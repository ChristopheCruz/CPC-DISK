"""Interface en ligne de commande de cpc_dsk.

Commandes :
    cpc-dsk new   <sortie.dsk> [--tracks N] [--sides N] [--sectors N] [--sector-size N]
    cpc-dsk info  <disk.dsk>
    cpc-dsk list  <disk.dsk> [--source filer|amsdos]
    cpc-dsk read  <disk.dsk> <nom> --out <local> [--source filer|amsdos]
    cpc-dsk write <disk.dsk> <nom> <local> [--fs both|filer|amsdos]
                          [--type basic|binary] [--load 0xADDR]
    cpc-dsk delete <disk.dsk> <nom>
    cpc-dsk hex   <disk.dsk> <piste> <secteur>
    cpc-dsk sector <disk.dsk> <piste> <secteur> [--write-file LOCAL]
"""

from __future__ import annotations

import argparse
import sys

from cpc_dsk.core import geometry
from cpc_dsk.core.adf import ADFDisk, ADFError
from cpc_dsk.core.cpcfs import (
    CpcError,
    CpcFilesystem,
    FT_BASIC,
    FT_BINARY,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def hexdump(data: bytes, width: int = 16) -> str:
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk).ljust(width * 3 - 1)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part}  |{ascii_part}|")
    return "\n".join(lines)


def _load(path: str) -> ADFDisk:
    try:
        return ADFDisk.load(path)
    except (OSError, ADFError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        raise SystemExit(1)


def _fs(disk: ADFDisk) -> CpcFilesystem:
    return CpcFilesystem(disk)


def _format_file(f) -> str:
    return (f"{f.name:14s} [{f.source:<12s}] {f.type_name:5s} "
            f"len={f.length:6d} load={f.load_addr:#06x} @0x{f.offset:06X}")


# --------------------------------------------------------------------------- #
# Sous-commandes
# --------------------------------------------------------------------------- #
def cmd_new(args) -> None:
    disk = ADFDisk.new_blank(
        tracks=args.tracks, sides=args.sides,
        sectors=args.sectors, sector_size=args.sector_size)
    disk.save(args.output)
    print(f"Disquette créée: {args.output}")
    print(f"  {disk.summary()}")


def cmd_info(args) -> None:
    disk = _load(args.disk)
    print(f"Fichier : {args.disk}")
    print(f"  {disk.summary()}")
    print(f"Fichiers:")
    for f in _fs(disk).list_files():
        print(f"  {_format_file(f)}")


def cmd_list(args) -> None:
    disk = _load(args.disk)
    files = _fs(disk).list_files(source=args.source)
    if not files:
        print("(aucun fichier détecté)")
        return
    for f in files:
        print(_format_file(f))


def cmd_read(args) -> None:
    disk = _load(args.disk)
    data = _fs(disk).read_file(args.name, source=args.source)
    with open(args.out, "wb") as fh:
        fh.write(data)
    print(f"Fichier {args.name!r} ({len(data)} o) extrait vers {args.out}.")


def cmd_write(args) -> None:
    disk = _load(args.disk)
    with open(args.local, "rb") as fh:
        data = fh.read()
    ftype = FT_BASIC if args.type == "basic" else FT_BINARY
    f = _fs(disk).write_file(
        args.name, data, file_type=ftype,
        load_addr=args.load, exec_addr=args.load,
        mode=args.fs)
    disk.save(args.disk)
    print(f"Fichier {f.name!r} ({f.length} o, {f.source}) "
          f"écrit sur {args.disk} @0x{f.offset:06X}.")


def cmd_delete(args) -> None:
    disk = _load(args.disk)
    _fs(disk).delete_file(args.name)
    disk.save(args.disk)
    print(f"Fichier {args.name!r} supprimé de {args.disk}.")


def cmd_hex(args) -> None:
    disk = _load(args.disk)
    data = disk.get_sector(args.track, args.sector)
    print(hexdump(data))


def cmd_sector(args) -> None:
    disk = _load(args.disk)
    if args.write_file:
        with open(args.write_file, "rb") as fh:
            data = fh.read()
        disk.set_sector(args.track, args.sector, data)
        disk.save(args.disk)
        print(f"Secteur (piste={args.track} secteur={args.sector}) "
              f"écrit depuis {args.write_file}.")
    else:
        data = disk.get_sector(args.track, args.sector)
        print(f"Secteur (piste={args.track} secteur={args.sector}) "
              f"— {len(data)} octets:")
        print(hexdump(data))


# --------------------------------------------------------------------------- #
# Parseur
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cpc-dsk",
        description="Éditeur de disquettes virtuelles .dsk (CPC) & Gotek.")
    sub = p.add_subparsers(dest="command", required=True)

    n = sub.add_parser("new", help="Créer une disquette vierge.")
    n.add_argument("output")
    n.add_argument("--tracks", type=int, default=geometry.DEFAULT_TRACKS)
    n.add_argument("--sides", type=int, default=geometry.DEFAULT_SIDES)
    n.add_argument("--sectors", type=int, default=geometry.DEFAULT_SECTORS)
    n.add_argument("--sector-size", type=int, default=geometry.DEFAULT_SECTOR_SIZE)
    n.set_defaults(func=cmd_new)

    i = sub.add_parser("info", help="Infos géométrie + fichiers.")
    i.add_argument("disk")
    i.set_defaults(func=cmd_info)

    l = sub.add_parser("list", help="Lister les fichiers (Filer + AMSDOS).")
    l.add_argument("disk")
    l.add_argument("--source", choices=["filer", "amsdos"],
                   help="N'afficher qu'une seule couche.")
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("read", help="Extraire un fichier vers un fichier local.")
    r.add_argument("disk")
    r.add_argument("name", help="Nom du fichier sur la disquette.")
    r.add_argument("--out", required=True, help="Fichier de sortie local.")
    r.add_argument("--source", choices=["filer", "amsdos"],
                   help="Couche à lire (par défaut: AMSDOS si présent, "
                        "sinon Filer).")
    r.set_defaults(func=cmd_read)

    w = sub.add_parser("write", help="Copier un fichier local sur la disquette.")
    w.add_argument("disk")
    w.add_argument("name", help="Nom du fichier sur la disquette (8.3).")
    w.add_argument("local", help="Fichier local à copier.")
    w.add_argument("--fs", choices=["both", "filer", "amsdos"], default="both",
                   help="both (défaut) = répertoire Filer + objet AMSDOS ; "
                        "filer = DOS/Gotek seul ; amsdos = émulateurs seuls.")
    w.add_argument("--type", choices=["basic", "binary"], default="binary")
    w.add_argument("--load", type=lambda s: int(s, 0), default=0x4000,
                   help="Adresse de chargement (décimal ou 0xhex) — objet "
                        "AMSDOS uniquement.")
    w.set_defaults(func=cmd_write)

    d = sub.add_parser("delete", help="Supprimer un fichier de la disquette.")
    d.add_argument("disk")
    d.add_argument("name", help="Nom du fichier à supprimer.")
    d.set_defaults(func=cmd_delete)

    h = sub.add_parser("hex", help="Hexdump d'un secteur.")
    h.add_argument("disk")
    h.add_argument("track", type=int)
    h.add_argument("sector", type=int)
    h.set_defaults(func=cmd_hex)

    s = sub.add_parser("sector", help="Lire/écrire un secteur brut.")
    s.add_argument("disk")
    s.add_argument("track", type=int)
    s.add_argument("sector", type=int)
    s.add_argument("--write-file", help="Fichier local à écrire dans le secteur.")
    s.set_defaults(func=cmd_sector)

    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ADFError, CpcError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
