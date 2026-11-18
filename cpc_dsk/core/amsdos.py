"""Catalogue AMSDOS / CP/M 2.2 : le système de fichiers que lit le vrai CPC.

C'est le format qu'écrivent le firmware AMSDOS du CPC, CP/M 2.2, RASM,
WinAPE ou CPCDiskXP, et que lit le Gotek branché sur la machine.

Formats reconnus (40 pistes × 1 face × 9 secteurs de 512 o)
=========================================================
::

    Format   IDs de secteur   Pistes réservées   Blocs (DSM+1)
    DATA     &C1..&C9         0                  180
    SYSTEM   &41..&49         2 (boot + CP/M)    171

Les secteurs sont repérés par leur **ID** (et non leur position physique) :
l'entrelacement des pistes (C1 C6 C2 C7 …) n'a pas d'influence.

Organisation logique
====================
- Le secteur logique ``s`` (compté depuis la première piste de données) est
  le secteur d'ID ``base + s % 9`` de la piste ``réservées + s // 9``.
- Un **bloc** fait 1 Ko = 2 secteurs logiques consécutifs.
- Les blocs 0 et 1 forment le **catalogue** : 64 entrées de 32 octets.

Entrée du catalogue (32 octets)
===============================
::

    Offset  Taille  Champ
    0x00    1       n° d'utilisateur (0..15) ; 0xE5 = entrée libre
    0x01    8       nom (bit 7 = attributs, ignoré à la lecture)
    0x09    3       extension (bit 7 de 0x09 = lecture seule,
                    bit 7 de 0x0A = fichier système / caché)
    0x0C    1       EX : n° d'extension, bits 0-4
    0x0D    1       S1 (0)
    0x0E    1       S2 : n° d'extension, bits 5 et plus
    0x0F    1       RC : nombre d'enregistrements de 128 o de l'extension
    0x10    16      numéros des blocs de 1 Ko (0 = non utilisé)

Une extension couvre 16 Ko au plus (16 blocs). Un fichier plus gros occupe
plusieurs entrées (extensions 0, 1, 2…). La taille d'un fichier est
``128 × (128 × n°_dernière_extension + RC_dernière)`` octets.

En-tête AMSDOS (128 octets, en tête des fichiers binaires et BASIC)
====================================================================
::

    0x00    1       utilisateur
    0x01    11      nom 8 + 3
    0x12    1       type : 0 BASIC, 1 BASIC protégé, 2 binaire
    0x15    2       adresse de chargement
    0x18    2       longueur (16 bits)
    0x1A    2       adresse d'exécution
    0x40    3       longueur (24 bits)
    0x43    2       somme des octets 0x00..0x42

Les fichiers ASCII (et ceux de CP/M) n'ont pas d'en-tête : leur longueur
est arrondie à 128 octets.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from cpc_dsk.core.adf import ADFDisk, TRACK_INFO_SIZE, TRACK_INFO_NUM_SECTORS_OFFSET
from cpc_dsk.core.cpcfs import (
    AMSDOS_HEADER_SIZE,
    CHECKSUM_COVERED,
    CHECKSUM_OFFSET,
    EXEC_OFFSET,
    FT_BASIC,
    FT_BINARY,
    FT_PROTECTED,
    FT_UNKNOWN,
    LEN16_OFFSET,
    LEN24_OFFSET,
    LOAD_OFFSET,
    NAME_OFFSET,
    NAME_SIZE,
    TYPE_OFFSET,
    CpcError,
    CpcFile,
    _normalize_83,
)

SECTORS_PER_TRACK = 9
SECTOR_SIZE = 512
BLOCK_SIZE = 1024
RECORD_SIZE = 128
DIR_ENTRIES = 64
DIR_BLOCKS = 2
ENTRY_SIZE = 32
EXTENT_RECORDS = 128          # 16 Ko par extension
BLOCKS_PER_ENTRY = 16
FREE_USER = 0xE5


@dataclass(frozen=True)
class AmsdosFormat:
    """Paramètres d'un format de disquette CPC (DPB d'AMSDOS)."""
    name: str          # "DATA" | "SYSTEM"
    first_id: int      # ID du premier secteur
    reserved: int      # pistes réservées avant les données
    blocks: int        # nombre de blocs (DSM + 1)


DATA = AmsdosFormat("DATA", 0xC1, 0, 180)
SYSTEM = AmsdosFormat("SYSTEM", 0x41, 2, 171)
FORMATS = (DATA, SYSTEM)


@dataclass
class AmsdosFile(CpcFile):
    """Un fichier du catalogue (avec ses blocs et ses attributs)."""
    user: int = 0
    blocks: List[int] = field(default_factory=list)
    records: int = 0           # taille au catalogue, en enregistrements de 128 o
    has_header: bool = False
    read_only: bool = False
    hidden: bool = False
    field11: str = ""          # nom tel qu'au catalogue (8 + 3, sans attributs)


# --------------------------------------------------------------------------- #
# Détection
# --------------------------------------------------------------------------- #
def _track_ids(disk: ADFDisk, track: int) -> List[int]:
    off = disk.track_offsets[track]
    ns = disk._raw[off + TRACK_INFO_NUM_SECTORS_OFFSET]
    return [disk._raw[off + 0x18 + i * 8 + 2] for i in range(ns)]


def detect_format(disk: ADFDisk) -> Optional[AmsdosFormat]:
    """Format AMSDOS de la disquette (DATA, SYSTEM) ou ``None``.

    Il faut 9 secteurs de 512 o d'IDs ``base..base+8`` sur la piste 0 et
    assez de pistes pour tous les blocs.
    """
    if disk.num_tracks == 0:
        return None
    try:
        ids = set(_track_ids(disk, 0))
    except IndexError:
        return None
    for fmt in FORMATS:
        if ids != set(range(fmt.first_id, fmt.first_id + SECTORS_PER_TRACK)):
            continue
        sectors = fmt.blocks * BLOCK_SIZE // SECTOR_SIZE
        last_track = fmt.reserved + (sectors - 1) // SECTORS_PER_TRACK
        if last_track >= disk.num_tracks:
            return None
        if disk.track_sizes[0] != TRACK_INFO_SIZE + SECTORS_PER_TRACK * SECTOR_SIZE:
            return None
        return fmt
    return None


def is_amsdos_disk(disk: ADFDisk) -> bool:
    return detect_format(disk) is not None


# --------------------------------------------------------------------------- #
# En-tête AMSDOS
# --------------------------------------------------------------------------- #
def parse_header(data: bytes) -> Optional[dict]:
    """Décode l'en-tête AMSDOS en tête de ``data`` (``None`` s'il n'y en a pas)."""
    if len(data) < AMSDOS_HEADER_SIZE:
        return None
    head = data[:CHECKSUM_OFFSET + 2]
    if not any(head):
        return None
    csum = sum(data[:CHECKSUM_COVERED]) & 0xFFFF
    if csum != struct.unpack_from("<H", data, CHECKSUM_OFFSET)[0]:
        return None
    length = int.from_bytes(data[LEN24_OFFSET:LEN24_OFFSET + 3], "little")
    return {
        "type": data[TYPE_OFFSET],
        "load": struct.unpack_from("<H", data, LOAD_OFFSET)[0],
        "exec": struct.unpack_from("<H", data, EXEC_OFFSET)[0],
        "length": length,
    }


def build_header(field11: str, length: int, file_type: int = FT_BINARY,
                 load_addr: int = 0, exec_addr: int = 0, user: int = 0) -> bytes:
    """En-tête AMSDOS de 128 octets (même agencement que celui du firmware)."""
    hdr = bytearray(AMSDOS_HEADER_SIZE)
    hdr[0] = user
    hdr[NAME_OFFSET:NAME_OFFSET + NAME_SIZE] = field11.encode("latin1")
    hdr[TYPE_OFFSET] = file_type & 0xFF
    hdr[LOAD_OFFSET:LOAD_OFFSET + 2] = struct.pack("<H", load_addr & 0xFFFF)
    hdr[LEN16_OFFSET:LEN16_OFFSET + 2] = struct.pack("<H", length & 0xFFFF)
    hdr[EXEC_OFFSET:EXEC_OFFSET + 2] = struct.pack("<H", exec_addr & 0xFFFF)
    hdr[LEN24_OFFSET:LEN24_OFFSET + 3] = length.to_bytes(3, "little")
    csum = sum(hdr[:CHECKSUM_COVERED]) & 0xFFFF
    hdr[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 2] = struct.pack("<H", csum)
    return bytes(hdr)


def _split_user(name: str) -> Tuple[Optional[int], str]:
    """``"3:JEU.BAS"`` -> ``(3, "JEU.BAS")`` ; sans préfixe -> ``(None, nom)``."""
    head, sep, rest = name.partition(":")
    if sep and head.strip().isdigit():
        return int(head), rest
    return None, name


def to_field11(name: str) -> str:
    """Nom lisible (``JEU.BAS``) ou champ 8+3 vers le champ de 11 caractères.

    Le point est le séparateur dès qu'il est présent (``ARKANO2.BIN`` fait
    11 caractères mais n'est pas un champ brut).
    """
    name = name.strip().upper()
    if "." in name:
        base, _, ext = name.rpartition(".")
        if len(base) > 8 or len(ext) > 3:
            raise CpcError(f"Nom trop long (8 + 3 caractères): {name!r}")
        return _normalize_83(base.ljust(8) + ext.ljust(3))
    return _normalize_83(name)


def _display_name(field11: str) -> str:
    base, ext = field11[:8].rstrip(), field11[8:].rstrip()
    return f"{base}.{ext}" if ext else base


# --------------------------------------------------------------------------- #
# Système de fichiers
# --------------------------------------------------------------------------- #
class AmsdosFilesystem:
    """Fichiers d'une disquette au format AMSDOS (DATA) ou CP/M (SYSTEM).

    Même interface que :class:`cpc_dsk.core.cpcfs.CpcFilesystem`
    (``list_files``, ``find``, ``read_file``, ``write_file``,
    ``delete_file``) : l'interface graphique et la ligne de commande
    l'utilisent sans changement.
    """

    def __init__(self, disk: ADFDisk, fmt: Optional[AmsdosFormat] = None):
        self.disk = disk
        self.fmt = fmt or detect_format(disk)
        if self.fmt is None:
            raise CpcError("Disquette sans catalogue AMSDOS (format DATA ou SYSTEM).")

    # ------------------------------------------------------------------ #
    # Secteurs et blocs
    # ------------------------------------------------------------------ #
    def _locate(self, logical: int) -> Tuple[int, int]:
        """(piste, index physique) du secteur logique ``logical``."""
        track = self.fmt.reserved + logical // SECTORS_PER_TRACK
        sec_id = self.fmt.first_id + logical % SECTORS_PER_TRACK
        try:
            return track, _track_ids(self.disk, track).index(sec_id)
        except (ValueError, IndexError):
            raise CpcError(f"Secteur &{sec_id:02X} introuvable sur la piste {track}.")

    def _sector_offset(self, logical: int) -> int:
        track, idx = self._locate(logical)
        return self.disk.track_offsets[track] + TRACK_INFO_SIZE + idx * SECTOR_SIZE

    def read_block(self, block: int) -> bytes:
        out = bytearray()
        for s in (2 * block, 2 * block + 1):
            track, idx = self._locate(s)
            out += self.disk.get_sector(track, idx)
        return bytes(out)

    def write_block(self, block: int, data: bytes) -> None:
        data = data.ljust(BLOCK_SIZE, b"\x00")
        for k, s in enumerate((2 * block, 2 * block + 1)):
            track, idx = self._locate(s)
            self.disk.set_sector(track, idx, data[k * SECTOR_SIZE:(k + 1) * SECTOR_SIZE])

    # ------------------------------------------------------------------ #
    # Catalogue
    # ------------------------------------------------------------------ #
    def read_catalog(self) -> bytearray:
        return bytearray(b"".join(self.read_block(b) for b in range(DIR_BLOCKS)))

    def write_catalog(self, cat: bytes) -> None:
        for b in range(DIR_BLOCKS):
            self.write_block(b, bytes(cat[b * BLOCK_SIZE:(b + 1) * BLOCK_SIZE]))

    @staticmethod
    def _entries(cat: bytes):
        for slot in range(DIR_ENTRIES):
            yield slot, bytes(cat[slot * ENTRY_SIZE:(slot + 1) * ENTRY_SIZE])

    def _groups(self, cat: bytes) -> Dict[Tuple[int, str], List[Tuple[int, bytes]]]:
        """Entrées vivantes groupées par (utilisateur, champ 8+3), triées par extension."""
        groups: Dict[Tuple[int, str], List[Tuple[int, bytes]]] = {}
        for slot, e in self._entries(cat):
            user = e[0]
            if user > 15:          # 0xE5 = libre ; 16..31 et plus = réservé
                continue
            field11 = bytes(b & 0x7F for b in e[1:12]).decode("latin1")
            ext_no = (e[12] & 0x1F) | ((e[14] & 0x3F) << 5)
            groups.setdefault((user, field11), []).append((ext_no, e))
        for v in groups.values():
            v.sort(key=lambda t: t[0])
        return groups

    def _used_blocks(self, cat: bytes) -> set:
        used = set(range(DIR_BLOCKS))
        for _, e in self._entries(cat):
            if e[0] == FREE_USER:
                continue
            used.update(b for b in e[16:32] if b)
        return used

    def free_blocks(self) -> List[int]:
        used = self._used_blocks(self.read_catalog())
        return [b for b in range(DIR_BLOCKS, self.fmt.blocks) if b not in used]

    def free_bytes(self) -> int:
        return len(self.free_blocks()) * BLOCK_SIZE

    def free_entries(self) -> int:
        return sum(1 for _, e in self._entries(self.read_catalog()) if e[0] == FREE_USER)

    # ------------------------------------------------------------------ #
    # Lecture
    # ------------------------------------------------------------------ #
    def _make_file(self, user: int, field11: str,
                   extents: List[Tuple[int, bytes]]) -> AmsdosFile:
        blocks: List[int] = []
        for _, e in extents:
            blocks.extend(b for b in e[16:32] if b and b < self.fmt.blocks)
        last_no, last = extents[-1]
        records = last_no * EXTENT_RECORDS + last[15]
        first = self.read_block(blocks[0]) if blocks else b""
        hdr = parse_header(first)
        size = records * RECORD_SIZE
        if hdr and hdr["length"] <= size - AMSDOS_HEADER_SIZE:
            ftype, load, exe, length = hdr["type"], hdr["load"], hdr["exec"], hdr["length"]
            has_header = True
        else:
            ftype, load, exe, length, has_header = FT_UNKNOWN, 0, 0, size, False
        name = _display_name(field11)
        e0 = extents[0][1]
        return AmsdosFile(
            name=name if user == 0 else f"{user}:{name}",
            offset=(self._sector_offset(2 * blocks[0]) if blocks else 0),
            file_type=ftype, load_addr=load, exec_addr=exe, length=length,
            source="CPM" if self.fmt is SYSTEM else "AMSDOS",
            user=user, blocks=blocks, records=records, has_header=has_header,
            read_only=bool(e0[9] & 0x80), hidden=bool(e0[10] & 0x80),
            field11=field11)

    def list_files(self, source: Optional[str] = None) -> List[AmsdosFile]:
        """Fichiers dans l'ordre du catalogue. ``source`` est ignoré (une seule couche)."""
        cat = self.read_catalog()
        return [self._make_file(u, f, ext) for (u, f), ext in self._groups(cat).items()]

    def find(self, name: str, source: Optional[str] = None) -> Optional[AmsdosFile]:
        user, bare = _split_user(name)
        target = to_field11(bare)
        for f in self.list_files():
            if f.field11 == target and (user is None or f.user == user):
                return f
        return None

    def file_sectors(self, f: AmsdosFile) -> set:
        """Secteurs occupés par le fichier : {(piste, index physique)}."""
        out = set()
        for b in f.blocks:
            out.add(self._locate(2 * b))
            out.add(self._locate(2 * b + 1))
        return out

    def read_raw(self, name: str) -> bytes:
        """Contenu complet au catalogue (en-tête AMSDOS compris)."""
        f = self.find(name)
        if f is None:
            raise CpcError(f"Fichier introuvable: {name!r}")
        data = b"".join(self.read_block(b) for b in f.blocks)
        return data[:f.records * RECORD_SIZE]

    def read_file(self, name: str, source: Optional[str] = None) -> bytes:
        """Données du fichier : sans en-tête, à la longueur exacte s'il en a un."""
        f = self.find(name)
        if f is None:
            raise CpcError(f"Fichier introuvable: {name!r}")
        raw = self.read_raw(name)
        if f.has_header:
            return raw[AMSDOS_HEADER_SIZE:AMSDOS_HEADER_SIZE + f.length]
        return raw

    # ------------------------------------------------------------------ #
    # Écriture / suppression
    # ------------------------------------------------------------------ #
    def write_file(self, name: str, data: bytes,
                   file_type: int = FT_BINARY,
                   load_addr: int = 0,
                   exec_addr: int = 0,
                   mode: str = "amsdos",
                   overwrite: bool = False,
                   user: int = 0) -> AmsdosFile:
        """Ajoute un fichier au catalogue.

        ``mode`` : ``"amsdos"`` ou ``"both"`` = avec en-tête AMSDOS (fichier
        binaire ou BASIC, comme ``SAVE`` sur le CPC) ; ``"raw"``, ``"filer"``
        ou ``"cpm"`` = données brutes (fichier ASCII, programme CP/M).
        """
        if mode not in ("amsdos", "both", "raw", "filer", "cpm"):
            raise CpcError(f"Mode inconnu: {mode!r}.")
        if not data:
            raise CpcError("Fichier vide: rien à écrire.")
        u, bare = _split_user(name)
        user = u if u is not None else user
        if not 0 <= user <= 15:
            raise CpcError("Numéro d'utilisateur hors de 0..15.")
        field11 = to_field11(bare)
        if self.find(f"{user}:{field11}") is not None:
            if not overwrite:
                raise CpcError(f"Fichier déjà présent: {_display_name(field11)}")
            self.delete_file(f"{user}:{field11}")

        with_header = mode in ("amsdos", "both")
        payload = (build_header(field11, len(data), file_type, load_addr, exec_addr, user)
                   + data) if with_header else data
        records = -(-len(payload) // RECORD_SIZE)
        if not with_header and len(payload) % RECORD_SIZE:
            payload += b"\x1A" * (RECORD_SIZE - len(payload) % RECORD_SIZE)  # fin ASCII
        n_blocks = -(-len(payload) // BLOCK_SIZE)
        n_entries = -(-n_blocks // BLOCKS_PER_ENTRY)

        cat = self.read_catalog()
        free_b = [b for b in range(DIR_BLOCKS, self.fmt.blocks)
                  if b not in self._used_blocks(cat)]
        free_e = [s for s, e in self._entries(cat) if e[0] == FREE_USER]
        if n_blocks > len(free_b):
            raise CpcError(f"Disquette pleine : il faut {n_blocks} Ko, "
                           f"il en reste {len(free_b)}.")
        if n_entries > len(free_e):
            raise CpcError("Catalogue plein (64 entrées).")

        blocks = free_b[:n_blocks]
        for i, b in enumerate(blocks):
            self.write_block(b, payload[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE])
        for k in range(n_entries):
            e = bytearray(ENTRY_SIZE)
            e[0] = user
            e[1:12] = field11.encode("latin1")
            e[12] = k & 0x1F
            e[14] = k >> 5
            e[15] = min(EXTENT_RECORDS, records - k * EXTENT_RECORDS)
            chunk = blocks[k * BLOCKS_PER_ENTRY:(k + 1) * BLOCKS_PER_ENTRY]
            e[16:16 + len(chunk)] = bytes(chunk)
            slot = free_e[k]
            cat[slot * ENTRY_SIZE:(slot + 1) * ENTRY_SIZE] = e
        self.write_catalog(cat)
        f = self.find(f"{user}:{field11}")
        assert f is not None
        return f

    def delete_file(self, name: str) -> None:
        """Efface un fichier comme AMSDOS : ses entrées passent à 0xE5."""
        f = self.find(name)
        if f is None:
            raise CpcError(f"Fichier introuvable: {name!r}")
        cat = self.read_catalog()
        target = f.field11
        for slot, e in self._entries(cat):
            if e[0] == f.user and bytes(b & 0x7F for b in e[1:12]).decode("latin1") == target:
                cat[slot * ENTRY_SIZE] = FREE_USER
        self.write_catalog(cat)


def new_data_disk() -> ADFDisk:
    """Disquette vierge au format DATA (catalogue vide, secteurs à 0xE5)."""
    return ADFDisk.new_blank()


__all__ = [
    "AmsdosFormat", "AmsdosFile", "AmsdosFilesystem", "DATA", "SYSTEM",
    "detect_format", "is_amsdos_disk", "parse_header", "build_header",
    "new_data_disk", "FT_BASIC", "FT_BINARY", "FT_PROTECTED", "FT_UNKNOWN",
]
