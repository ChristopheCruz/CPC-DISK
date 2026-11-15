"""Conteneur d'image de disque CPC : format « EXTENDED CPC DSK » / ADF.

Ce module implémente le **conteneur** des images ``.dsk`` du CPC, tel que
produit par WinAPE / SAMdisk et lu par les émulateurs (Fuse, CPCJS, CERMU).
Le système de fichiers (fichiers AMSDOS) est dans :mod:`cpc_dsk.core.cpcfs`.

Structure du fichier
====================
::

    +-----------------------------+
    | Disk-Info (256 octets)      |  magic + géométrie + tailles des pistes
    +-----------------------------+
    | Piste 0 : Track-Info (256 o)|
    |           + données secteurs|
    | Piste 1 : Track-Info (256 o)|
    |           + données secteurs|
    |    ...                      |
    +-----------------------------+

Disk-Info (256 octets)
----------------------
::

    Offset  Taille  Champ
    0x00    34      magic
                        Extended : "EXTENDED CPC DSK File\r\nDisk-Info\r\n"
                        Standard : "MV - CPCEMU Disk-File\r\nDisk-Info\r\n"
    0x22    14      chaîne « créateur » (outil qui a produit l'image)
    0x30    1       nb de pistes
    0x31    1       nb de faces
    0x32    2       taille uniforme des pistes (LE16) — format Standard
    0x34    N       taille de chaque piste (1 o, ×256 = octets) — format Extended
    0xFF ...        réserve (0)

Bloc piste
----------
::

    Offset        Taille  Champ
    0x00          12      "Track-Info\r\n"
    0x14          1       code taille secteur (128<<n : 0=128, 1=256, 2=512 o)
    0x15          1       nb de secteurs de la piste
    0x16          1       gap3
    0x17          1       octet de remplissage (0xE5 après formatage)
    0x18 + i×8    8       enregistrement secteur i : cylindre, face, ID,
                          code taille, st1, st2, longueur LE16
    0x100         ...     données des secteurs (contiguës, taille = taille_piste-256)

WinAPE valide ces enregistrements à l'ouverture (avec la table des pistes
@0x34 : pistes×faces entrées, valeur × 256 = taille de bloc, 0 = non
formatée) ; une image sans enregistrements de secteurs est refusée (« invalid
track sizes »). Les disques générés par cet outil reproduisent la structure
des disques réels (IDs de secteurs C1 C6 C2 C7 C3 C8 C4 C9 C5, secteurs
vierges remplis à 0xE5).

La taille d'un bloc piste (donnée dans le tableau des pistes) est un multiple
de 256 ; les données de secteurs occupent ``taille_piste - 256`` octets, soit
``nb_secteurs`` secteurs de ``(taille_piste-256)/nb_secteurs`` octets chacun
(par ex. 9 secteurs × 512 o = 4608 o, bloc de 4864 o).

Variantes SAM / WinAPE (tolérées)
---------------------------------

- le tableau des pistes peut être **complété à zéro** au-delà du nombre de
  pistes réelles (le champ 0x30 peut les compter) ; le premier zéro marque la
  fin des pistes ;
- une **traînée** (section ``Offset-Info``) peut suivre la dernière piste ;
  elle est conservée en l'état à l'enregistrement ;
- la taille des secteurs varie par piste (ex. piste 0 = 9 × 512 o, les autres
  = 15 × 256 o).
"""

from __future__ import annotations

import os
from typing import Iterator, List, Tuple

# --- Constantes du format (point unique d'ajustement) ---
MAGIC_EXTENDED = b"EXTENDED CPC DSK File\r\nDisk-Info\r\n"
MAGIC_STANDARD = b"MV - CPCEMU Disk-File\r\nDisk-Info\r\n"
CREATOR_OFFSET = 0x22
CREATOR_SIZE = 14
NUM_TRACKS_OFFSET = 0x30
NUM_SIDES_OFFSET = 0x31
STD_TRACK_SIZE_OFFSET = 0x32
EXT_TRACK_SIZE_TABLE_OFFSET = 0x34

DISK_INFO_SIZE = 256
TRACK_INFO_SIZE = 256
TRACK_INFO_MAGIC = b"Track-Info\r\n"
TRACK_INFO_NUM_SECTORS_OFFSET = 0x15


class ADFError(Exception):
    """Erreur de lecture / écriture du conteneur .dsk."""


class ADFDisk:
    """Modèle d'une image de disquette CPC (conteneur EXTENDED/Standard DSK).

    L'image est conservée en mémoire comme tableau d'octets brut ; les méthodes
    de navigation (pistes, secteurs) opèrent directement dessus.
    """

    def __init__(self, raw: bytes, creator: str = "cpc-dsk v0.1"):
        self._raw = bytearray(raw)
        self._creator = creator
        self.extended = True
        self.num_tracks = 0
        self.num_sides = 1
        self.track_sizes: List[int] = []
        self.track_offsets: List[int] = []
        self._parse_header()

    # ------------------------------------------------------------------ #
    # Analyse de l'en-tête
    # ------------------------------------------------------------------ #
    def _parse_header(self) -> None:
        raw = self._raw
        if len(raw) < DISK_INFO_SIZE:
            raise ADFError(
                f"Fichier trop court ({len(raw)} o) pour un en-tête "
                f"Disk-Info de {DISK_INFO_SIZE} o.")
        if raw[:len(MAGIC_EXTENDED)] == MAGIC_EXTENDED:
            self.extended = True
        elif raw[:len(MAGIC_STANDARD)] == MAGIC_STANDARD:
            self.extended = False
        elif raw[0:8] == b"EXTENDED" or raw[0:8] == b"MV - CPC":
            # Variante écourtée du magic : on tolère si le préfixe colle.
            self.extended = raw[0] == ord("E")
        else:
            raise ADFError(
                f"Magic inconnu: {raw[:16]!r}. Ce fichier n'est pas une image "
                ".dsk CPC (attendu 'EXTENDED CPC DSK File' ou 'MV - CPCEMU "
                "Disk-File').")

        self.num_tracks = raw[NUM_TRACKS_OFFSET]
        self.num_sides = raw[NUM_SIDES_OFFSET]
        if self.num_tracks == 0:
            raise ADFError("Nombre de pistes nul dans le Disk-Info.")

        if self.extended:
            table = [
                raw[EXT_TRACK_SIZE_TABLE_OFFSET + t]
                for t in range(self.num_tracks)
            ]
            # Certains outils (SAM / WinAPE) déclarent plus de pistes que le
            # fichier n'en contient : le tableau est complété à zéro (ex. 42
            # pistes déclarées pour 39 pistes réelles). Le premier zéro marque
            # la fin des pistes réelles (une piste de 0 o est invalide).
            n = len(table)
            for i, b in enumerate(table):
                if b == 0:
                    n = i
                    break
            self.num_tracks = n
            self.track_sizes = [b * 256 for b in table[:n]]
        else:
            ts = raw[STD_TRACK_SIZE_OFFSET] | (raw[STD_TRACK_SIZE_OFFSET + 1] << 8)
            self.track_sizes = [ts] * self.num_tracks

        # Offsets cumulés des blocs piste.
        self.track_offsets = []
        off = DISK_INFO_SIZE
        for sz in self.track_sizes:
            if sz <= TRACK_INFO_SIZE:
                raise ADFError("Taille de piste invalide (<= 256 o).")
            self.track_offsets.append(off)
            off += sz
        if off > len(raw):
            raise ADFError(
                f"Fichier tronqué: {len(raw)} o, au moins {off} o attendus "
                f"selon le Disk-Info.")
        # Des octets après la dernière piste = traînée de fin de fichier
        # (section « Offset-Info » produite par SAM / WinAPE) ; elle est
        # conservée à l'enregistrement.

    # ------------------------------------------------------------------ #
    # Persistance
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: str) -> "ADFDisk":
        with open(path, "rb") as fh:
            return cls(fh.read())

    def save(self, path: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(bytes(self._raw))

    # ------------------------------------------------------------------ #
    # Fabrication d'une disquette vierge
    # ------------------------------------------------------------------ #
    @classmethod
    def new_blank(cls,
                  tracks: int = 40,
                  sides: int = 1,
                  sectors: int = 9,
                  sector_size: int = 512,
                  creator: str = "cpc-dsk v0.1") -> "ADFDisk":
        """Crée une disquette vierge au format Extended.

        Par défaut, géométrie identique à une disquette CPC réelle (40 pistes,
        1 face, 9 secteurs × 512 o). La taille de bloc doit être un multiple de
        256 (256 + secteurs×taille_secteur).
        """
        if tracks <= 0 or sides <= 0 or sectors <= 0 or sector_size <= 0:
            raise ADFError("Géométrie invalide.")
        track_data_size = sectors * sector_size
        if track_data_size % 256 != 0:
            raise ADFError(
                f"secteurs×taille_secteur ({track_data_size}) doit être un "
                f"multiple de 256 pour ce format.")
        track_block = TRACK_INFO_SIZE + track_data_size  # multiple de 256
        track_byte = track_block // 256

        # Disk-Info (256 o)
        header = bytearray(DISK_INFO_SIZE)
        magic = MAGIC_EXTENDED
        header[0:len(magic)] = magic
        creator_bytes = creator.encode("latin1")[:CREATOR_SIZE]
        header[CREATOR_OFFSET:CREATOR_OFFSET + len(creator_bytes)] = creator_bytes
        header[NUM_TRACKS_OFFSET] = tracks
        header[NUM_SIDES_OFFSET] = sides
        for t in range(tracks):
            header[EXT_TRACK_SIZE_TABLE_OFFSET + t] = track_byte

        # Blocs piste — chaque en-tête Track-Info reproduit la structure des
        # disquettes réelles (vérifiée sur greed.dsk/robot.dsk) :
        #   0x14 = taille secteur (128<<n), 0x15 = nb de secteurs,
        #   0x16 = gap3, 0x17 = octet de remplissage,
        #   0x18 + i×8 = enregistrement secteur (c, h, r, n, st1, st2, len LE16).
        # Sans ces enregistrements, WinAPE rejette l'image (« invalid track
        # sizes »). Les secteurs vierges sont remplis à 0xE5, comme après
        # formatage réel (le répertoire Filer vide est aussi 0xE5).
        # Code de taille : 128<<n (128/256/512 -> 0/1/2).
        size_shift = (sector_size // 128).bit_length() - 1
        sec_ids_9 = (0xC1, 0xC6, 0xC2, 0xC7, 0xC3, 0xC8, 0xC4, 0xC9, 0xC5)
        blocks = bytearray()
        for t in range(tracks):
            ti = bytearray(TRACK_INFO_SIZE)
            ti[0:len(TRACK_INFO_MAGIC)] = TRACK_INFO_MAGIC
            ti[0x14] = size_shift
            ti[TRACK_INFO_NUM_SECTORS_OFFSET] = sectors
            ti[0x16] = 0x52  # gap3 (valeur observée sur greed.dsk)
            ti[0x17] = 0xE5  # octet de remplissage
            for i in range(sectors):
                rec = bytearray(8)
                rec[0] = t
                rec[2] = (sec_ids_9[i] if i < len(sec_ids_9) else 0xC0 + i + 1)
                rec[3] = size_shift
                rec[6] = sector_size & 0xFF
                rec[7] = (sector_size >> 8) & 0xFF
                ti[0x18 + i * 8: 0x18 + i * 8 + 8] = rec
            blocks += ti
            blocks += b"\xE5" * track_data_size  # secteurs formatés (remplis)

        return cls(bytes(header) + bytes(blocks), creator=creator)

    # ------------------------------------------------------------------ #
    # Accès pistes / secteurs
    # ------------------------------------------------------------------ #
    def _check_track(self, track: int) -> None:
        if not (0 <= track < self.num_tracks):
            raise ADFError(
                f"Piste hors bornes: {track} (0..{self.num_tracks - 1}).")

    def num_sectors(self, track: int) -> int:
        """Nombre de secteurs de la piste (champ Track-Info[0x15])."""
        self._check_track(track)
        return self._raw[self.track_offsets[track] + TRACK_INFO_NUM_SECTORS_OFFSET]

    def get_track_data(self, track: int) -> bytes:
        """Données brutes des secteurs de la piste (après l'en-tête Track-Info)."""
        self._check_track(track)
        off = self.track_offsets[track] + TRACK_INFO_SIZE
        return bytes(self._raw[off:off + self.track_sizes[track] - TRACK_INFO_SIZE])

    def set_track_data(self, track: int, data: bytes) -> None:
        self._check_track(track)
        expected = self.track_sizes[track] - TRACK_INFO_SIZE
        if len(data) != expected:
            raise ADFError(
                f"Taille de données piste invalide: {len(data)} o, attendu "
                f"{expected} o.")
        off = self.track_offsets[track] + TRACK_INFO_SIZE
        self._raw[off:off + expected] = data

    def get_sector(self, track: int, sector: int) -> bytes:
        """Un secteur de la piste (taille = (taille_piste-256)/nb_secteurs)."""
        ns = self.num_sectors(track)
        if ns == 0:
            raise ADFError("Piste sans secteur.")
        if not (0 <= sector < ns):
            raise ADFError(
                f"Secteur hors bornes: {sector} (0..{ns - 1}) sur la piste {track}.")
        td = self.get_track_data(track)
        ss = len(td) // ns
        return td[sector * ss:(sector + 1) * ss]

    def set_sector(self, track: int, sector: int, data: bytes) -> None:
        ns = self.num_sectors(track)
        if ns == 0:
            raise ADFError("Piste sans secteur.")
        if not (0 <= sector < ns):
            raise ADFError(
                f"Secteur hors bornes: {sector} (0..{ns - 1}) sur la piste {track}.")
        td = bytearray(self.get_track_data(track))
        ss = len(td) // ns
        if len(data) != ss:
            raise ADFError(
                f"Taille de secteur invalide: {len(data)} o, attendu {ss} o.")
        td[sector * ss:(sector + 1) * ss] = data
        self.set_track_data(track, bytes(td))

    def iter_data(self) -> Iterator[Tuple[int, bytes]]:
        """Itère sur les données de toutes les pistes: ``(piste, données)``."""
        for track in range(self.num_tracks):
            yield track, self.get_track_data(track)

    # ------------------------------------------------------------------ #
    # Informations
    # ------------------------------------------------------------------ #
    @property
    def file_size(self) -> int:
        return len(self._raw)

    def summary(self) -> str:
        fmt = "Extended" if self.extended else "Standard"
        return (f"format={fmt} pistes={self.num_tracks} faces={self.num_sides} "
                f"taille_fichier={self.file_size} o "
                f"tailles_pistes={sorted(set(self.track_sizes))}")

    def __repr__(self) -> str:  # pragma: no cover
        return f"ADFDisk({self.summary()})"
