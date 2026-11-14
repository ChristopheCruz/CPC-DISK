"""Interface en ligne de commande de cpc_dsk.

Usage:
    cpc-dsk new   <sortie.dsk> [--tracks N] [--sides N] [--sectors N] [--sector-size N]
    cpc-dsk info  <disk.dsk>
    cpc-dsk sector <disk.dsk> <piste> <face> <secteur> [--write-file LOCAL]
    cpc-dsk hex   <disk.dsk> <piste> <face> <secteur>
    cpc-dsk dump  <disk.dsk> <piste> <face> <secteur> --out LOCAL
"""

from __future__ import annotations

import argparse
import sys

from cpc_dsk.core import geometry
from cpc_dsk.core.adf import ADFDisk, ADFError


# --------------------------------------------------------------------------- #
# Helpers d'affichage
# --------------------------------------------------------------------------- #
def hexdump(data: bytes, width: int = 16) -> str:
    """Formate ``data`` en hexdump classique (offset | hex | ASCII)."""
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        # Pad à largeur constante pour l'alignement.
        hex_part = hex_part.ljust(width * 3 - 1)
        ascii_part = "".join(
            chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part}  |{ascii_part}|")
    return "\n".join(lines)


def _load(path: str) -> ADFDisk:
    try:
        return ADFDisk.load(path)
    except (OSError, ADFError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        raise SystemExit(1)


# --------------------------------------------------------------------------- #
# Sous-commandes
# --------------------------------------------------------------------------- #
def cmd_new(args) -> None:
    disk = ADFDisk(tracks=args.tracks, sides=args.sides,
                   sectors_per_track=args.sectors, sector_size=args.sector_size)
    disk.save(args.output)
    print(f"Disquette ADF créée: {args.output}")
    print(f"  géométrie : {disk.tracks} pistes x {disk.sides} faces "
          f"x {disk.sectors_per_track} secteurs x {disk.sector_size} o")
    print(f"  capacité  : {disk.data_capacity} octets "
          f"({disk.data_capacity // 1024} Ko)")
    print(f"  taille    : {disk.expected_file_size()} octets")


def cmd_info(args) -> None:
    disk = _load(args.disk)
    print(f"Fichier   : {args.disk}")
    print(f"Géométrie : {disk.tracks} pistes x {disk.sides} faces "
          f"x {disk.sectors_per_track} secteurs x {disk.sector_size} o")
    print(f"Secteurs  : {disk.total_sectors}")
    print(f"Capacité  : {disk.data_capacity} octets "
          f"({disk.data_capacity // 1024} Ko)")
    print(f"Fichier   : {disk.expected_file_size()} octets attendus")


def cmd_sector(args) -> None:
    disk = _load(args.disk)
    if args.write_file:
        with open(args.write_file, "rb") as fh:
            data = fh.read()
        disk.set_sector(args.track, args.side, args.sector, data)
        disk.save(args.disk)
        print(f"Secteur ({args.track},{args.side},{args.sector}) "
              f"écrit depuis {args.write_file}.")
    else:
        data = disk.get_sector(args.track, args.side, args.sector)
        print(f"Secteur (piste={args.track} face={args.side} "
              f"secteur={args.sector}) — {len(data)} octets:")
        print(hexdump(data))


def cmd_hex(args) -> None:
    disk = _load(args.disk)
    data = disk.get_sector(args.track, args.side, args.sector)
    print(hexdump(data))


def cmd_dump(args) -> None:
    disk = _load(args.disk)
    data = disk.get_sector(args.track, args.side, args.sector)
    with open(args.out, "wb") as fh:
        fh.write(data)
    print(f"Secteur ({args.track},{args.side},{args.sector}) "
          f"exporté vers {args.out}.")


# --------------------------------------------------------------------------- #
# Parseur
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cpc-dsk",
        description="Éditeur de disquettes virtuelles .dsk (ADF) pour Amstrad CPC.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="Créer une disquette ADF vierge.")
    p_new.add_argument("output", help="Fichier .dsk à créer.")
    p_new.add_argument("--tracks", type=int, default=geometry.TRACKS_PER_SIDE)
    p_new.add_argument("--sides", type=int, default=geometry.NUM_SIDES)
    p_new.add_argument("--sectors", type=int, default=geometry.SECTORS_PER_TRACK)
    p_new.add_argument("--sector-size", type=int, default=geometry.SECTOR_SIZE)
    p_new.set_defaults(func=cmd_new)

    p_info = sub.add_parser("info", help="Afficher les informations d'une disquette.")
    p_info.add_argument("disk", help="Fichier .dsk.")
    p_info.set_defaults(func=cmd_info)

    p_sec = sub.add_parser("sector",
                           help="Lire un secteur brut (ou l'écrire avec --write-file).")
    p_sec.add_argument("disk", help="Fichier .dsk.")
    p_sec.add_argument("track", type=int, help="N° de piste (0-39).")
    p_sec.add_argument("side", type=int, help="N° de face (0-1).")
    p_sec.add_argument("sector", type=int, help="N° de secteur (0-9).")
    p_sec.add_argument("--write-file",
                       help="Fichier local dont le contenu est écrit dans le secteur.")
    p_sec.set_defaults(func=cmd_sector)

    p_hex = sub.add_parser("hex", help="Hexdump d'un secteur brut.")
    p_hex.add_argument("disk", help="Fichier .dsk.")
    p_hex.add_argument("track", type=int)
    p_hex.add_argument("side", type=int)
    p_hex.add_argument("sector", type=int)
    p_hex.set_defaults(func=cmd_hex)

    p_dump = sub.add_parser("dump", help="Exporter un secteur brut vers un fichier.")
    p_dump.add_argument("disk", help="Fichier .dsk.")
    p_dump.add_argument("track", type=int)
    p_dump.add_argument("side", type=int)
    p_dump.add_argument("sector", type=int)
    p_dump.add_argument("--out", required=True, help="Fichier de sortie.")
    p_dump.set_defaults(func=cmd_dump)

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ADFError as exc:
        print(f"Erreur ADF: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
