"""Rédacteur FAT32 minimal, **sans aucune dépendance** (fonctionne sous
Windows, Linux et dans l'exécutable PyInstaller).

Produit une image ``.img`` « superfloppy » (pas de MBR ni de table de
partitions : le secteur 0 est le secteur d'amorçage FAT32), même
disposition que le rédacteur FAT16 de :mod:`cpc_dsk.core.gotek` et que
``mkfs.fat -F 32`` sur un fichier :

    secteur 0        secteur d'amorçage (BPB FAT32)
    secteur 1        FSInfo (nombre de clusters libres, prochain libre)
    secteur 6 / 7    copies de secours du secteur d'amorçage / FSInfo
    32 secteurs      réservés au total (valeur de mkfs.fat)
    FAT1, FAT2       deux tables FAT 32 bits
    données          cluster 2 = répertoire racine (chaîne de clusters),
                     puis les fichiers en clusters contigus

Secteurs de 512 o ; taille de cluster selon la table de Microsoft
(format Windows) : 512 o jusqu'à 260 Mo, 4 Ko jusqu'à 8 Go, 8 Ko jusqu'à
16 Go, 16 Ko jusqu'à 32 Go. Le volume compte toujours au moins 65 525
clusters (sinon ce n'est pas du FAT32 au sens de la spécification) :
d'où une taille minimale de 33 Mo. Taille maximale : 32 Go
(limite du formatage FAT32 de Windows).

Noms 8.3 uniquement (pas d'entrées LFN), entrée « nom de volume » en tête
de la racine. Vérifié avec ``fsck.fat -n`` et relu par
:func:`cpc_dsk.core.gotek.list_fat_image`.
"""

from __future__ import annotations

import struct
import time
from typing import List, Sequence, Tuple

SECTOR = 512
RESERVED = 32
NFATS = 2
MIN_CLUSTERS = 65525          # en dessous : FAT16 (spécification Microsoft)
MAX_CLUSTERS = 0x0FFFFFF5     # clusters valides : 2..0x0FFFFFF6
MAX_SIZE_MB = 32 * 1024       # 32 Go : limite du formatage FAT32 de Windows
EOC = 0x0FFFFFF8              # fin de chaîne (valeur écrite par mkfs.fat)


class Fat32Error(Exception):
    """Image FAT32 impossible (taille hors limites, image saturée…)."""


def sectors_per_cluster(size_bytes: int) -> int:
    """Taille de cluster (en secteurs de 512 o) — table Microsoft."""
    mb = size_bytes / (1024 * 1024)
    if mb <= 260:
        return 1
    if mb <= 8 * 1024:
        return 8
    if mb <= 16 * 1024:
        return 16
    return 32


def _compute(size_bytes: int):
    """``(total, spc, taille_fat, nb_clusters)`` ou ``None`` si la taille ne
    donne pas un volume FAT32 valide."""
    if size_bytes > MAX_SIZE_MB * 1024 * 1024:
        return None
    total = size_bytes // SECTOR
    spc = sectors_per_cluster(size_bytes)
    # Taille de FAT : plus petite valeur K telle que la table couvre tous
    # les clusters de données restants (point fixe).
    def need(k: int) -> int:
        clusters = max(0, (total - RESERVED - NFATS * k) // spc)
        return ((clusters + 2) * 4 + SECTOR - 1) // SECTOR

    fatsz = 1
    while need(fatsz) > fatsz:
        fatsz = need(fatsz)
    while fatsz > 1 and need(fatsz - 1) <= fatsz - 1:
        fatsz -= 1
    clusters = max(0, (total - RESERVED - NFATS * fatsz) // spc)
    if not MIN_CLUSTERS <= clusters <= MAX_CLUSTERS:
        return None
    return total, spc, fatsz, clusters


def min_size_mb() -> int:
    """Plus petite taille (Mo entiers) acceptée par :func:`write_fat32_image`."""
    mb = 1
    while _compute(mb * 1024 * 1024) is None:
        mb += 1
    return mb


def _geometry(size_bytes: int) -> Tuple[int, int, int, int]:
    """Renvoie ``(total_secteurs, secteurs_par_cluster, taille_fat,
    nb_clusters)`` ; lève :class:`Fat32Error` si la taille ne convient pas."""
    if size_bytes > MAX_SIZE_MB * 1024 * 1024:
        raise Fat32Error(
            f"Image trop grande pour du FAT32 (max {MAX_SIZE_MB // 1024} Go).")
    geo = _compute(size_bytes)
    if geo is None:
        raise Fat32Error(
            f"Image trop petite pour du FAT32 (minimum {min_size_mb()} Mo).")
    return geo


# Code d'amorçage + message (offsets 0x5A..0x1FD), copie de celui de
# mkfs.fat 4.2 en FAT32 (le message est en 0x7C77 une fois chargé).
_BOOT_CODE: bytes = (
    b"\x0e\x1f\xbe\x77\x7c\xac\x22\xc0\x74\x0b\x56\xb4\x0e\xbb\x07\x00"
    b"\xcd\x10\x5e\xeb\xf0\x32\xe4\xcd\x16\xcd\x19\xeb\xfe"
    b"This is not a bootable disk.  Please insert a bootable floppy and"
    b"\r\npress any key to try again ... \r\n"
)


def _to_83(name: str) -> bytes:
    """``BASE.EXT`` -> 11 octets (base 8 + ext 3, majuscules, espaces)."""
    name = name.upper()
    base, _dot, ext = name.partition(".")
    return (base[:8].ljust(8) + ext[:3].ljust(3)).encode("latin1")


def write_fat32_image(
    output_img: str,
    files: Sequence[Tuple[str, bytes]],
    size_bytes: int,
    volume_label: str = "CPC-HXC",
    volume_id: int | None = None,
) -> str:
    """Écrit une image FAT32 de ``size_bytes`` contenant ``files``
    (séquence de ``(NOM 8.3, données)``) à la racine.

    L'image est écrite par morceaux (seuls les secteurs utiles sont
    écrits ; le reste est étendu à zéro par le système de fichiers hôte).
    """
    total, spc, fatsz, nclusters = _geometry(size_bytes)
    csize = spc * SECTOR
    data_start = RESERVED + NFATS * fatsz          # premier secteur de données

    names = [n.upper() for n, _ in files]
    if len(set(names)) != len(names):
        raise Fat32Error("Noms de fichiers en double dans l'image.")

    # --- Allocation : racine au cluster 2, puis fichiers contigus. ---
    n_entries = 1 + len(files)                     # libellé + fichiers
    root_clusters = max(1, (n_entries * 32 + csize - 1) // csize)
    fat = bytearray(4 * (nclusters + 2))
    struct.pack_into("<I", fat, 0, 0x0FFFFFF8)     # entrée 0 (média F8)
    struct.pack_into("<I", fat, 4, 0x0FFFFFFF)     # entrée 1

    def alloc(first: int, count: int) -> None:
        for c in range(first, first + count - 1):
            struct.pack_into("<I", fat, 4 * c, c + 1)
        struct.pack_into("<I", fat, 4 * (first + count - 1), EOC)

    alloc(2, root_clusters)
    nxt = 2 + root_clusters
    placed: List[Tuple[str, bytes, int]] = []
    for name, data in files:
        n = (len(data) + csize - 1) // csize
        if n == 0:
            placed.append((name, data, 0))         # fichier vide : cluster 0
            continue
        if nxt + n > nclusters + 2:
            raise Fat32Error(
                f"Image saturée pour {name!r} : augmente la taille.")
        alloc(nxt, n)
        placed.append((name, data, nxt))
        nxt += n
    used = nxt - 2
    free = nclusters - used
    next_free = nxt if nxt < nclusters + 2 else 0xFFFFFFFF

    # --- Répertoire racine ---
    now = time.localtime()
    mdate = ((now.tm_year - 1980) << 9) | (now.tm_mon << 5) | now.tm_mday
    mtime = (now.tm_hour << 11) | (now.tm_min << 5) | (now.tm_sec // 2)
    root = bytearray(root_clusters * csize)
    label = volume_label.upper()[:11].ljust(11).encode("latin1")
    root[0:11] = label
    root[11] = 0x08                                # attribut « volume ID »
    struct.pack_into("<H", root, 22, mtime)
    struct.pack_into("<H", root, 24, mdate)
    for i, (name, data, first) in enumerate(placed, start=1):
        ent = bytearray(32)
        ent[0:11] = _to_83(name)
        ent[11] = 0x20                             # attribut « archive »
        struct.pack_into("<H", ent, 14, mtime)     # création
        struct.pack_into("<H", ent, 16, mdate)
        struct.pack_into("<H", ent, 18, mdate)     # dernier accès
        struct.pack_into("<H", ent, 20, first >> 16)
        struct.pack_into("<H", ent, 22, mtime)     # modification
        struct.pack_into("<H", ent, 24, mdate)
        struct.pack_into("<H", ent, 26, first & 0xFFFF)
        struct.pack_into("<I", ent, 28, len(data))
        root[32 * i:32 * (i + 1)] = ent

    # --- Secteur d'amorçage FAT32 ---
    if volume_id is None:
        volume_id = int(time.time()) & 0xFFFFFFFF
    boot = bytearray(SECTOR)
    boot[0:3] = b"\xeb\x58\x90"                    # jmp court + nop
    boot[3:11] = b"CPC-DISK"                       # OEM
    struct.pack_into("<H", boot, 0x0B, SECTOR)
    boot[0x0D] = spc
    struct.pack_into("<H", boot, 0x0E, RESERVED)
    boot[0x10] = NFATS
    struct.pack_into("<H", boot, 0x11, 0)          # pas de racine fixe
    struct.pack_into("<H", boot, 0x13, 0)          # total 16 bits : 0
    boot[0x15] = 0xF8                              # média : disque fixe
    struct.pack_into("<H", boot, 0x16, 0)          # FAT16 : 0 => FAT32
    struct.pack_into("<H", boot, 0x18, 63)         # secteurs/piste (BIOS)
    struct.pack_into("<H", boot, 0x1A, 255)        # têtes (BIOS)
    struct.pack_into("<I", boot, 0x1C, 0)          # secteurs cachés (pas de MBR)
    struct.pack_into("<I", boot, 0x20, total)
    struct.pack_into("<I", boot, 0x24, fatsz)
    struct.pack_into("<H", boot, 0x28, 0)          # FAT en miroir
    struct.pack_into("<H", boot, 0x2A, 0)          # version 0.0
    struct.pack_into("<I", boot, 0x2C, 2)          # cluster racine
    struct.pack_into("<H", boot, 0x30, 1)          # secteur FSInfo
    struct.pack_into("<H", boot, 0x32, 6)          # secours du boot
    boot[0x40] = 0x80                              # numéro de lecteur
    boot[0x42] = 0x29                              # signature étendue
    struct.pack_into("<I", boot, 0x43, volume_id)
    boot[0x47:0x52] = label
    boot[0x52:0x5A] = b"FAT32   "
    boot[0x5A:0x5A + len(_BOOT_CODE)] = _BOOT_CODE
    boot[0x1FE:0x200] = b"\x55\xaa"

    fsinfo = bytearray(SECTOR)
    struct.pack_into("<I", fsinfo, 0, 0x41615252)       # « RRaA »
    struct.pack_into("<I", fsinfo, 0x1E4, 0x61417272)   # « rrAa »
    struct.pack_into("<I", fsinfo, 0x1E8, free)
    struct.pack_into("<I", fsinfo, 0x1EC, next_free)
    fsinfo[0x1FE:0x200] = b"\x55\xaa"

    def cluster_off(c: int) -> int:
        return (data_start + (c - 2) * spc) * SECTOR

    with open(output_img, "wb") as fh:
        fh.truncate(total * SECTOR)
        for sec, blob in ((0, boot), (1, fsinfo), (6, boot), (7, fsinfo)):
            fh.seek(sec * SECTOR)
            fh.write(blob)
        for i in range(NFATS):
            fh.seek((RESERVED + i * fatsz) * SECTOR)
            fh.write(fat)
        fh.seek(cluster_off(2))
        fh.write(root)
        for _name, data, first in placed:
            if first:
                fh.seek(cluster_off(first))
                fh.write(data)
    return output_img
