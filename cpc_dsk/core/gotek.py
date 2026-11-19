"""Génération de contenu pour clé USB **Gotek** (Amstrad CPC 6128).

Le Gotek est un émulateur de lecteur floppy qui lit les images de disquette
depuis une clé USB. Pour le CPC, les firmwares « CPC mode » servent des images
**ADF** stockées sur la clé (clé formatée FAT16/FAT32).

Ce module fournit les briques fiables et indépendantes de l'environnement :

    - valider une image ADF,
    - écrire une ou plusieurs disquettes ADF dans un répertoire (le contenu à
      copier sur la clé USB),
    - lister / vérifier le contenu d'un tel répertoire,
    - créer une *image FAT16 complète* (fichier ``.img`` prêt à flasher sur
      la clé) via :func:`create_fat_image` — rédacteur FAT16 **intégré,
      sans aucune dépendance** (fonctionne sous Windows, Linux et dans
      l'exécutable PyInstaller),
    - lire le contenu d'une image FAT16 existante via
      :func:`list_fat_image` (noms + données des fichiers de la racine).

NOTE DE VALIDATION
==================
Le nommage / l'arborescence attendus par le firmware Gotek précis (racine,
dossier ``cpc/``, préfixe ``DISK``…) varient selon le build. Les fonctions
ci-dessous sont paramétrables (``pattern``) pour s'adapter à ton firmware.
"""

from __future__ import annotations

import os
import shutil
import struct
import time
from dataclasses import dataclass, field
from typing import List, Sequence

from cpc_dsk.core.adf import ADFDisk, ADFError

# Nom de fichier par défaut pour les disquettes sur la clé.
DEFAULT_NAME_PATTERN = "DISK%03d.adf"


class GotekError(Exception):
    """Erreur lors de la préparation du contenu Gotek."""


@dataclass
class GotekConfig:
    """Paramètres de génération du contenu Gotek.

    Attributes:
        name_pattern: Patron de nommage des fichiers ADF (``%d`` = index).
        subfolder: Sous-dossier cible (``""`` = racine de la clé).
        start_index: Index de départ pour la numérotation.
    """
    name_pattern: str = DEFAULT_NAME_PATTERN
    subfolder: str = ""
    start_index: int = 1
    extra: dict = field(default_factory=dict)


def validate_adf(path: str) -> ADFDisk:
    """Charge et valide une image ADF ; lève :class:`GotekError` si invalide."""
    try:
        return ADFDisk.load(path)
    except (OSError, ADFError) as exc:
        raise GotekError(f"Image ADF invalide ou illisible: {path} — {exc}") from exc


def _target_path(output_dir: str, config: GotekConfig, index: int) -> str:
    name = config.name_pattern % index
    base = os.path.join(output_dir, config.subfolder) if config.subfolder else output_dir
    return os.path.join(base, name)


def prepare_usb_directory(
    output_dir: str,
    sources: Sequence,
    config: GotekConfig | None = None,
) -> List[str]:
    """Écrit les disquettes ADF dans ``output_dir`` (contenu à copier sur la clé).

    ``sources`` est une séquence de chemins vers des fichiers ``.adf``/``.dsk``
    **ou** d'objets :class:`ADFDisk`. Chaque disquette est écrite avec un nom
    séquentiel défini par :class:`GotekConfig`.

    Renvoie la liste des chemins de fichiers créés.
    """
    config = config or GotekConfig()
    os.makedirs(output_dir, exist_ok=True)

    created: List[str] = []
    for i, source in enumerate(sources):
        target = _target_path(output_dir, config, config.start_index + i)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if isinstance(source, ADFDisk):
            source.save(target)
        elif isinstance(source, str):
            validate_adf(source)          # vérifie avant de copier
            shutil.copyfile(source, target)
        else:
            raise GotekError(
                f"Source non supportée: {source!r} "
                "(attendu un chemin .adf ou un objet ADFDisk).")
        created.append(target)
    return created


def list_usb_directory(folder: str) -> List[str]:
    """Liste les images ADF présentes dans un répertoire (recursif)."""
    found: List[str] = []
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            if name.lower().endswith((".adf", ".dsk")):
                found.append(os.path.join(root, name))
    return found


def verify_usb_directory(folder: str) -> List[str]:
    """Vérifie que toutes les images ADF d'un répertoire sont valides.

    Renvoie la liste des fichiers valides ; lève :class:`GotekError` au premier
    fichier invalide.
    """
    valid: List[str] = []
    for path in list_usb_directory(folder):
        validate_adf(path)
        valid.append(path)
    return valid


def create_fat_image(
    output_img: str,
    sources: Sequence,
    config: GotekConfig | None = None,
    size_mb: int = 32,
    fat_type: int = 16,
) -> str:
    """Crée une image FAT16 ``.img`` contenant les disquettes ADF.

    Le rédacteur FAT16 **intégré** (aucune dépendance externe — fonctionne
    sous Windows, Linux et dans l'exécutable PyInstaller) produit un volume
    byte-par-byte compatible avec ``mkfs.fat`` 4.2 (vérifié avec fsck.fat et
    libblkid) : fichiers à la racine, 512 o/secteur, 1 secteur/cluster.

    Args:
        output_img: Chemin de l'image ``.img`` à produire.
        sources: Chemins ``.adf`` ou objets :class:`ADFDisk`.
        config: Configuration de nommage (les fichiers vont à la racine,
            comme l'attendent la plupart des firmwares Gotek).
        size_mb: Taille de l'image en Mo (4 à ~32 pour du FAT16 avec cette
            géométrie).
        fat_type: ignoré (le rédacteur intégré produit de la FAT16, le
            format classique des clés Gotek).
    """
    config = config or GotekConfig()
    return _write_fat16_image(output_img, _collect_ades(sources, config),
                              size_mb * 1024 * 1024, volume_label="CPC-GOTEK")


@dataclass
class FatFile:
    """Fichier lu dans une image FAT16 (contenu d'une clé Gotek)."""
    name: str
    size: int
    data: bytes


def list_fat_image(path: str) -> List[FatFile]:
    """Lit une image FAT16 ou FAT32 (``.img`` de clé Gotek) et renvoie ses
    fichiers.

    Analyse le secteur d'amorçage (BPB), la table FAT et le répertoire
    racine (région fixe pour FAT16, chaîne de clusters pour FAT32), puis
    reconstitue chaque fichier en suivant sa chaîne de clusters. Les
    entrées « volume ID », supprimées (0xE5), les dossiers et les entrées
    LFN sont ignorées.

    Renvoie la liste des :class:`FatFile` de la racine (noms au format
    ``BASE.EXT``). Lève :class:`GotekError` si le fichier n'est pas une
    image FAT lisible : FAT16 (le rédacteur intégré produit de la FAT16,
    ~32 Mo) et FAT32 (clés USB réelles de plus de 32 Mo, images ``dd``)
    sont supportés ; FAT12 ne l'est pas.
    """
    with open(path, "rb") as fh:
        img = fh.read()
    if len(img) < 2 * 512 or img[510:512] != b"\x55\xaa":
        raise GotekError(
            "Pas une image FAT (secteur d'amorçage absent) — attends un "
            ".img produit par cet outil ou par mkfs.fat.")

    bps = struct.unpack_from("<H", img, 0x0B)[0]
    spc = img[0x0D]
    reserved = struct.unpack_from("<H", img, 0x0E)[0]
    nfats = img[0x10]
    rootent = struct.unpack_from("<H", img, 0x11)[0]
    fatsz16 = struct.unpack_from("<H", img, 0x16)[0]
    fatsz32 = struct.unpack_from("<I", img, 0x24)[0]
    if not bps or not spc or not reserved or not 1 <= nfats <= 4:
        raise GotekError("BPB incohérent : ce fichier n'est pas une image FAT.")

    fat32 = fatsz16 == 0
    if fat32:
        if not fatsz32:
            raise GotekError(
                "BPB incohérent : ce fichier n'est pas une image FAT.")
    elif not rootent:
        raise GotekError("BPB incohérent : ce fichier n'est pas une image FAT.")

    fat_off = reserved * bps
    fat_size = (fatsz32 if fat32 else fatsz16) * bps
    if fat_off + nfats * fat_size > len(img):
        raise GotekError("Image tronquée : les tables FAT dépassent le fichier.")
    fat = img[fat_off:fat_off + fat_size]

    if not fat32:
        # Règle Microsoft : moins de 4085 clusters de données = FAT12
        # (la taille de la table FAT seule ne suffit pas à trancher).
        data_start_cls = (fat_off + nfats * fat_size) // bps + \
            (rootent * 32 + bps - 1) // bps
        n_data_clusters = (len(img) // bps - data_start_cls) // spc
        if n_data_clusters < 4085:
            raise GotekError(
                "Image FAT12 non supportée : cet outil lit les images "
                "FAT16 et FAT32.")

    eoc = 0x0FFFFFFF if fat32 else 0xFFF8

    def fat_entry(c: int) -> int:
        if fat32:
            return struct.unpack_from("<I", fat, 4 * c)[0] & 0x0FFFFFFF
        return struct.unpack_from("<H", fat, 2 * c)[0]

    data_start_sec = (fat_off + nfats * fat_size) // bps
    if not fat32:
        data_start_sec += (rootent * 32 + bps - 1) // bps
    n_entries = len(fat) // (4 if fat32 else 2)

    def read_chain(first: int, size: int) -> bytes:
        if size == 0:
            return b""
        if not (2 <= first < eoc) or first >= n_entries:
            return b"\x00" * size  # entrée corrompue : données inconnues
        out = bytearray()
        c = first
        for _ in range(100000):  # garde contre une chaîne cyclique
            if not (2 <= c < eoc) or c >= n_entries:
                break
            off = (data_start_sec + (c - 2) * spc) * bps
            if off + bps > len(img):
                break
            out += img[off:off + bps]
            if len(out) >= size:
                break
            c = fat_entry(c)
        return bytes(out[:size])

    # Répertoire racine : région fixe (FAT16) ou chaîne de clusters (FAT32).
    if fat32:
        root_cluster = struct.unpack_from("<I", img, 0x2C)[0]
        bound = max(0, len(img) - data_start_sec * bps)
        root_data = read_chain(root_cluster, bound)
    else:
        root_off = fat_off + nfats * fat_size
        root_bytes = rootent * 32
        if root_off + root_bytes > len(img):
            raise GotekError("Image tronquée : le répertoire racine dépasse le "
                             "fichier.")
        root_data = img[root_off:root_off + root_bytes]

    files: List[FatFile] = []
    for i in range(len(root_data) // 32):
        ent = root_data[32 * i:32 * (i + 1)]
        if ent[0] in (0x00, 0xE5):
            continue
        attr = ent[11]
        if attr & (0x08 | 0x10) or attr == 0x0F:
            continue  # volume ID, dossier ou entrée LFN
        base = ent[0:8].decode("latin1").strip()
        ext = ent[8:11].decode("latin1").strip()
        name = f"{base}.{ext}" if ext else base
        if not name:
            continue
        size = struct.unpack_from("<I", ent, 28)[0]
        if fat32:
            # Cluster de départ FAT32 : mot fort en 20, mot faible en 26
            # (les octets 22-25 sont l'heure/date de modification).
            first = ((struct.unpack_from("<H", ent, 20)[0] << 16) |
                     struct.unpack_from("<H", ent, 26)[0]) & 0x0FFFFFFF
        else:
            first = struct.unpack_from("<H", ent, 26)[0]
        files.append(FatFile(name=name, size=size,
                             data=read_chain(first, size)))
    return files


def _collect_ades(
    sources: Sequence,
    config: GotekConfig,
) -> List[tuple]:
    """Charge les sources et renvoie ``[(nom, données), …]``."""
    files: List[tuple] = []
    for i, source in enumerate(sources):
        name = (config.name_pattern % (config.start_index + i)).upper()
        if isinstance(source, ADFDisk):
            data = bytes(source._raw)
        elif isinstance(source, str):
            validate_adf(source)
            with open(source, "rb") as fh:
                data = fh.read()
        else:
            raise GotekError(
                f"Source non supportée: {source!r} "
                "(attendu un chemin .adf ou un objet ADFDisk).")
        files.append((name, data))
    return files


# --------------------------------------------------------------------------- #
# Rédacteur FAT16 minimal (aucune dépendance)
# --------------------------------------------------------------------------- #

# Queue du secteur d'amorçage (offsets 0x3E..0x1FF) : code de boot, message
# et signature 0x55AA — copie byte-par-byte du secteur produit par mkfs.fat
# 4.2 (identique sur des volumes de 4 à 32 Mo).
_BOOT_TAIL: bytes = (
    b"\x0e\x1f\xbe\x5b\x7c\xac\x22\xc0\x74\x0b\x56\xb4"
    b"\x0e\xbb\x07\x00\xcd\x10\x5e\xeb\xf0\x32\xe4\xcd"
    b"\x16\xcd\x19\xeb\xfe\x54\x68\x69\x73\x20\x69\x73"
    b"\x20\x6e\x6f\x74\x20\x61\x20\x62\x6f\x6f\x74\x61"
    b"\x62\x6c\x65\x20\x64\x69\x73\x6b\x2e\x20\x20\x50"
    b"\x6c\x65\x61\x73\x65\x20\x69\x6e\x73\x65\x72\x74"
    b"\x20\x61\x20\x62\x6f\x6f\x74\x61\x62\x6c\x65\x20"
    b"\x66\x6c\x6f\x70\x70\x79\x20\x61\x6e\x64\x0d\x0a"
    b"\x70\x72\x65\x73\x73\x20\x61\x6e\x79\x20\x6b\x65"
    b"\x79\x20\x74\x6f\x20\x74\x72\x79\x20\x61\x67\x61"
    b"\x69\x6e\x20\x2e\x2e\x2e\x20\x0d\x0a\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x55\xaa"
)

def _write_fat16_image(
    output_img: str,
    files: Sequence[tuple],
    size_bytes: int,
    volume_label: str = "CPC-GOTEK",
) -> str:
    """Écrit une image FAT16 de ``size_bytes`` contenant ``files``.

    ``files`` : séquence de ``(NOM, données)`` ; le nom est tronqué au format
    8.3 (majuscules). Les fichiers sont posés à la racine, en clusters
    contigus (1 secteur/cluster, secteurs de 512 o) — disposition lue par
    tous les firmwares FAT.
    """
    sec = 512
    total = size_bytes // sec
    if total < 1024:
        raise GotekError("Image trop petite pour du FAT16 (< 512 Ko).")

    # Taille de la table FAT : plus petit K valide — même résultat que
    # mkfs.fat 4.2 (K = 32/64/127/254 secteurs pour 4/8/16/32 Mo).
    root_sectors = (512 * 32 + 511) // 512  # 512 entrées racine × 32 o = 32 o

    def _fat_need(kk: int) -> int:
        entries = total - (1 + 2 * kk + root_sectors) + 2  # +2 : entrées 0/1
        return (2 * entries + sec - 1) // sec

    k = 1
    while _fat_need(k) > k:
        k = _fat_need(k)
    while k > 1 and _fat_need(k - 1) <= k - 1:
        k -= 1
    data_start = 1 + 2 * k + root_sectors
    if total - data_start > 65526:
        # Clusters valides FAT16 : 2..0xFFF7 = 65526 (1 secteur/cluster).
        raise GotekError(
            "Image trop grande pour du FAT16 (max ≈ 32 Mo) : réduis size_mb.")

    img = bytearray(size_bytes)

    # --- Allocation : clusters contigus, chaînés dans la table FAT. ---
    # La région FAT fait k secteurs = k × 512 o = k × 256 entrées 16 o.
    fat1 = bytearray(k * sec)
    struct.pack_into("<H", fat1, 0, 0xFFF8)     # entrée 0 (réserve, FAT16)
    struct.pack_into("<H", fat1, 2, 0xFFFF)     # entrée 1
    struct.pack_into("<H", fat1, 4, 0xFFFF)     # cluster 2 (premier)

    def _set_eoc(cluster: int) -> None:
        struct.pack_into("<H", fat1, 2 * cluster, 0xFFFF)

    def _chain(cluster: int, next_cluster: int) -> None:
        struct.pack_into("<H", fat1, 2 * cluster, next_cluster)

    def _alloc(first: int, count: int) -> None:
        if count == 1:
            _set_eoc(first)
        else:
            for c in range(first, first + count - 1):
                _chain(c, c + 1)
            _set_eoc(first + count - 1)

    now = time.localtime()
    mdate = ((now.tm_year - 1980) << 9) | now.tm_mon
    mtime = ((now.tm_hour & 7) << 11) | (now.tm_min << 5) | (now.tm_sec // 2)

    root = bytearray(512 * 32)

    # Entrée VOLUME ID (libellé) en tête du répertoire racine, comme
    # mkfs.fat : sans elle, fsck.fat considère le label du BPB comme orphelin.
    lent = bytearray(32)
    lent[0:11] = volume_label.upper()[:11].ljust(11).encode("latin1")
    lent[11] = 0x08  # attribut « volume ID »
    root[0:32] = lent

    next_cluster = 2
    for idx, (name, data) in enumerate(files):
        n = max(1, (len(data) + sec - 1) // sec)
        first = next_cluster
        if first + n > total - data_start + 2:
            raise GotekError(
                f"Image saturée pour {name!r} (agrandis size_mb).")
        _alloc(first, n)
        next_cluster += n

        # Entrée de répertoire racine (8.3, majuscules, sans espace).
        base, ext = _to_83(name)
        ent = bytearray(32)
        ent[0:11] = (base + ext).encode("latin1")
        ent[11] = 0x20  # attribut « archive »
        # Décalages de l'entrée 32 o (communs à FAT12/16/32).
        struct.pack_into("<H", ent, 22, mtime)    # heure de modification
        struct.pack_into("<H", ent, 24, mdate)    # date de modification
        struct.pack_into("<H", ent, 26, first)    # cluster premier (16 o)
        struct.pack_into("<I", ent, 28, len(data))  # taille du fichier
        root[32 * (idx + 1):32 * (idx + 2)] = ent

        # Données, cluster par cluster (512 o ; le dernier est tronqué).
        off = (first - 2) * sec
        for i in range(n):
            chunk = data[i * sec:(i + 1) * sec]
            img[sec * (data_start + off // sec) + off % sec:
                sec * (data_start + off // sec) + off % sec + len(chunk)] = chunk
            off += sec

    # --- Tableaux (FAT1 + copie FAT2, répertoire racine). ---
    img[sec:sec + len(fat1)] = fat1
    img[sec * (1 + k):sec * (1 + k) + len(fat1)] = fat1
    img[sec * (1 + 2 * k):sec * (1 + 2 * k) + len(root)] = root

    # --- Secteur d'amorçage (BPB) FAT16 — disposition « compacte » de
    #     dosfstools, reproduite byte-par-byte d'une référence mkfs.fat 4.2
    #     (vérifiée sur 4/8/16/32 Mo) : c'est elle, et non la variante
    #     « extended BPB » du manuel Microsoft, que fsck.fat 4.2 et libblkid
    #     reconnaissent (signature 0x29 @ 0x26, libellé @ 0x2B, 0x55AA @ 0x1FE).
    img[0:3] = b"\xeb\x3c\x90"                      # jmp court + nop
    img[3:11] = b"GOTEK   "                         # OEM
    struct.pack_into("<H", img, 0x0B, sec)          # octets par secteur
    img[0x0D] = 1                                   # secteurs par cluster
    struct.pack_into("<H", img, 0x0E, 1)            # secteurs réservés
    img[0x10] = 2                                   # nombre de tables FAT
    struct.pack_into("<H", img, 0x11, 512)          # entrées répertoire racine
    if total - 8 <= 0xFFFF:
        struct.pack_into("<H", img, 0x13, total - 8)  # total (convention dosfstools)
        struct.pack_into("<I", img, 0x20, 0)
    else:
        struct.pack_into("<H", img, 0x13, 0)
        struct.pack_into("<I", img, 0x20, total - 8)  # total 32 o
    img[0x15] = 0xF8                                # descripteur de média
    struct.pack_into("<H", img, 0x16, k)            # taille FAT (secteurs)
    struct.pack_into("<H", img, 0x18, 63)           # secteurs/piste (BIOS)
    struct.pack_into("<H", img, 0x1A, 255)          # têtes (BIOS)
    struct.pack_into("<I", img, 0x1C, 0)            # secteurs cachés
    struct.pack_into("<I", img, 0x24, 0x80)         # constante de mkfs.fat (jamais lue si fatsz16 ≠ 0)
    img[0x26] = 0x29                                # signature d'amorçage
    struct.pack_into("<I", img, 0x27, 0x43504331)   # ID de volume (« CPC1 »)
    img[0x2B:0x36] = volume_label.upper()[:11].ljust(11).encode("latin1")
    img[0x36:0x3E] = b"FAT16   "
    img[0x3E:0x200] = _BOOT_TAIL                    # code + message + 0x55AA

    with open(output_img, "wb") as fh:
        fh.write(img)
    return output_img


def _to_83(name: str) -> tuple:
    """Nom 8.3 (majuscules) : (base 8, ext 3) complétés d'espaces."""
    name = name.upper().replace(" ", "")
    base, dot, ext = name.partition(".")
    return base[:8].ljust(8), ext[:3].ljust(3)
