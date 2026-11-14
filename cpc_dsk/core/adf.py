"""Lecture / écriture du format d'image de disque ADF (Amstrad Disk File).

Le format ADF est une image « brute » des pistes d'une disquette CPC, telle
qu'utilisée par les émulateurs (Fuse, CPCJS). Ce module permet de :

    - créer une disquette vierge,
    - lire / écrire des secteurs bruts,
    - sauvegarder / charger une image ``.dsk``.

Structure de fichier implémentée (documentée, autocohérente)
=============================================================
::

    +---------------------------+
    | En-tête de fichier (40 o) |
    +---------------------------+
    | Piste 0, face 0 : 10 sect. |
    | Piste 0, face 1 : 10 sect. |
    |   ...                     |
    | Piste 39, face 1: 10 sect. |
    +---------------------------+

En-tête (40 octets)
-------------------
::

    Offset  Taille  Champ
    0x00    4       signature  b"CPC1"
    0x04    1       version    = 1
    0x05    1       pistes/face = 40
    0x06    1       faces       = 2
    0x07    1       secteurs/piste = 10
    0x08    2       taille secteur (256, little-endian)
    0x0A    30      réservé (0x00)

Secteur (270 octets), disposition canonique FM/MFM « logique »
--------------------------------------------------------------
::

    Offset  Taille  Champ
    0x00    4       préambule / synchronisation (0x00 x4)
    0x04    1       marque d'adresse ID   = 0xFE
    0x05    1       cylindre (n° de piste)
    0x06    1       tête  (n° de face)
    0x07    1       secteur
    0x08    1       encodage  = 0x02 (densité double / MFM)
    0x09    1       taille données (haute)  = 0x01
    0x0A    1       taille données (basse)  = 0x00   -> 256
    0x0B    1       checksum du champ ID
    0x0C    1       marque d'adresse données = 0xFE
    0x0D   256      données du secteur
    0xBD    1       checksum des données

Ordre des secteurs dans le fichier : piste (majeure) -> face -> secteur.
Index linéaire :  (piste * faces + face) * secteurs/piste + secteur.

NOTE DE VALIDATION
==================
La géométrie (40/2/10/256) est celle du format standard CPC. La disposition
octet par octet de l'en-tête et des secteurs est une implémentation propre,
autocohérente (testée en aller-retour). Si une image produite n'est pas
reconnue par un émulateur précis, ajuster les constantes ``ADF_*`` ci-dessous
pour coller à la référence exacte (source libspectrum / Fuse).
"""

from __future__ import annotations

import os
import struct
from typing import Iterator, List

from cpc_dsk.core import geometry

# --- Constantes du format ADF (point unique d'ajustement) ---
ADF_SIGNATURE = b"CPC1"
ADF_VERSION = 1
ADF_HEADER_SIZE = 40

SYNC_BYTES = 4                 # préambule avant le champ ID
ADDR_MARK = 0xFE               # marque d'adresse (FM/MFM logique)
ENCODING_MFM = 0x02            # densité double

# Taille d'un secteur « encodé » dans l'image (voir docstring).
SECTOR_RECORD_SIZE = (SYNC_BYTES + 1 + 7 + 1 + geometry.SECTOR_SIZE + 1)
# = 4 + 1 + 7 + 1 + 256 + 1 = 270 octets


class ADFError(Exception):
    """Erreur de lecture / écriture du format ADF."""


def _checksum(data: bytes) -> int:
    """Checksum simple (somme mod 256) — suffisant pour l'autocohérence."""
    return sum(data) & 0xFF


class ADFDisk:
    """Modèle mémoire d'une disquette ADF (tableau de secteurs bruts)."""

    def __init__(self,
                 tracks: int = geometry.TRACKS_PER_SIDE,
                 sides: int = geometry.NUM_SIDES,
                 sectors_per_track: int = geometry.SECTORS_PER_TRACK,
                 sector_size: int = geometry.SECTOR_SIZE):
        if tracks <= 0 or sides <= 0 or sectors_per_track <= 0 or sector_size <= 0:
            raise ADFError("Géométrie invalide (toutes les valeurs doivent être > 0).")
        self.tracks = tracks
        self.sides = sides
        self.sectors_per_track = sectors_per_track
        self.sector_size = sector_size
        total = tracks * sides * sectors_per_track
        self._sectors: List[bytearray] = [bytearray(sector_size) for _ in range(total)]

    # ------------------------------------------------------------------ #
    # Fabrication
    # ------------------------------------------------------------------ #
    @classmethod
    def new_blank(cls) -> "ADFDisk":
        """Crée une disquette vierge (géométrie standard CPC)."""
        return cls()

    @classmethod
    def load(cls, path: str) -> "ADFDisk":
        """Charge une image ``.dsk`` depuis le disque."""
        with open(path, "rb") as fh:
            data = fh.read()
        return cls._from_bytes(data)

    def save(self, path: str) -> None:
        """Sauvegarde l'image ``.dsk`` sur le disque."""
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(self._to_bytes())

    # ------------------------------------------------------------------ #
    # Accès aux secteurs
    # ------------------------------------------------------------------ #
    def _flat_index(self, track: int, side: int, sector: int) -> int:
        if not geometry.is_valid_address(track, side, sector,
                                         self.tracks, self.sides,
                                         self.sectors_per_track):
            raise ADFError(
                f"Adresse secteur hors bornes: piste={track} face={side} "
                f"secteur={sector} (pistes={self.tracks}, faces={self.sides}, "
                f"secteurs/piste={self.sectors_per_track}).")
        return (track * self.sides + side) * self.sectors_per_track + sector

    def get_sector(self, track: int, side: int, sector: int) -> bytes:
        """Renvoie les ``sector_size`` octets bruts du secteur."""
        return bytes(self._sectors[self._flat_index(track, side, sector)])

    def set_sector(self, track: int, side: int, sector: int, data: bytes) -> None:
        """Écrit ``sector_size`` octets dans le secteur (taille vérifiée)."""
        if len(data) != self.sector_size:
            raise ADFError(
                f"Taille de données invalide: {len(data)} octets, "
                f"attendu {self.sector_size}.")
        idx = self._flat_index(track, side, sector)
        self._sectors[idx] = bytearray(data)

    def iter_sectors(self) -> Iterator[tuple]:
        """Itère sur tous les secteurs : ``(piste, face, secteur, données)``."""
        for track in range(self.tracks):
            for side in range(self.sides):
                for sector in range(self.sectors_per_track):
                    yield track, side, sector, self.get_sector(track, side, sector)

    # ------------------------------------------------------------------ #
    # Sérialisation
    # ------------------------------------------------------------------ #
    def _to_bytes(self) -> bytes:
        out = bytearray(self._build_header())
        for _track, _side, _sector, data in self.iter_sectors():
            # L'ordre d'itération est déjà piste->face->secteur.
            out += self._encode_sector(_track, _side, _sector, data)
        return bytes(out)

    @classmethod
    def _from_bytes(cls, data: bytes) -> "ADFDisk":
        header = data[:ADF_HEADER_SIZE]
        (sig, version, tracks, sides, sectors_per_track,
         sector_size) = cls._parse_header(header)
        if sig != ADF_SIGNATURE:
            raise ADFError(
                f"Signature ADF invalide: {sig!r} (attendu {ADF_SIGNATURE!r}). "
                "Le fichier n'est peut-être pas une image ADF CPC.")
        disk = cls(tracks=tracks, sides=sides,
                   sectors_per_track=sectors_per_track, sector_size=sector_size)

        expected = ADF_HEADER_SIZE + disk.total_sectors * SECTOR_RECORD_SIZE
        if len(data) != expected:
            raise ADFError(
                f"Taille de fichier incohérente: {len(data)} octets, "
                f"attendu {expected} pour cette géométrie.")

        offset = ADF_HEADER_SIZE
        for track in range(tracks):
            for side in range(sides):
                for sector in range(sectors_per_track):
                    record = data[offset:offset + SECTOR_RECORD_SIZE]
                    offset += SECTOR_RECORD_SIZE
                    payload = cls._decode_sector(record, track, side, sector,
                                                 sector_size)
                    idx = (track * sides + side) * sectors_per_track + sector
                    disk._sectors[idx] = bytearray(payload)
        return disk

    # --- En-tête ---
    def _build_header(self) -> bytes:
        reserved = bytes(ADF_HEADER_SIZE - 10)
        return (ADF_SIGNATURE
                + bytes([ADF_VERSION, self.tracks, self.sides,
                         self.sectors_per_track])
                + struct.pack("<H", self.sector_size)
                + reserved)

    @staticmethod
    def _parse_header(header: bytes):
        if len(header) < ADF_HEADER_SIZE:
            raise ADFError("En-tête ADF tronqué.")
        sig = header[0:4]
        version = header[4]
        tracks = header[5]
        sides = header[6]
        sectors_per_track = header[7]
        sector_size = struct.unpack("<H", header[8:10])[0]
        return sig, version, tracks, sides, sectors_per_track, sector_size

    # --- Secteur ---
    @classmethod
    def _encode_sector(cls, track: int, side: int, sector: int, data: bytes) -> bytes:
        if len(data) != geometry.SECTOR_SIZE and len(data) != cls.sector_size:
            pass  # la taille exacte est imposée par set_sector / load
        id_field = bytes([track, side, sector,
                          ENCODING_MFM,
                          (len(data) >> 8) & 0xFF, len(data) & 0xFF])
        id_checksum = _checksum(id_field)
        id_block = bytes([ADDR_MARK]) + id_field + bytes([id_checksum])
        data_block = bytes([ADDR_MARK]) + bytes(data) + bytes([_checksum(data)])
        return bytes(SYNC_BYTES) + id_block + data_block

    @classmethod
    def _decode_sector(cls, record: bytes, track: int, side: int,
                       sector: int, sector_size: int) -> bytes:
        if len(record) != SECTOR_RECORD_SIZE:
            raise ADFError("Secteur ADF tronqué.")
        # Vérifie la cohérence du champ ID (piste/face/secteur).
        id_track = record[SYNC_BYTES + 1]
        id_side = record[SYNC_BYTES + 2]
        id_sector = record[SYNC_BYTES + 3]
        if (id_track, id_side, id_sector) != (track, side, sector):
            raise ADFError(
                f"Champ ID incohérent: (piste,face,secteur)=({id_track},"
                f"{id_side},{id_sector}) attendu ({track},{side},{sector}).")
        size_hi = record[SYNC_BYTES + 5]
        size_lo = record[SYNC_BYTES + 6]
        declared_size = (size_hi << 8) | size_lo
        if declared_size != sector_size:
            raise ADFError(
                f"Taille secteur déclarée incohérente: {declared_size} "
                f"attendu {sector_size}.")
        # Les données débutent juste après le champ ID (8 octets) + AM (1 octet).
        data_start = SYNC_BYTES + 1 + 7 + 1
        data = record[data_start:data_start + sector_size]
        return bytes(data)

    # ------------------------------------------------------------------ #
    # Informations
    # ------------------------------------------------------------------ #
    @property
    def total_sectors(self) -> int:
        """Nombre total de secteurs de la disquette."""
        return self.tracks * self.sides * self.sectors_per_track

    @property
    def data_capacity(self) -> int:
        """Capacité de données utilisateur en octets."""
        return self.total_sectors * self.sector_size

    def expected_file_size(self) -> int:
        """Taille attendue du fichier ``.dsk`` sur disque."""
        return ADF_HEADER_SIZE + self.total_sectors * SECTOR_RECORD_SIZE

    def __repr__(self) -> str:  # pragma: no cover - affichage
        return (f"ADFDisk(pistes={self.tracks}, faces={self.sides}, "
                f"secteurs/piste={self.sectors_per_track}, "
                f"taille_secteur={self.sector_size})")
