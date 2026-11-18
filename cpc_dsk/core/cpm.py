"""CP/M 2.2 (CPM) pour le CPC : images « System format ».

Au-dessus du conteneur :mod:`cpc_dsk.core.adf`, ce module lit/écrit les
disquettes **CP/M 2.2** du CPC (format « System format », celui que
produit SYSGEN de CP/M et que charge le BIOS AMSDOS sur le vrai
matériel — c'est le système à tester avec le Gotek).

Géométrie (vérifiée sur 3 disques réels : cpm22.dsk, Planetfall, Starcross)
===========================================================================
::

    40 pistes × 1 face × 9 secteurs × 512 o
    IDs de secteur : 41 46 42 47 43 48 44 49 45 (ordre cpm22) ou 41..49
    (ordre séquentiel, Planetfall) — les deux sont valides ; l'ordre réel
    est celui des enregistrements Track-Info (0x18 + i×8).
    gap3 = 0x2A (cpm22 ; 0x4E sur Planetfall — indifférent aux lecteurs),
    octet de remplissage = 0xE5, code taille = 2 (512 o).

Secteurs système (identiques d'un disque à l'autre, localisés **par ID**)
==========================================================================
::

    Piste 0
        &41  boot : charge &42 à &300 puis passe la main au WBOOT (ROM).
                  Préfixe : 60 69 11 00 05 01
        &42  configuration : couleurs, bannière de démarrage, tables
                  clavier. Préfixe : 35 12 32 00 FA 00 0C 81
        &48  CP/M partie 1 (en-tête JP &9A5C, lu par le WBOOT)
        &49  CP/M partie 2
    Piste 1 : les 9 secteurs entiers (CCP + BDOS chargés à &9700..&AD00)

Répertoire CP/M (format Filer, piste 2)
=======================================
Les 3 premiers secteurs physiques de la piste 2 : 48 entrées de 32 o
(même agencement que le répertoire Filer du CPC — vérifié sur cpm22.dsk).
Entrée occupée ::

    Offset  Taille  Champ
    0x00    1       0x00
    0x01    11      nom 8.3 : base 8 + extension 3, **séparateur espace**
                    (pas de '.' ni de 0xC9), latin1
    0x0C    1       index du chunk (0, 1, 2, …)
    0x0D    2       0x00 0x00
    0x0F    1       taille du chunk en unités de 128 o (max 0x80 = 16 Ko)
    0x10    16      compteur d'allocation global (démarre à 0x02, valeurs
                    consécutives d'un disque à l'autre), puis zéros

Entrée vide : 32 × 0xE5 (ou 32 × 0x00 — les deux coexistent sur cpm22).

Paquet de données
=================
Les fichiers sont empilés séquentiellement dans l'ordre du répertoire, à
partir du 4e secteur physique de la piste 2 (position linéaire 10752),
au multiple de 128 o, remplissage 0xE5 pour les espaces de queue.

Deux types d'objets cohabitent :

- **Fichiers du répertoire CP/M** : données brutes (COM/BAS de CP/M) ou
  préfixées d'un **en-tête AMSDOS** de 128 o (fichiers créés par Amsdos
  : celui-ci écrit l'en-tête dans la région allouée). La lecture retire
  l'en-tête s'il est présent et valide (checksum + nom concordant).
- **Objets AMSDOS associés (« legacy »)** : sur les disques réels, certains
  fichiers ont une entrée de répertoire mais leur contenu réel est un
  objet AMSDOS (en-tête 128 o + données, checksum valide) inséré
  dans/autour de l'allocation du répertoire — souvent avec préfixe de
  remplissage 0xE5 (l'objet ne démarre pas au début de la région) — et
  parfois **plusieurs objets** portent le même nom (copies d'époque,
  ex. RITDEMO.BIN, DISC.BAS sur cpm22). La lecture retombe sur l'objet
  le plus proche de la région du répertoire, trouvé par balayage.

Création de disques
===================
:func:`new_cpm_system_disk` génère un disque système CP/M 2.2
amorphe, à partir d'une image de référence (CP/M 2.2 + Amsdos 2.0
extraits d'un cpm22.dsk réel, ``cpc_dsk/data/cpm22_system.bin``).
Les Track-Infos produites sont **identiques à l'octet** à celles du
cpm22.dsk réel (IDs, gap3 0x2A, enregistrements de secteurs) : WinAPE
les valide sans réserve.
"""

from __future__ import annotations

import os
import struct
import sys
from typing import List, Optional, Tuple

from cpc_dsk.core.adf import (
    ADFDisk,
    ADFError,
    TRACK_INFO_SIZE,
    TRACK_INFO_NUM_SECTORS_OFFSET,
)
from cpc_dsk.core.cpcfs import (
    AMSDOS_HEADER_SIZE,
    CHECKSUM_COVERED,
    CHECKSUM_OFFSET,
    CpcDirEntry,
    CpcError,
    CpcFile,
    CpcFilesystem,
    DIR_ENTRY_SIZE,
    DIR_MAX_CHUNK_BYTES,
    DIR_UNIT_SIZE,
    EXEC_OFFSET,
    LEN16_OFFSET,
    LEN24_OFFSET,
    LOAD_OFFSET,
    NAME_OFFSET,
    NAME_SIZE,
    TYPE_OFFSET,
    FT_BASIC,
    FT_BINARY,
    FT_UNKNOWN,
    _normalize_83,
    _valid_name,
)

# --- Géométrie CP/M ---
CPM_TRACKS = 40
CPM_SIDES = 1
CPM_SECTORS = 9
CPM_SECTOR_SIZE = 512
CPM_TRACK_DATA_SIZE = CPM_SECTORS * CPM_SECTOR_SIZE            # 4608
CPM_TRACK_BLOCK_SIZE = TRACK_INFO_SIZE + CPM_TRACK_DATA_SIZE   # 4864
CPM_CAPACITY = CPM_TRACKS * CPM_TRACK_DATA_SIZE                # 184320

# IDs de secteur d'une piste CP/M (ordre du cpm22.dsk réel).
CPM_SECTOR_IDS = (0x41, 0x46, 0x42, 0x47, 0x43, 0x48, 0x44, 0x49, 0x45)
CPM_SECTOR_ID_SET = frozenset(CPM_SECTOR_IDS)
CPM_GAP3 = 0x2A   # valeur observée sur cpm22.dsk

# IDs des secteurs système (piste 0).
CPM_BOOT_ID = 0x41
CPM_CONFIG_ID = 0x42
CPM_SYS1_ID = 0x48
CPM_SYS2_ID = 0x49

BOOT_PREFIX = b"\x60\x69\x11\x00\x05\x01"
CONFIG_PREFIX = b"\x35\x12\x32\x00\xfa\x00\x0c\x81"

# --- Répertoire CP/M (piste 2, 3 premiers secteurs physiques) ---
CPM_DIR_TRACK = 2
CPM_DIR_SECTORS = 3
CPM_DIR_OFFSET = CPM_DIR_TRACK * CPM_TRACK_DATA_SIZE               # 9216
CPM_DIR_SIZE = CPM_DIR_SECTORS * CPM_SECTOR_SIZE                   # 1536
CPM_DIR_MAX_ENTRIES = CPM_DIR_SIZE // DIR_ENTRY_SIZE               # 48
CPM_DIR_EMPTY_E5 = b"\xE5" * DIR_ENTRY_SIZE
CPM_DIR_EMPTY_00 = b"\x00" * DIR_ENTRY_SIZE

# --- Paquet de données (après le répertoire) ---
CPM_PACK_START = CPM_DIR_OFFSET + CPM_DIR_SIZE                     # 10752

# --- Image de référence (cpc_dsk/data/cpm22_system.bin) ---
_REFERENCE_NAME = "cpm22_system.bin"
_OFF_BOOT = 0
_OFF_CONFIG = 512
_OFF_SYS1 = 1024
_OFF_SYS2 = 1536
_OFF_TRACK1 = 2048
_OFF_TRACK1_END = _OFF_TRACK1 + CPM_TRACK_DATA_SIZE    # 6656
_OFF_UTILS = 6656     # utilitaires : nom 8+3 (11 o) + longueur LE32 + données
CPM22_SYSTEM_SIZE = 46780   # cf. scripts/make_cpm_reference.py

__all__ = [
    "CPM_TRACKS", "CPM_SIDES", "CPM_SECTORS", "CPM_SECTOR_SIZE",
    "CPM_TRACK_DATA_SIZE", "CPM_TRACK_BLOCK_SIZE", "CPM_CAPACITY",
    "CPM_SECTOR_IDS", "CPM_SECTOR_ID_SET", "CPM_GAP3",
    "CPM_BOOT_ID", "CPM_CONFIG_ID", "CPM_SYS1_ID", "CPM_SYS2_ID",
    "BOOT_PREFIX", "CONFIG_PREFIX",
    "CPM_DIR_TRACK", "CPM_DIR_SECTORS", "CPM_DIR_OFFSET", "CPM_DIR_SIZE",
    "CPM_DIR_MAX_ENTRIES", "CPM_DIR_EMPTY_E5", "CPM_DIR_EMPTY_00",
    "CPM_PACK_START", "CPM22_SYSTEM_SIZE",
    "is_cpm_disk", "new_cpm_system_disk", "CpmFilesystem", "CpcError",
]


# --------------------------------------------------------------------------- #
# Accès aux secteurs par ID
# --------------------------------------------------------------------------- #
def _track_sector_ids(disk: ADFDisk, track: int) -> List[int]:
    """IDs de secteur d'une piste (ordre physique, enregistrements Track-Info)."""
    off = disk.track_offsets[track]
    ti = disk._raw[off:off + TRACK_INFO_SIZE]
    ns = ti[TRACK_INFO_NUM_SECTORS_OFFSET]
    return [ti[0x18 + i * 8 + 2] for i in range(ns)]


def _id_to_index(disk: ADFDisk, track: int, sec_id: int) -> int:
    """Index physique du secteur d'ID ``sec_id`` sur la piste ``track``."""
    for i, sid in enumerate(_track_sector_ids(disk, track)):
        if sid == sec_id:
            return i
    raise CpcError(f"Secteur ID &{sec_id:02X} introuvable (piste {track}).")


def _sector_by_id(disk: ADFDisk, track: int, sec_id: int) -> bytes:
    """Lecture d'un secteur par son ID (et non son index physique)."""
    return disk.get_sector(track, _id_to_index(disk, track, sec_id))


def _write_sector_by_id(disk: ADFDisk, track: int, sec_id: int,
                        data: bytes) -> None:
    disk.set_sector(track, _id_to_index(disk, track, sec_id), data)


def is_cpm_disk(disk: ADFDisk) -> bool:
    """Vrai si l'image est un disque CP/M 2.2 (« System format »).

    Critères : géométrie 40×1×9×512, IDs de secteur &41..&49 sur la piste 0,
    secteurs boot (&41) et configuration (&42) reconnaissables à leur
    préfixe.
    """
    if disk.num_tracks != CPM_TRACKS or disk.num_sides != CPM_SIDES:
        return False
    if any(t != CPM_TRACK_BLOCK_SIZE for t in disk.track_sizes):
        return False
    try:
        if set(_track_sector_ids(disk, 0)) != CPM_SECTOR_ID_SET:
            return False
        boot = _sector_by_id(disk, 0, CPM_BOOT_ID)
        conf = _sector_by_id(disk, 0, CPM_CONFIG_ID)
    except (CpcError, ADFError):
        return False
    return (boot[:len(BOOT_PREFIX)] == BOOT_PREFIX
            and conf[:len(CONFIG_PREFIX)] == CONFIG_PREFIX)


# --------------------------------------------------------------------------- #
# Image de référence
# --------------------------------------------------------------------------- #
def _reference_path() -> str:
    """Chemin de l'image de référence (compatible PyInstaller)."""
    here = os.path.dirname(os.path.abspath(__file__))  # cpc_dsk/core
    cand = os.path.normpath(
        os.path.join(here, os.pardir, "data", _REFERENCE_NAME))
    if os.path.isfile(cand):
        return cand
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cand = os.path.join(meipass, "cpc_dsk", "data", _REFERENCE_NAME)
        if os.path.isfile(cand):
            return cand
    raise CpcError(f"Image de référence CP/M introuvable: {cand}")


def _reference_bin() -> bytes:
    """Lit l'image de référence CP/M 2.2 (cpc_dsk/data/cpm22_system.bin)."""
    with open(_reference_path(), "rb") as fh:
        data = fh.read()
    if len(data) != CPM22_SYSTEM_SIZE:
        raise CpcError(
            f"Image de référence CP/M corrompue: {len(data)} o, attendu "
            f"{CPM22_SYSTEM_SIZE} o.")
    return data


# --------------------------------------------------------------------------- #
# Utilitaires noms / en-têtes
# --------------------------------------------------------------------------- #
def _cpm_to_ascii(data: bytes) -> bytes:
    """Jeu de caractères CP/M vers ASCII (0xC1..0xD6 = A..Z, 0x80 = @).

    Les entrées de répertoire des disques CP/M réels portent des noms soit
    en jeu de caractères CP/M (Planetfall : « PLANET.COM » =
    50 4C 41 4E 45 54 20 20 C3 4F 4D), soit en ASCII (cpm22, écrit par
    Amsdos) — la traduction est un no-op dans ce dernier cas.
    """
    out = bytearray(len(data))
    for i, b in enumerate(data):
        if 0xC1 <= b <= 0xD6:
            out[i] = b - 0xC1 + 0x41
        elif b == 0x80:
            out[i] = 0x40
        else:
            out[i] = b
    return bytes(out)


def _dir_field_to_name(field: bytes) -> str:
    """Champ de répertoire 11 o (base 8 + ext 3, séparateur espace) vers nom.

    Tout nom CP/M est 8.3 : « AMSDOS  COM » → ``AMSDOS.COM``,
    « DISCKIT2COM » → ``DISCKIT2.COM``, « ROINTIMEDEM » → ``ROINTIME.DEM``.
    Les champs en jeu de caractères CP/M sont d'abord traduits en ASCII.
    """
    txt = _cpm_to_ascii(field).decode("latin1")
    base = txt[:8].rstrip()
    ext = txt[8:11].rstrip()
    return base + ("." + ext if ext else "")


def _cpm_field11(name: str) -> str:
    """Nom utilisateur vers champ 11 o CP/M (séparateur espace).

    « RITDEMO.BIN » → « RITDEMO BIN » ; les noms 11 caractères sans point
    (ex. « ROINTIMEDEM ») sont des champs déjà formés (base 8 + ext 3) —
    :func:`cpc_dsk.core.cpcfs._normalize_83` ne sait pas re-découper un nom
    11 caractères **ponctué** (cas Filer), d'où la conversion préalable.
    """
    if "." in name:
        base, _, ext = name.partition(".")
        name = (base + " " + ext).strip()
    return _normalize_83(name)


def _valid_amsdos_header(hdr: bytes, name: Optional[str] = None) -> bool:
    """Vrai si 128 octets forment un en-tête AMSDOS valide (checksum, nom ;
    nom concordant si ``name`` fourni)."""
    name_raw = hdr[NAME_OFFSET:NAME_OFFSET + NAME_SIZE]
    if not _valid_name(name_raw):
        return False
    stored = hdr[CHECKSUM_OFFSET] | (hdr[CHECKSUM_OFFSET + 1] << 8)
    if sum(hdr[:CHECKSUM_COVERED]) & 0xFFFF != stored:
        return False
    if name is not None:
        from cpc_dsk.core.cpcfs import _clean_name
        if _cpm_field11(_clean_name(name_raw)) != _cpm_field11(name):
            return False
    return True


def _build_amsdos_header(field11: str, file_type: int, load_addr: int,
                         length: int, exec_addr: int) -> bytes:
    """Construit un en-tête AMSDOS de 128 o (checksum inclus)."""
    hdr = bytearray(AMSDOS_HEADER_SIZE)
    hdr[NAME_OFFSET:NAME_OFFSET + NAME_SIZE] = field11.encode("latin1")
    hdr[TYPE_OFFSET:TYPE_OFFSET + 2] = struct.pack("<H", file_type)
    hdr[LOAD_OFFSET:LOAD_OFFSET + 2] = struct.pack("<H", load_addr)
    hdr[LEN16_OFFSET:LEN16_OFFSET + 2] = struct.pack("<H", length & 0xFFFF)
    hdr[EXEC_OFFSET:EXEC_OFFSET + 2] = struct.pack("<H", exec_addr)
    hdr[LEN24_OFFSET:LEN24_OFFSET + 3] = length.to_bytes(3, "little")
    csum = sum(hdr[:CHECKSUM_COVERED]) & 0xFFFF
    hdr[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 2] = struct.pack("<H", csum)
    return bytes(hdr)


def _first_free_run(free: List[int], n: int) -> Optional[int]:
    """Plus petit slot ``s`` (sur 48) tel que ``s..s+n-1`` sont tous libres."""
    free_set = set(free)
    for s in sorted(free_set):
        if s + n <= CPM_DIR_MAX_ENTRIES and all(
                x in free_set for x in range(s, s + n)):
            return s
    return None


# --------------------------------------------------------------------------- #
# Création d'un disque système CP/M
# --------------------------------------------------------------------------- #
def new_cpm_system_disk(with_utils: bool = True,
                        reference: Optional[bytes] = None,
                        creator: str = "cpc-dsk v1.0") -> ADFDisk:
    """Crée un disque système CP/M 2.2 amorphe (« System format »).

    Le système provient de l'image de référence (CP/M 2.2 + Amsdos 2.0,
    extraits d'un cpm22.dsk réel) : secteurs boot (&41), configuration
    (&42), CP/M (&48/&49) et piste 1 complète (CCP+BDOS).

    ``with_utils=True`` (défaut) ajoute les 4 utilitaires de base avec
    leurs entrées de répertoire : AMSDOS.COM, DISCKIT2.COM, LOGO2.COM,
    LOGO2.SUB — un système opérationnel pour tester le Gotek.
    ``with_utils=False`` laisse le répertoire vide (le boot reste possible,
    mais les commandes CP/M ne sont pas sur disque).

    Les Track-Infos produites sont identiques à l'octet à celles du
    cpm22.dsk réel (IDs &41..&49 en ordre 41 46 42 47 43 48 44 49 45,
    gap3 0x2A, enregistrements de secteurs) : WinAPE les valide.
    """
    ref = reference if reference is not None else _reference_bin()
    if len(ref) != CPM22_SYSTEM_SIZE:
        raise CpcError(
            f"Image de référence CP/M invalide: {len(ref)} o, attendu "
            f"{CPM22_SYSTEM_SIZE} o.")

    disk = ADFDisk.new_blank(
        tracks=CPM_TRACKS, sides=CPM_SIDES,
        sectors=CPM_SECTORS, sector_size=CPM_SECTOR_SIZE,
        sector_ids=CPM_SECTOR_IDS, gap3=CPM_GAP3, creator=creator)

    # Secteurs système (localisés par ID, comme sur les disques réels).
    _write_sector_by_id(disk, 0, CPM_BOOT_ID,
                        ref[_OFF_BOOT:_OFF_BOOT + CPM_SECTOR_SIZE])
    _write_sector_by_id(disk, 0, CPM_CONFIG_ID,
                        ref[_OFF_CONFIG:_OFF_CONFIG + CPM_SECTOR_SIZE])
    _write_sector_by_id(disk, 0, CPM_SYS1_ID,
                        ref[_OFF_SYS1:_OFF_SYS1 + CPM_SECTOR_SIZE])
    _write_sector_by_id(disk, 0, CPM_SYS2_ID,
                        ref[_OFF_SYS2:_OFF_SYS2 + CPM_SECTOR_SIZE])
    # Piste 1 : CCP + BDOS entiers (9 secteurs, ordre image du disque réel).
    disk.set_track_data(1, ref[_OFF_TRACK1:_OFF_TRACK1_END])

    if with_utils:
        # Écrits par le vrai catalogue CP/M (blocs de 1 Ko repérés par ID de
        # secteur) : le CP/M de la machine les retrouve à l'identique.
        from cpc_dsk.core.amsdos import AmsdosFilesystem, SYSTEM
        fs = AmsdosFilesystem(disk, SYSTEM)
        for name, data in _reference_utils(ref):
            fs.write_file(name, data, mode="raw")
    return disk


def _reference_utils(ref: bytes) -> List[Tuple[str, bytes]]:
    """Utilitaires rangés dans l'image de référence : [(nom 8+3, données)]."""
    out = []
    pos = _OFF_UTILS
    while pos < len(ref):
        field11 = ref[pos:pos + 11].decode("latin1")
        (n,) = struct.unpack_from("<I", ref, pos + 11)
        out.append((field11, ref[pos + 15:pos + 15 + n]))
        pos += 15 + n
    return out


# --------------------------------------------------------------------------- #
# Système de fichiers CP/M
# --------------------------------------------------------------------------- #
def _guess_type(name: str) -> int:
    """Type AMSDOS probable d'après l'extension (le répertoire CP/M ne
    stocke pas le type)."""
    ext = name.rsplit(".", 1)[1].upper() if "." in name else name[-3:].upper()
    if ext == "BAS":
        return FT_BASIC
    if ext in ("COM", "BIN"):
        return FT_BINARY
    return FT_UNKNOWN


class CpmFilesystem:
    """Système de fichiers CP/M 2.2 d'une image .dsk.

    Deux couches, comme sur les disques réels :

    - le **répertoire CP/M** (piste 2, 48 entrées, format Filer) — lu par
      le vrai BDOS CP/M (et donc le Gotek sur matériel réel) ;
    - les **objets AMSDOS** (en-têtes 128 o balayées, méthode CERMU) — lu
      par les émulateurs, et support de repli pour les fichiers « legacy »
      dont la région du répertoire est vide mais qui ont un objet AMSDOS
      ailleurs sur le disque.

    ``CpcFile.source`` est ``"CPM"`` pour les fichiers du répertoire,
    ``"AMSDOS"`` pour les objets isolés.
    """

    def __init__(self, disk: ADFDisk):
        if not is_cpm_disk(disk):
            raise CpcError(
                "Image non CP/M : géométrie 40×1×9×512, IDs de secteur "
                "&41..&49 et secteurs boot/configuration attendus "
                "(« System format » CP/M 2.2).")
        self.disk = disk
        self._helper = CpcFilesystem(disk)

    # ------------------------------------------------------------------ #
    # Répertoire CP/M — lecture
    # ------------------------------------------------------------------ #
    def _dir_raw(self) -> bytes:
        return self._helper._read_linear(CPM_DIR_OFFSET, CPM_DIR_SIZE)

    @staticmethod
    def _field(entry: bytes) -> bytes:
        """Champ nom 11 o de l'entrée, traduit en ASCII (jeu CP/M géré)."""
        return _cpm_to_ascii(entry[1:12])

    @staticmethod
    def _entry_live(entry: bytes) -> bool:
        """Vraie si l'entrée 32 o est occupée (ni 0xE5, ni 0x00, nom valide)."""
        if len(entry) != DIR_ENTRY_SIZE:
            return False
        if entry in (CPM_DIR_EMPTY_E5, CPM_DIR_EMPTY_00):
            return False
        return _valid_name(_cpm_to_ascii(entry[1:12]))

    def read_directory(self) -> List[CpcDirEntry]:
        """Lit les entrées du répertoire CP/M occupées (une par chunk)."""
        raw = self._dir_raw()
        entries: List[CpcDirEntry] = []
        for slot in range(CPM_DIR_MAX_ENTRIES):
            e = raw[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE]
            if not self._entry_live(e):
                continue
            entries.append(CpcDirEntry(
                slot=slot,
                name=_dir_field_to_name(e[1:12]),
                chunk_index=e[0x0C],
                size_units=e[0x0F],
                tail_max=max(e[0x10:0x10 + 16]),
            ))
        return entries

    def _pack_end(self) -> int:
        """Position linéaire de fin du paquet (après la dernière allocation)."""
        end = CPM_PACK_START
        for e in self.read_directory():
            end += e.size_bytes
        return end

    def _files_with_slots(self) -> Tuple[List[CpcFile], dict]:
        """Fichiers du répertoire (chunks regroupés) + slot de chaque entrée.

        ``offset`` = début de la région allouée (image), ``length`` = taille
        totale allouée (arrondie au 128 o, somme des chunks).
        """
        raw = self._dir_raw()
        files: List[CpcFile] = []
        slot_of: dict = {}
        pos = CPM_PACK_START
        prev_field: Optional[bytes] = None
        for slot in range(CPM_DIR_MAX_ENTRIES):
            e = raw[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE]
            if not self._entry_live(e):
                continue
            field = self._field(e)
            size = e[0x0F] * DIR_UNIT_SIZE
            if field != prev_field:
                name = _dir_field_to_name(field)
                files.append(CpcFile(
                    name=name,
                    offset=self._helper._linear_to_image(pos),
                    file_type=_guess_type(name),
                    load_addr=0,
                    exec_addr=0,
                    length=0,
                    source="CPM",
                ))
                prev_field = field
            files[-1].length += size
            slot_of[slot] = files[-1]
            pos += size
        return files, slot_of

    def list_files(self, source: Optional[str] = None) -> List[CpcFile]:
        """Liste les fichiers.

        ``source`` : ``"cpm"`` (répertoire CP/M seulement), ``"amsdos"``
        (objets AMSDOS balayés seulement) ou ``None`` pour les deux
        (répertoire d'abord, puis objets AMSDOS dont le nom n'est pas dans
        le répertoire — les legacy n'apparaissent qu'une seule fois, sous
        leur nom de répertoire).
        """
        if source is not None:
            source = source.lower()
        if source == "amsdos":
            return self._helper._scan_amsdos()
        if source in ("cpm", "filer"):
            return self._files_with_slots()[0]
        dir_files = self._files_with_slots()[0]
        dir_fields = [_cpm_field11(f.name) for f in dir_files]
        out = list(dir_files)
        for a in self._helper._scan_amsdos():
            fa = _cpm_field11(a.name)
            a_base, a_ext = fa[:8].rstrip(), fa[8:11].rstrip()
            # Objet « réclamé » par un fichier du répertoire (correspondance
            # exacte ou legacy : base identique, extension vide ou égale).
            claimed = any(
                fa == d
                or (d[:8].rstrip() == a_base
                    and a_ext in ("", d[8:11].rstrip()))
                for d in dir_fields
            )
            if not claimed:
                out.append(a)
        return out

    @staticmethod
    def _amsdos_matches_name(a_name: str, dir_name: str) -> bool:
        """Vrai si l'objet AMSDOS ``a_name`` correspond au fichier de
        répertoire ``dir_name`` : correspondance exacte sur le champ 8.3,
        ou legacy (base identique, extension de l'objet vide ou égale) —
        les disques réels portent des objets AMSDOS sans extension
        (``RITDEMO`` pour le fichier ``RITDEMO.BIN`` du répertoire)."""
        fa = _cpm_field11(a_name)
        fd = _cpm_field11(dir_name)
        if fa == fd:
            return True
        a_base, a_ext = fa[:8].rstrip(), fa[8:11].rstrip()
        d_base, d_ext = fd[:8].rstrip(), fd[8:11].rstrip()
        return d_base == a_base and a_ext in ("", d_ext)

    def _amsdos_by_name(self, name: str,
                        near_lin: Optional[int] = None,
                        near_span: int = 0) -> Optional[CpcFile]:
        """Objet AMSDOS correspondant à un nom.

        Avec ``near_lin``/``near_span`` (région du répertoire), le
        candidat retenu est le plus proche de cette région — les disques
        réels en portent parfois plusieurs pour le même fichier (copies),
        le contenu étant celui qui chevauche ou avoisine l'allocation.
        """
        field11 = _cpm_field11(name)
        base = field11[:8].rstrip()
        ext = field11[8:11].rstrip()
        cands = [
            a for a in self._helper._scan_amsdos()
            if _cpm_field11(a.name) == field11
            or (_cpm_field11(a.name)[:8].rstrip() == base
                and _cpm_field11(a.name)[8:11].rstrip() in ("", ext))
        ]
        if not cands:
            return None
        if near_lin is None:
            return cands[0]

        def dist(a: CpcFile) -> int:
            start = self._helper._image_to_linear(a.offset)
            d = start - near_lin
            if 0 <= d < near_span:
                return d  # dans la région du répertoire
            return near_span + abs(d)  # à l'extérieur

        return min(cands, key=dist)

    def find(self, name: str, source: Optional[str] = None) -> Optional[CpcFile]:
        """Retrouve un fichier par nom.

        Sans ``source`` : le répertoire CP/M d'abord (couche lue par le vrai
        DOS), puis les objets AMSDOS isolés.
        """
        field11 = _cpm_field11(name)
        if source is not None:
            source = source.lower()
        if source in (None, "cpm", "filer"):
            raw = self._dir_raw()
            _, slot_of = self._files_with_slots()
            for slot in range(CPM_DIR_MAX_ENTRIES):
                e = raw[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE]
                if (self._entry_live(e)
                        and self._field(e).rstrip()
                        == field11.encode("latin1")):
                    return slot_of[slot]
        if source in (None, "amsdos"):
            for f in self._helper._scan_amsdos():
                if _cpm_field11(f.name) == field11:
                    return f
        return None

    # ------------------------------------------------------------------ #
    # Lecture des fichiers
    # ------------------------------------------------------------------ #
    def read_file(self, name: str, source: Optional[str] = None) -> bytes:
        """Lit les données d'un fichier.

        Fichier du répertoire CP/M :

        - région allouée préfixée d'un en-tête AMSDOS valide (checksum +
          nom concordant) : l'en-tête est retiré, longueur exacte restituée ;
        - sinon, si un objet AMSDOS valide porte ce nom : c'est le contenu
          réel (fichiers « legacy » des disques réels — l'objet est
          inséré dans/autour de l'allocation du répertoire, éventuellement
          avec préfixe de remplissage 0xE5) ; l'objet le plus proche de la
          région du répertoire est lu ;
        - sinon : la région allouée brute (COM/BAS de CP/M, éventuellement
          suivis de remplissage 0xE5).

        Objet AMSDOS : les données exactes (après l'en-tête de 128 o).
        """
        f = self.find(name, source)
        if f is None:
            raise CpcError(f"Fichier introuvable: {name!r}")
        if f.source == "AMSDOS":
            lin = self._helper._image_to_linear(f.offset)
            return self._helper._read_linear(
                lin + AMSDOS_HEADER_SIZE, f.length)

        lin = self._helper._image_to_linear(f.offset)
        region = self._helper._read_linear(lin, f.length)
        if (len(region) >= AMSDOS_HEADER_SIZE
                and _valid_amsdos_header(region[:AMSDOS_HEADER_SIZE], f.name)):
            length = (region[LEN24_OFFSET]
                      | (region[LEN24_OFFSET + 1] << 8)
                      | (region[LEN24_OFFSET + 2] << 16))
            return region[AMSDOS_HEADER_SIZE:AMSDOS_HEADER_SIZE + length]
        a = self._amsdos_by_name(f.name, near_lin=lin, near_span=f.length)
        if a is not None:
            lin_a = self._helper._image_to_linear(a.offset)
            return self._helper._read_linear(
                lin_a + AMSDOS_HEADER_SIZE, a.length)
        return region

    # ------------------------------------------------------------------ #
    # Frontières d'allocation (adaptées CP/M)
    # ------------------------------------------------------------------ #
    def _dir_field_present(self, field11: str) -> bool:
        """Vrai si le champ 8.3 existe déjà dans le répertoire CP/M."""
        target = field11.encode("latin1")
        raw = self._dir_raw()
        for slot in range(CPM_DIR_MAX_ENTRIES):
            e = raw[slot * DIR_ENTRY_SIZE:(slot + 1) * DIR_ENTRY_SIZE]
            if self._entry_live(e) and self._field(e).rstrip() == target:
                return True
        return False

    def _amsdos_frontier(self) -> int:
        """Linéaire de fin de la pile d'objets AMSDOS (croissance
        descendante depuis la fin du disque) — borne basse : fin du paquet
        CP/M (et non du paquet Filer, absent sur ce type de disque)."""
        frontier = CPM_CAPACITY
        pack_end = self._pack_end()
        for a in self._helper._scan_amsdos():
            start = self._helper._image_to_linear(a.offset)
            if start >= pack_end and start < frontier:
                frontier = start
        return frontier

    # ------------------------------------------------------------------ #
    # Écriture / suppression
    # ------------------------------------------------------------------ #
    def write_file(self, name: str, data: bytes,
                   file_type: int = FT_BINARY,
                   load_addr: int = 0x4000,
                   exec_addr: int = 0,
                   mode: str = "cpm") -> CpcFile:
        """Écrit un fichier sur la disquette CP/M.

        ``mode`` :

        - ``"cpm"`` (défaut) : fichier du **répertoire CP/M** — en-tête
          AMSDOS de 128 o + données, empilés en fin de paquet, plus les
          entrées du répertoire (chunks de 16 Ko, compteur d'allocation
          continué après le maximum existant). Lisible par le vrai BDOS
          (Gotek sur matériel réel) **et** par les balayages AMSDOS des
          émulateurs (l'en-tête est retiré à la lecture).
        - ``"amsdos"`` : objet AMSDOS seulement (en-tête + données, empilés
          depuis la fin du disque), sans entrée de répertoire — visible
          uniquement des émulateurs.

        ``file_type``/``load_addr``/``exec_addr`` remplissent l'en-tête
        AMSDOS (ignorés à la lecture par le BDOS, qui ne voit que le
        répertoire et les données).
        """
        if mode not in ("cpm", "amsdos"):
            raise CpcError(f"Mode inconnu: {mode!r} (cpm|amsdos).")
        if not data:
            raise CpcError("Fichier vide: rien à écrire.")
        field11 = _cpm_field11(name)
        display = _dir_field_to_name(field11.encode("latin1"))

        if mode == "amsdos":
            need = AMSDOS_HEADER_SIZE + len(data)
            end_front = self._amsdos_frontier()
            if end_front - need < CPM_PACK_START:
                raise CpcError(
                    "Pas assez d'espace libre pour l'objet AMSDOS.")
            dest = end_front - need
            if not self._helper._linear_region_free(dest, need):
                raise CpcError(
                    "Espace de destination AMSDOS occupé par des données "
                    "inattendues (disque partiellement utilisé d'une façon "
                    "inconnue).")
            hdr = _build_amsdos_header(field11, file_type, load_addr,
                                       len(data), exec_addr)
            self._helper._write_linear(dest, hdr + data)
            return CpcFile(
                name=display,
                offset=self._helper._linear_to_image(dest),
                file_type=file_type,
                load_addr=load_addr,
                exec_addr=exec_addr,
                length=len(data),
                source="AMSDOS",
            )

        # mode "cpm" : région allouée = en-tête AMSDOS + données, arrondie
        # au 128 o, en fin de paquet.
        if self._dir_field_present(field11):
            raise CpcError(f"Fichier déjà présent (répertoire CP/M): {name!r}")
        total_bytes = ((len(data) + AMSDOS_HEADER_SIZE
                        + DIR_UNIT_SIZE - 1) // DIR_UNIT_SIZE) * DIR_UNIT_SIZE
        pack_end = self._pack_end()
        if pack_end + total_bytes > CPM_CAPACITY:
            raise CpcError("Pas assez d'espace libre sur la disquette.")
        if not self._helper._linear_region_free(pack_end, total_bytes):
            raise CpcError(
                "Espace du paquet CP/M occupé par des données inattendues "
                "(disque partiellement utilisé d'une façon inconnue).")

        # Chunks (16 Ko max par entrée de répertoire).
        chunks: List[int] = []
        rest = total_bytes
        while rest > 0:
            c = min(rest, DIR_MAX_CHUNK_BYTES)
            chunks.append(c // DIR_UNIT_SIZE)
            rest -= c
        raw = self._dir_raw()
        free_slots = [
            s for s in range(CPM_DIR_MAX_ENTRIES)
            if not self._entry_live(
                raw[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE])
        ]
        slot = _first_free_run(free_slots, len(chunks))
        if slot is None:
            raise CpcError(
                "Répertoire CP/M plein (48 entrées max, chunks inclus).")

        # Compteur d'allocation continué après le maximum existant
        # (valeurs consécutives, comme sur les disques réels).
        live = [
            raw[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE]
            for s in range(CPM_DIR_MAX_ENTRIES)
            if self._entry_live(
                raw[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE])
        ]
        counter = max((max(e[0x10:0x10 + 16]) for e in live), default=1) + 1
        entries = bytearray()
        for k, units in enumerate(chunks):
            e = bytearray(DIR_ENTRY_SIZE)
            e[1:12] = field11.encode("latin1")
            e[0x0C] = k
            e[0x0F] = units
            ktail = (units * DIR_UNIT_SIZE + 1023) // 1024
            for b in range(ktail):
                e[0x10 + b] = counter
                counter += 1
            entries += e

        # 1) Entrées du répertoire (les autres restent inchangées).
        dirbuf = bytearray(raw)
        dirbuf[slot * DIR_ENTRY_SIZE:
               (slot + len(chunks)) * DIR_ENTRY_SIZE] = entries
        self._helper._write_linear(CPM_DIR_OFFSET, bytes(dirbuf))

        # 2) Données : en-tête AMSDOS + fichier + remplissage 0xE5.
        hdr = _build_amsdos_header(field11, file_type, load_addr,
                                   len(data), exec_addr)
        padded = data + b"\xE5" * (total_bytes - AMSDOS_HEADER_SIZE - len(data))
        self._helper._write_linear(pack_end, hdr + padded)

        return CpcFile(
            name=display,
            offset=self._helper._linear_to_image(pack_end),
            file_type=file_type,
            load_addr=load_addr,
            exec_addr=exec_addr,
            length=len(data),
            source="CPM",
        )

    def _zero_amsdos(self, f: CpcFile) -> None:
        """Mettre un objet AMSDOS (en-tête + données) à zéro."""
        lin = self._helper._image_to_linear(f.offset)
        self._helper._write_linear(
            lin, b"\x00" * (AMSDOS_HEADER_SIZE + f.length))

    def delete_file(self, name: str) -> None:
        """Supprime un fichier (des couches où il existe).

        Fichier du répertoire CP/M : région allouée remplie 0xE5 + entrées
        du répertoire remplies 0xE5 — **sans recollage** du paquet (le CP/M
        2.2 tolère les trous ; les données des fichiers suivants restent en
        place) — plus, pour les fichiers « legacy » des disques réels,
        tous les objets AMSDOS portant ce nom (contenu réel, éventuellement
        inséré dans/autour de l'allocation) sont mis à zéro.
        Objet AMSDOS sans entrée de répertoire : mis à zéro.
        """
        field11 = _cpm_field11(name)
        raw = self._dir_raw()
        target = field11.encode("latin1")
        hits = [
            s for s in range(CPM_DIR_MAX_ENTRIES)
            if self._entry_live(
                raw[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE])
            and self._field(
                raw[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE]
            ).rstrip() == target
        ]
        if not hits:
            f = self.find(field11, source="amsdos")
            if f is None:
                raise CpcError(f"Fichier introuvable: {name!r}")
            self._zero_amsdos(f)
            return

        _, slot_of = self._files_with_slots()
        first = slot_of[hits[0]]
        # Objets AMSDOS correspondants (capturés avant que le remplissage
        # 0xE5 ne détruise les en-têtes éventuellement insérés dans la
        # région).
        objs = [
            a for a in self._helper._scan_amsdos()
            if self._amsdos_matches_name(a.name, first.name)
        ]
        lin = self._helper._image_to_linear(first.offset)
        self._helper._write_linear(lin, b"\xE5" * first.length)
        for a in objs:
            self._zero_amsdos(a)

        dirbuf = bytearray(raw)
        for s in hits:
            dirbuf[s * DIR_ENTRY_SIZE:(s + 1) * DIR_ENTRY_SIZE] = CPM_DIR_EMPTY_E5
        self._helper._write_linear(CPM_DIR_OFFSET, bytes(dirbuf))
