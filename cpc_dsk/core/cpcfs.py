"""Système de fichiers CPC : répertoire Filer + fichiers AMSDOS.

Au-dessus du conteneur :mod:`cpc_dsk.core.adf`, ce module manipule les
**fichiers** d'une disquette. Deux couches coexistent (vérifié sur des
disquettes réelles) :

1. **Le répertoire Filer** (DOS CPC d'origine) — piste 0, secteur 0.
   C'est lui que lit le vrai DOS du CPC (et donc le Gotek sur matériel
   réel).
2. **Les en-têtes AMSDOS** — ajoutés par Amsdos (DOS tiers). Chaque fichier
   est préfixé d'un en-tête de 128 o, localisé par balayage (méthode utilisée
   par l'émulateur CERMU). Les lecteurs qui ne savent pas lire le répertoire
   Filer (beaucoup d'émulateurs) trouvent les fichiers par ce canal.

Répertoire Filer (piste 0, secteur 0) — vérifié sur images réelles
===================================================================
16 entrées de 32 octets. Entrée occupée ::

    Offset  Taille  Champ
    0x00    1       0x00
    0x01    11      nom 8.3 (8 + 3), ``'.'`` codé 0xC9, latin1
    0x0C    1       index du chunk dans le fichier (0, 1, 2, …)
    0x0D    2       0x00 0x00
    0x0F    1       taille du chunk en unités de 128 o (max 0x80 = 16 Ko)
    0x10    16      k octets de compteur d'allocation (k = ceil(chunk/1024)),
                    valeurs consécutives issues d'un compteur global
                    (démarre à 0x02), puis zéros

Entrée vide : 32 octets 0xE5 (ou 0x00 sur disquette vierge).

Un fichier peut occuper plusieurs entrées consécutives (chunks de 16 Ko max).
Les données des fichiers sont empilées **séquentiellement dans l'ordre du
répertoire**, à partir du secteur 1 de la piste 0 (juste après le secteur
répertoire). Le Filer recolle le paquet à l'insertion/suppression d'un
fichier (le compteur global conservé dans les octets de queue reflète
l'ordre d'écriture, pas l'ordre physique).

Fichier Filer = données brutes (pas d'en-tête), taille réelle arrondie au
multiple de 128 o. La longueur exacte n'est pas stockée dans le répertoire ;
pour un fichier BASIC, le premier octet des données porte la longueur
interne.

En-tête AMSDOS (128 octets) — vérifié sur images réelles
========================================================
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
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

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

# Types de fichier (AMSDOS)
FT_BASIC = 0
FT_PROTECTED = 1
FT_BINARY = 2
FT_UNKNOWN = 3  # fichier Filer : le type n'est pas stocké

# --- Constantes du répertoire Filer ---
DIR_TRACK = 0
DIR_SECTOR = 0
DIR_SECTOR_SIZE = 512
DIR_ENTRY_SIZE = 32
DIR_MAX_ENTRIES = 16
DIR_NAME_OFFSET = 1
DIR_NAME_SIZE = 11
DIR_CHUNK_INDEX_OFFSET = 0x0C
DIR_SIZE_UNITS_OFFSET = 0x0F
DIR_TAIL_OFFSET = 0x10
DIR_UNIT_SIZE = 128           # unité de taille ([15])
DIR_MAX_CHUNK_BYTES = 16384   # 0x80 unités par chunk
DIR_EMPTY_ENTRY = b"\xE5" * DIR_ENTRY_SIZE
DIR_DOT_BYTE = 0xC9           # encodage de '.' dans le nom 8.3


class CpcError(Exception):
    """Erreur du système de fichiers CPC."""


def _clean_name(raw: bytes) -> str:
    """Nettoie un nom (supprime NUL et espaces de fin)."""
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
    espaces de remplissage et un NUL final). Tout autre octet (symbole,
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


def _valid_dir_name(raw: bytes) -> bool:
    """Valide un nom de champ de répertoire Filer (autorise 0xC9 = '.')."""
    return _valid_name(bytes(b if b != DIR_DOT_BYTE else 46 for b in raw))


def _dir_name_to_text(raw: bytes) -> str:
    """Nom de champ de répertoire (0xC9 = '.') vers texte lisible."""
    txt = raw.decode("latin1").replace(chr(DIR_DOT_BYTE), ".")
    return txt.rstrip()


def _normalize_83(name: str) -> str:
    """Normalise un nom en champ 8.3 de 11 caractères (base 8 + ext 3).

    Un nom de 11 caractères est un champ déjà formé (découpage canonique
    [8][3], la base pouvant contenir un point). Sinon: accepté les
    notations ``BASE.EXT`` (point) ou ``BASE    EXT`` (espace), sinon
    découpage [8][3] direct.
    """
    name = name.strip().upper()
    if not name:
        raise CpcError("Nom de fichier vide.")
    if len(name) == 11:
        base, ext = name[:8], name[8:11]
    elif " " in name:
        base, _, ext = name.rpartition(" ")
    elif "." in name:
        base, _, ext = name.partition(".")
    else:
        base, ext = name[:8], name[8:11]
    base = base[:8]
    ext = ext[:3]
    for ch in base + ext:
        if ch == " ":
            continue
        if not (ch.isalnum() or ch in "._-"):
            raise CpcError(f"Caractère interdit dans le nom: {ch!r}")
    if not base.strip() and not ext.strip():
        raise CpcError("Nom de fichier vide.")
    return base.ljust(8) + ext.ljust(3)


def _first_free_run(free: List[int], n: int) -> Optional[int]:
    """Plus petit slot ``s`` tel que ``s..s+n-1`` sont tous libres."""
    free_set = set(free)
    for s in sorted(free_set):
        if s + n <= DIR_MAX_ENTRIES and all(x in free_set for x in range(s, s + n)):
            return s
    return None


def _entry_live(entry: bytes) -> bool:
    """Vraie si l'entrée 32 o représente un fichier (ni vide, ni supprimée)."""
    if len(entry) != DIR_ENTRY_SIZE or entry == DIR_EMPTY_ENTRY:
        return False
    return _valid_dir_name(entry[DIR_NAME_OFFSET:DIR_NAME_OFFSET + DIR_NAME_SIZE])


@dataclass
class CpcFile:
    """Un fichier localisé sur la disquette (Filer ou AMSDOS)."""
    name: str
    offset: int          # position dans l'image (début données Filer / en-tête AMSDOS)
    file_type: int       # FT_BASIC / FT_PROTECTED / FT_BINARY / FT_UNKNOWN
    load_addr: int
    exec_addr: int
    length: int
    source: str = "AMSDOS"  # "FILER" | "AMSDOS" | "FILER+AMSDOS"

    @property
    def type_name(self) -> str:
        return {FT_BASIC: "BASIC", FT_PROTECTED: "PROT",
                FT_BINARY: "BIN", FT_UNKNOWN: "DATA"}.get(
            self.file_type, f"TYPE{self.file_type}")


@dataclass
class CpcDirEntry:
    """Une entrée du répertoire Filer (un chunk de fichier)."""
    slot: int
    name: str
    chunk_index: int
    size_units: int
    tail_max: int

    @property
    def size_bytes(self) -> int:
        return self.size_units * DIR_UNIT_SIZE


class CpcFilesystem:
    """Système de fichiers d'une image .dsk (répertoire Filer + AMSDOS)."""

    def __init__(self, disk: ADFDisk):
        self.disk = disk

    # ------------------------------------------------------------------ #
    # Espace de données linéaire (toutes pistes, sans en-têtes Track-Info)
    # ------------------------------------------------------------------ #
    def _track_data_size(self, track: int) -> int:
        return self.disk.track_sizes[track] - TRACK_INFO_SIZE

    def _capacity(self) -> int:
        """Taille totale de l'espace de données linéaire (toutes pistes)."""
        return sum(self._track_data_size(t)
                   for t in range(self.disk.num_tracks))

    def _linear_to_image(self, lin: int) -> int:
        """Position linéaire (données) -> offset dans l'image brute."""
        cum = 0
        for track in range(self.disk.num_tracks):
            tsize = self._track_data_size(track)
            if lin < cum + tsize:
                return self.disk.track_offsets[track] + TRACK_INFO_SIZE + (lin - cum)
            cum += tsize
        raise CpcError("Capacité disque dépassée.")

    def _image_to_linear(self, img: int) -> int:
        """Offset dans l'image brute -> position linéaire (données)."""
        cum = 0
        for track in range(self.disk.num_tracks):
            base = self.disk.track_offsets[track] + TRACK_INFO_SIZE
            tsize = self._track_data_size(track)
            if base <= img < base + tsize:
                return cum + (img - base)
            cum += tsize
        raise CpcError("Position hors des données de secteurs.")

    def _read_linear(self, lin: int, size: int) -> bytes:
        """Lit ``size`` octets de l'espace de données linéaire (peut traverser
        les limites de piste)."""
        buf = bytearray()
        rem = size
        pos = lin
        for track in range(self.disk.num_tracks):
            if rem <= 0:
                break
            tsize = self._track_data_size(track)
            if pos >= tsize:
                # Piste entièrement avant la position cible : on la saute en
                # décrémentant (un simple pos = 0 reposerait au début de la
                # piste suivante et écraserait / lirait la mauvaise région).
                pos -= tsize
                continue
            base = self.disk.track_offsets[track] + TRACK_INFO_SIZE
            take = min(rem, tsize - pos)
            buf += self.disk._raw[base + pos:base + pos + take]
            rem -= take
            pos = 0  # la suite continue au début de la piste suivante
        if rem > 0:
            raise CpcError("Capacité disque dépassée.")
        return bytes(buf)

    def _write_linear(self, lin: int, data: bytes) -> None:
        """Écrit ``data`` dans l'espace de données linéaire (peut traverser
        les limites de piste)."""
        raw = self.disk._raw
        written = 0
        pos = lin
        for track in range(self.disk.num_tracks):
            if written >= len(data):
                break
            tsize = self._track_data_size(track)
            if pos >= tsize:
                pos -= tsize
                continue
            base = self.disk.track_offsets[track] + TRACK_INFO_SIZE
            take = min(len(data) - written, tsize - pos)
            raw[base + pos:base + pos + take] = data[written:written + take]
            written += take
            pos = 0
        if written < len(data):
            raise CpcError("Capacité disque dépassée.")

    # ------------------------------------------------------------------ #
    # Répertoire Filer — lecture
    # ------------------------------------------------------------------ #
    def _dir_sector(self) -> bytes:
        try:
            sec = self.disk.get_sector(DIR_TRACK, DIR_SECTOR)
        except ADFError as exc:
            raise CpcError("Disque sans secteur de répertoire (piste 0, secteur 0).") from exc
        if len(sec) != DIR_SECTOR_SIZE:
            raise CpcError(
                f"Secteur de répertoire de taille inattendue ({len(sec)} o, "
                f"{DIR_SECTOR_SIZE} requis).")
        return sec

    def read_directory(self) -> List[CpcDirEntry]:
        """Lit les entrées Filer occupées (une par chunk, ordre des slots)."""
        sec = self._dir_sector()
        entries: List[CpcDirEntry] = []
        for slot in range(DIR_MAX_ENTRIES):
            e = sec[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE]
            if not _entry_live(e):
                continue
            entries.append(CpcDirEntry(
                slot=slot,
                name=_dir_name_to_text(
                    e[DIR_NAME_OFFSET:DIR_NAME_OFFSET + DIR_NAME_SIZE]),
                chunk_index=e[DIR_CHUNK_INDEX_OFFSET],
                size_units=e[DIR_SIZE_UNITS_OFFSET],
                tail_max=max(e[DIR_TAIL_OFFSET:DIR_TAIL_OFFSET + 16]),
            ))
        return entries

    def _pack_bounds(self) -> Tuple[int, int]:
        """Bornes (linéaires) du paquet de données Filer : juste après le
        secteur répertoire, dans l'ordre des entrées du répertoire."""
        sec = self._dir_sector()
        pack_start = len(sec)
        pack_end = pack_start
        for entry in self.read_directory():
            pack_end += entry.size_bytes
        return pack_start, pack_end

    def list_directory_files(self) -> List[CpcFile]:
        """Regroupe les entrées du répertoire par fichier (ordre du répertoire)."""
        entries = self.read_directory()
        pack, _ = self._pack_bounds()
        files: List[CpcFile] = []
        cur_name: Optional[str] = None
        for en in entries:
            if en.name != cur_name:
                cur_name = en.name
                files.append(CpcFile(
                    name=en.name,
                    offset=self._linear_to_image(pack),
                    file_type=FT_UNKNOWN,
                    load_addr=0,
                    exec_addr=0,
                    length=0,
                    source="FILER",
                ))
            files[-1].length += en.size_bytes
            pack += en.size_bytes
        return files

    def read_directory_names(self) -> List[str]:
        """Noms des fichiers du répertoire Filer (un par fichier)."""
        return [f.name for f in self.list_directory_files()]

    # ------------------------------------------------------------------ #
    # AMSDOS — balayage des en-têtes
    # ------------------------------------------------------------------ #
    def _scan_amsdos(self) -> List[CpcFile]:
        """Retourne les fichiers AMSDOS valides (méthode de balayage CERMU).

        Le balayage porte sur le **flux physique** (données de secteurs
        concaténées, sans en-têtes Track-Info) — c'est ce flux que voit un
        lecteur AMSDOS. Un fichier traverse les pistes ; les en-têtes de
        blocs sont de la métadonnée du conteneur. ``CpcFile.offset`` reste
        un offset d'image (pour affichage / hex).
        """
        stream = self._read_linear(0, self._capacity())
        files: List[CpcFile] = []
        for pos in range(0, len(stream) - (CHECKSUM_OFFSET + 2)):
            name_raw = stream[NAME_OFFSET + pos:NAME_OFFSET + pos + NAME_SIZE]
            if not _valid_name(name_raw):
                continue
            s = sum(stream[pos:pos + CHECKSUM_COVERED]) & 0xFFFF
            stored = (stream[pos + CHECKSUM_OFFSET]
                      | (stream[pos + CHECKSUM_OFFSET + 1] << 8))
            if s != stored:
                continue
            ftype = stream[pos + TYPE_OFFSET] | (stream[pos + TYPE_OFFSET + 1] << 8)
            load = stream[pos + LOAD_OFFSET] | (stream[pos + LOAD_OFFSET + 1] << 8)
            execa = stream[pos + EXEC_OFFSET] | (stream[pos + EXEC_OFFSET + 1] << 8)
            full = (stream[pos + LEN24_OFFSET]
                    | (stream[pos + LEN24_OFFSET + 1] << 8)
                    | (stream[pos + LEN24_OFFSET + 2] << 16))
            files.append(CpcFile(
                name=_clean_name(name_raw),
                offset=self._linear_to_image(pos),
                file_type=ftype,
                load_addr=load,
                exec_addr=execa,
                length=full,
                source="AMSDOS",
            ))
        return files

    # ------------------------------------------------------------------ #
    # API publique : liste / recherche / lecture
    # ------------------------------------------------------------------ #
    def list_files(self, source: Optional[str] = None) -> List[CpcFile]:
        """Liste les fichiers.

        ``source``: ``"filer"`` (répertoire seulement), ``"amsdos"``
        (balayage d'en-têtes seulement) ou ``None`` pour les deux (fichiers
        Filer d'abord, dans l'ordre du répertoire).
        """
        if source is not None:
            source = source.lower()
        if source == "filer":
            return self.list_directory_files()
        if source == "amsdos":
            return self._scan_amsdos()
        return self.list_directory_files() + self._scan_amsdos()

    def find(self, name: str, source: Optional[str] = None) -> Optional[CpcFile]:
        """Retrouve un fichier par nom 8.3.

        Sans ``source``: privilégie la version AMSDOS (métadonnées complètes
        : longueur exacte, adresses), puis le répertoire Filer.
        """
        target = _normalize_83(name)
        if source is not None:
            source = source.lower()

        if source in (None, "amsdos"):
            for f in self._scan_amsdos():
                if _normalize_83(f.name) == target:
                    return f

        if source in (None, "filer"):
            # Le champ 8.3 brut du répertoire est la source de vérité: le nom
            # affiché (rstrippé) peut avoir perdu la frontière base/ext.
            files = self.list_directory_files()
            sec = self._dir_sector()
            fidx = 0
            prev_field: Optional[str] = None
            for slot in range(DIR_MAX_ENTRIES):
                e = bytes(sec[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE])
                if not _entry_live(e):
                    continue
                raw_field = bytes(
                    e[DIR_NAME_OFFSET:DIR_NAME_OFFSET + DIR_NAME_SIZE]
                ).decode("latin1").replace(chr(DIR_DOT_BYTE), ".")
                if raw_field != prev_field:
                    prev_field = raw_field
                    if fidx >= len(files):
                        break
                    f = files[fidx]
                    fidx += 1
                    if raw_field == target:
                        return f
        return None

    def read_file(self, name: str, source: Optional[str] = None) -> bytes:
        """Lit les données d'un fichier.

        Version Filer : la région allouée complète (arrondie au multiple de
        128 o, comme la charge réelle du Filer). Version AMSDOS : les données
        exactes (après l'en-tête de 128 o).
        """
        f = self.find(name, source)
        if f is None:
            raise CpcError(f"Fichier introuvable: {name!r}")
        # Flux physique : le fichier peut traverser plusieurs pistes.
        lin = self._image_to_linear(f.offset)
        if f.source == "FILER":
            return self._read_linear(lin, f.length)
        return self._read_linear(lin + AMSDOS_HEADER_SIZE, f.length)

    # ------------------------------------------------------------------ #
    # Frontières d'allocation
    # ------------------------------------------------------------------ #
    def _amsdos_end_frontier(self) -> int:
        """Linéaire de fin de la pile d'objets AMSDOS (croissance descendante
        depuis la fin de l'espace de données).

        Le paquet Filer croît vers l'avant depuis le secteur répertoire
        (contrainte du format) ; les objets AMSDOS écrits par cet outil sont
        empilés vers l'arrière depuis la fin du disque. Les deux ne
        s'entrecroisent que quand le disque est plein.
        """
        capacity = self._capacity()
        pack_end = self._pack_bounds()[1]
        frontier = capacity
        for a in self._scan_amsdos():
            start = self._image_to_linear(a.offset)
            if start >= pack_end and start < frontier:
                frontier = start
        return frontier

    def _linear_region_free(self, lin: int, size: int) -> bool:
        """Vrai si la région linéaire [lin, lin+size) est vierge (0 ou 0xE5).

        En coordonnées linéaires (pas image) : la région peut traverser des
        pistes, et les en-têtes Track-Info (non nuls) ne comptent pas.
        """
        return all(b in (0, 0xE5) for b in self._read_linear(lin, size))

    def _assert_amsdos_outside_pack(self) -> None:
        """Refuse de réorganiser le paquet Filer si des objets AMSDOS s'y
        trouvent (disque ambigü — les données seraient écrasées)."""
        pack_start, pack_end = self._pack_bounds()
        for a in self._scan_amsdos():
            start = self._image_to_linear(a.offset)
            if pack_start <= start < pack_end:
                raise CpcError(
                    "Objet AMSDOS détecté dans le paquet Filer: disque ambigü, "
                    "écriture/suppression Filer refusée (utilisez --fs amsdos "
                    "pour ajouter des fichiers AMSDOS).")

    # ------------------------------------------------------------------ #
    # Répertoire Filer — écriture (paquet + réorganisation)
    # ------------------------------------------------------------------ #
    def _repack_filer(self,
                      insert: Optional[Tuple[bytes, List[int], int, bytes]] = None,
                      old_sec: Optional[bytes] = None) -> None:
        """Réécrit le paquet Filer : données des fichiers vivants, contiguës
        et ordonnées par slot.

        ``insert`` = ``(champ 11 o, [unités par chunk], slot, données
        remplies)`` : fichier à insérer (ses chunks occupent slot..slot+n-1,
        compteur d'allocation continué après le maximum existant).
        ``old_sec`` : secteur répertoire décrivant la disposition **précédente**
        des données (indispensable après une suppression : les données des
        fichiers suivants sont encore à leur ancienne place, trou compris).
        """
        sec = self._dir_sector()
        if old_sec is None:
            old_sec = sec

        # Positions anciennes (le layout de old_sec, fichiers supprimés
        # compris — leur taille compte dans le décalage des suivants).
        old_pos: dict = {}
        pack = len(old_sec)
        for slot in range(DIR_MAX_ENTRIES):
            e = bytes(old_sec[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE])
            if not _entry_live(e):
                continue
            old_pos[slot] = pack
            pack += e[DIR_SIZE_UNITS_OFFSET] * DIR_UNIT_SIZE
        old_pack_end = pack

        # Fichiers vivants (répertoire actuel) + leurs données (positions
        # anciennes).
        live: List[List] = []
        for slot in range(DIR_MAX_ENTRIES):
            e = bytes(sec[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE])
            if not _entry_live(e):
                continue
            sz = e[DIR_SIZE_UNITS_OFFSET] * DIR_UNIT_SIZE
            live.append([slot, e, self._read_linear(old_pos[slot], sz)])

        if insert is not None:
            dir_field, chunks, slot, pdata = insert
            counter = max((max(e[DIR_TAIL_OFFSET:DIR_TAIL_OFFSET + 16])
                           for _, e, _ in live), default=1) + 1
            for k, units in enumerate(chunks):
                e = bytearray(DIR_ENTRY_SIZE)
                e[DIR_NAME_OFFSET:DIR_NAME_OFFSET + DIR_NAME_SIZE] = dir_field
                e[DIR_CHUNK_INDEX_OFFSET] = k
                e[DIR_SIZE_UNITS_OFFSET] = units
                ktail = (units * DIR_UNIT_SIZE + 1023) // 1024
                for b in range(ktail):
                    e[DIR_TAIL_OFFSET + b] = counter
                    counter += 1
                live.append([
                    slot + k,
                    bytes(e),
                    pdata[k * DIR_MAX_CHUNK_BYTES:(k + 1) * DIR_MAX_CHUNK_BYTES],
                ])

        live.sort(key=lambda t: t[0])

        new_sec = bytearray(sec)
        for slot, e, _ in live:
            new_sec[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE] = e
        self.disk.set_sector(DIR_TRACK, DIR_SECTOR, bytes(new_sec))

        pack = len(old_sec)
        for slot, e, data in live:
            self._write_linear(pack, data)
            pack += e[DIR_SIZE_UNITS_OFFSET] * DIR_UNIT_SIZE

        if pack < old_pack_end:
            # La queue libérée (suppression) revient à l'état vierge, sinon
            # une écriture Filer suivante au même endroit la verrait
            # « occupée ».
            self._write_linear(pack, bytes(old_pack_end - pack))

    # ------------------------------------------------------------------ #
    # API publique : écriture / suppression
    # ------------------------------------------------------------------ #
    def write_file(self, name: str, data: bytes,
                   file_type: int = FT_BINARY,
                   load_addr: int = 0,
                   exec_addr: int = 0,
                   mode: str = "both") -> CpcFile:
        """Écrit un fichier sur la disquette.

        ``mode``:
          - ``"filer"``  : fichier Filer (données brutes + entrées du
            répertoire). Lu par le vrai DOS CPC / Gotek sur matériel réel.
            ``file_type``/``load_addr``/``exec_addr`` sont ignorés.
          - ``"amsdos"`` : objet AMSDOS (en-tête 128 o + données), lu par les
            émulateurs qui balayent les en-têtes (ex. CERMU).
          - ``"both"`` (défaut) : les deux — le disque est lisible à la fois
            par le vrai DOS et les émulateurs (agencement identique à celui
            des disques réels d'époque).

        Allocation : les fichiers Filer grandissent vers l'avant (fin du
        paquet, contrainte du format) ; les objets AMSDOS sont empilés vers
        l'arrière depuis la fin du disque.
        """
        if mode not in ("filer", "amsdos", "both"):
            raise CpcError(f"Mode inconnu: {mode!r} (filer|amsdos|both).")
        if not data:
            raise CpcError("Fichier vide: rien à écrire.")
        field11 = _normalize_83(name)

        if mode in ("filer", "both") and self.find(field11, source="filer") is not None:
            raise CpcError(f"Fichier déjà présent (répertoire Filer): {field11!r}")
        if mode in ("amsdos", "both") and self.find(field11, source="amsdos") is not None:
            raise CpcError(f"Fichier déjà présent (AMSDOS): {field11!r}")

        total_units = (len(data) + DIR_UNIT_SIZE - 1) // DIR_UNIT_SIZE
        total_bytes = total_units * DIR_UNIT_SIZE

        pos_f = None
        pos_a = None
        filer_end = 0  # linéaire de fin du paquet Filer après écriture

        if mode in ("filer", "both"):
            self._assert_amsdos_outside_pack()
            pack_end = self._pack_bounds()[1]
            pos_f = self._linear_to_image(pack_end)
            if not self._linear_region_free(pack_end, total_bytes):
                raise CpcError(
                    "Espace du paquet Filer occupé par des données inattendues "
                    "(disque partiellement utilisé d'une façon inconnue).")
            filer_end = pack_end + total_bytes

        dest_a = None
        if mode in ("amsdos", "both"):
            need = AMSDOS_HEADER_SIZE + len(data)
            end_front = self._amsdos_end_frontier()
            if end_front - need < filer_end:
                raise CpcError(
                    f"Pas assez d'espace libre (objet AMSDOS {need} o + paquet "
                    f"Filer).")
            dest_a = end_front - need
            if not self._linear_region_free(dest_a, need):
                raise CpcError(
                    f"Espace de destination AMSDOS occupé par des données "
                    f"inattendues (disque partiellement utilisé d'une façon "
                    f"inconnue).")
            pos_a = self._linear_to_image(dest_a)

        # 1) Fichier Filer : données brutes (remplies à 128 o) + entrées.
        if mode in ("filer", "both"):
            padded = data + bytes(total_bytes - len(data))
            chunks: List[int] = []
            rest = len(data)
            while rest > 0:
                c = min(rest, DIR_MAX_CHUNK_BYTES)
                chunks.append((c + DIR_UNIT_SIZE - 1) // DIR_UNIT_SIZE)
                rest -= c
            sec = self._dir_sector()
            free_slots = [
                s for s in range(DIR_MAX_ENTRIES)
                if not _entry_live(bytes(sec[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE]))
            ]
            slot = _first_free_run(free_slots, len(chunks))
            if slot is None:
                raise CpcError(
                    "Répertoire Filer plein (16 entrées max, chunks inclus).")
            dir_field = field11.replace(".", chr(DIR_DOT_BYTE)).encode("latin1")
            self._repack_filer(insert=(dir_field, chunks, slot, padded))

        # 2) Objet AMSDOS : en-tête 128 o + données, écrits dans le flux
        #    physique : l'objet traverse les pistes sans toucher les
        #    en-têtes Track-Info du conteneur (agencement des disques réels,
        #    vérifié sur greed.dsk).
        if mode in ("amsdos", "both"):
            hdr = bytearray(AMSDOS_HEADER_SIZE)
            hdr[NAME_OFFSET:NAME_OFFSET + NAME_SIZE] = field11.encode("latin1")
            hdr[TYPE_OFFSET:TYPE_OFFSET + 2] = struct.pack("<H", file_type)
            hdr[LOAD_OFFSET:LOAD_OFFSET + 2] = struct.pack("<H", load_addr)
            hdr[LEN16_OFFSET:LEN16_OFFSET + 2] = struct.pack("<H", len(data) & 0xFFFF)
            hdr[EXEC_OFFSET:EXEC_OFFSET + 2] = struct.pack("<H", exec_addr)
            hdr[LEN24_OFFSET:LEN24_OFFSET + 3] = len(data).to_bytes(3, "little")
            csum = sum(hdr[:CHECKSUM_COVERED]) & 0xFFFF
            hdr[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 2] = struct.pack("<H", csum)
            self._write_linear(dest_a, bytes(hdr) + data)

        return CpcFile(
            name=field11.rstrip(),
            offset=pos_a if pos_a is not None else (pos_f or 0),
            file_type=file_type if mode != "filer" else FT_UNKNOWN,
            load_addr=load_addr,
            exec_addr=exec_addr,
            length=len(data),
            source={"filer": "FILER", "amsdos": "AMSDOS",
                    "both": "FILER+AMSDOS"}[mode],
        )

    def delete_file(self, name: str) -> None:
        """Supprime un fichier des deux couches (celles où il existe).

        Filer : entrées remplies 0xE5, paquet recollé. AMSDOS : en-tête +
        données mis à zéro.
        """
        field11 = _normalize_83(name)
        field_dir = field11.replace(".", chr(DIR_DOT_BYTE)).encode("latin1")
        deleted = False

        sec = self._dir_sector()
        hit = [
            s for s in range(DIR_MAX_ENTRIES)
            if _entry_live(bytes(sec[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE]))
            and bytes(sec[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE])[
                DIR_NAME_OFFSET:DIR_NAME_OFFSET + DIR_NAME_SIZE] == field_dir
        ]
        if hit:
            self._assert_amsdos_outside_pack()
            secb = bytearray(sec)
            for s in hit:
                secb[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE] = DIR_EMPTY_ENTRY
            self.disk.set_sector(DIR_TRACK, DIR_SECTOR, bytes(secb))
            # Les données des fichiers suivants sont encore à leur ancienne
            # place (le trou compris) : layout de référence = sec.
            self._repack_filer(old_sec=sec)
            deleted = True

        f = self.find(field11, source="amsdos")
        if f is not None:
            # Flux physique : l'objet peut traverser plusieurs pistes.
            lin = self._image_to_linear(f.offset)
            self._write_linear(lin, b"\x00" * (AMSDOS_HEADER_SIZE + f.length))
            deleted = True

        if not deleted:
            raise CpcError(f"Fichier introuvable: {name!r}")
