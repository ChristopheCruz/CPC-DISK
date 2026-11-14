"""Système de fichiers CPC : fichiers AMSDOS sur une image .dsk.

Au-dessus du conteneur :mod:`cpc_dsk.core.adf`, ce module manipule les
**fichiers** d'une disquette. Chaque fichier sur un disque CPC commence par un
**en-tête AMSDOS** (128 octets) suivi des données.

En-tête AMSDOS (128 octets) — vérifié sur images réelles (greed.dsk)
====================================================================
::

    Offset  Taille  Champ
    0x00    1       (réserve / partie de la zone contrôlée)
    0x01    11      nom du fichier (8.3, latin1)
    0x12    2       type de fichier (LE16): 0=BASIC, 1=BASIC protégé, 2=binaire
    0x15    2       adresse de chargement (LE16)
    0x18    2       longueur (LE16) / adresse d'entrée (binaire)
    0x1A    2       adresse d'exécution (LE16)
    0x40    3       longueur totale (24 bits, LE)
    0x43    2       checksum (LE16) = somme des octets 0x00..0x42 (67 o)
    0x80    ...     les données du fichier débutent à l'offset +128

Les fichiers sont localisés en balayant l'image à la recherche d'en-têtes
AMSDOS dont le checksum est valide et le nom exploitable (c'est la méthode
utilisée par l'émulateur CERMU).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional

from cpc_dsk.core.adf import ADFDisk, ADFError, TRACK_INFO_SIZE

# --- Constantes de l'en-tête AMSDOS ---
AMSDOS_HEADER_SIZE = 128
NAME_OFFSET = 1
NAME_SIZE = 11
TYPE_OFFSET = 0x12
LOAD_OFFSET = 0x15
LEN16_OFFSET = 0x18
EXEC_OFFSET = 0x1A
LEN24_OFFSET = 0x40
CHECKSUM_OFFSET = 0x43
CHECKSUM_COVERED = 67  # somme des octets [0x00:0x43]

# Types de fichier
FT_BASIC = 0
FT_PROTECTED = 1
FT_BINARY = 2


class CpcError(Exception):
    """Erreur du système de fichiers CPC."""


def _clean_name(raw: bytes) -> str:
    """Nettoie un nom AMSDOS (supprime NUL et espaces de fin)."""
    return raw.split(b"\x00", 1)[0].decode("latin1").rstrip()


_ALLOWED_NAME_BYTES = (
    set(range(ord("A"), ord("Z") + 1))
    | set(range(ord("a"), ord("z") + 1))
    | set(range(ord("0"), ord("9") + 1))
    | {ord("."), ord("_"), ord("-")}
)


def _valid_name(raw: bytes) -> bool:
    """Heuristique anti-faux-positifs pour un nom de fichier CPC.

    Un nom valide ne contient que des lettres, chiffres, ``. _ -`` (plus des
    espaces de remplissage et un NUL final). Toute autre octet (symbole,
    caractère latin-1 étendu, contrôle) écarte l'en-tête comme bruit. Au moins
    2 caractères « portants » sont exigés.
    """
    carrying = 0
    for b in raw:
        if b == 0 or b == 32:          # NUL / espace de remplissage
            continue
        if b in _ALLOWED_NAME_BYTES:
            carrying += 1
        else:
            return False
    return carrying >= 2


@dataclass
class CpcFile:
    """Un fichier AMSDOS localisé sur la disquette."""
    name: str
    offset: int          # position de l'en-tête AMSDOS dans l'image
    file_type: int       # FT_BASIC / FT_PROTECTED / FT_BINARY
    load_addr: int
    exec_addr: int
    length: int

    @property
    def type_name(self) -> str:
        return {FT_BASIC: "BASIC", FT_PROTECTED: "PROT",
                FT_BINARY: "BIN"}.get(self.file_type, f"TYPE{self.file_type}")


class CpcFilesystem:
    """Système de fichiers d'une image .dsk (via balayage AMSDOS)."""

    def __init__(self, disk: ADFDisk):
        self.disk = disk

    # ------------------------------------------------------------------ #
    # Liste / lecture
    # ------------------------------------------------------------------ #
    def list_files(self) -> List[CpcFile]:
        """Balaye l'image et retourne les fichiers AMSDOS valides."""
        raw = bytes(self.disk._raw)
        files: List[CpcFile] = []
        for pos in range(0, len(raw) - (CHECKSUM_OFFSET + 2)):
            name_raw = raw[NAME_OFFSET + pos: NAME_OFFSET + pos + NAME_SIZE]
            if not _valid_name(name_raw):
                continue
            s = sum(raw[pos:pos + CHECKSUM_COVERED]) & 0xFFFF
            stored = raw[pos + CHECKSUM_OFFSET] | (raw[pos + CHECKSUM_OFFSET + 1] << 8)
            if s != stored:
                continue
            ftype = raw[pos + TYPE_OFFSET] | (raw[pos + TYPE_OFFSET + 1] << 8)
            load = raw[pos + LOAD_OFFSET] | (raw[pos + LOAD_OFFSET + 1] << 8)
            execa = raw[pos + EXEC_OFFSET] | (raw[pos + EXEC_OFFSET + 1] << 8)
            full = (raw[pos + LEN24_OFFSET]
                    | (raw[pos + LEN24_OFFSET + 1] << 8)
                    | (raw[pos + LEN24_OFFSET + 2] << 16))
            files.append(CpcFile(
                name=_clean_name(name_raw),
                offset=pos,
                file_type=ftype,
                load_addr=load,
                exec_addr=execa,
                length=full,
            ))
        return files

    def find(self, name: str) -> Optional[CpcFile]:
        """Retrouve un fichier par nom (insensible aux espaces de fin)."""
        target = name.rstrip().upper()
        for f in self.list_files():
            if f.name.rstrip().upper() == target:
                return f
        return None

    def read_file(self, name: str) -> bytes:
        """Lit les données d'un fichier (après l'en-tête AMSDOS)."""
        f = self.find(name)
        if f is None:
            raise CpcError(f"Fichier introuvable: {name!r}")
        raw = bytes(self.disk._raw)
        start = f.offset + AMSDOS_HEADER_SIZE
        return raw[start:start + f.length]

    # ------------------------------------------------------------------ #
    # Écriture
    # ------------------------------------------------------------------ #
    def _find_free(self, size: int) -> Optional[int]:
        """Trouve une zone libre (d'octets nuls) de ``size`` octets contigus."""
        raw = self.disk._raw
        for track in range(self.disk.num_tracks):
            base = self.disk.track_offsets[track] + TRACK_INFO_SIZE
            tsize = self.disk.track_sizes[track] - TRACK_INFO_SIZE
            i = 0
            while i < tsize:
                if raw[base + i] == 0:
                    j = i
                    while (j < tsize and raw[base + j] == 0
                           and j - i < size):
                        j += 1
                    if j - i >= size:
                        return base + i
                    i = j
                else:
                    i += 1
        return None

    def write_file(self, name: str, data: bytes,
                   file_type: int = FT_BINARY,
                   load_addr: int = 0,
                   exec_addr: int = 0) -> CpcFile:
        """Écrit un fichier sur la disquette (en-tête AMSDOS + données).

        Alloue la première zone libre. NB: ne met pas à jour le répertoire
        traditionnel CPC (à finaliser) ; les fichiers sont lisibles par les
        lecteurs qui balayent les en-têtes AMSDOS (ex. CERMU).
        """
        name_raw = name.encode("latin1")[:NAME_SIZE]
        if self.find(name) is not None:
            raise CpcError(f"Fichier déjà présent: {name!r}")

        hdr = bytearray(AMSDOS_HEADER_SIZE)
        hdr[NAME_OFFSET:NAME_OFFSET + len(name_raw)] = name_raw
        hdr[TYPE_OFFSET:TYPE_OFFSET + 2] = struct.pack("<H", file_type)
        hdr[LOAD_OFFSET:LOAD_OFFSET + 2] = struct.pack("<H", load_addr)
        hdr[LEN16_OFFSET:LEN16_OFFSET + 2] = struct.pack("<H", len(data) & 0xFFFF)
        hdr[EXEC_OFFSET:EXEC_OFFSET + 2] = struct.pack("<H", exec_addr)
        hdr[LEN24_OFFSET:LEN24_OFFSET + 3] = (len(data)).to_bytes(3, "little")
        csum = sum(hdr[:CHECKSUM_COVERED]) & 0xFFFF
        hdr[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 2] = struct.pack("<H", csum)

        pos = self._find_free(AMSDOS_HEADER_SIZE + len(data))
        if pos is None:
            raise CpcError(
                "Pas assez d'espace libre sur la disquette "
                f"(besoin de {AMSDOS_HEADER_SIZE + len(data)} o).")

        raw = self.disk._raw
        raw[pos:pos + AMSDOS_HEADER_SIZE] = hdr
        raw[pos + AMSDOS_HEADER_SIZE:pos + AMSDOS_HEADER_SIZE + len(data)] = data
        return CpcFile(name=name_raw.decode("latin1").rstrip(),
                       offset=pos, file_type=file_type,
                       load_addr=load_addr, exec_addr=exec_addr,
                       length=len(data))

    # ------------------------------------------------------------------ #
    # Répertoire (lecture, vue secondaire)
    # ------------------------------------------------------------------ #
    def read_directory_names(self) -> List[str]:
        """Lit les noms du répertoire CPC (piste 0, secteur 0, entrées 32 o)."""
        try:
            sec = self.disk.get_sector(0, 0)
        except (ADFError, IndexError):
            return []
        names: List[str] = []
        for i in range(len(sec) // 32):
            entry = sec[i * 32:(i + 1) * 32]
            if len(entry) < 13:
                break
            name_raw = entry[1:12]      # nom 8.3 (11 octets)
            if name_raw == b"\x00" * 11:
                continue
            if any(b == 0xE5 for b in entry):
                break
            nm = _clean_name(name_raw)
            if nm:
                names.append(nm)
        return names
