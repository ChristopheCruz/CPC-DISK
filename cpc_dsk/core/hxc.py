"""Clé USB pour Gotek équipé du firmware **HxC** (HxC2001).

Le firmware HxC pour Gotek lit directement les images Amstrad ``.DSK``
(aucune conversion) posées à la racine d'une clé FAT32 (FAT16 marche
aussi). Il faut en plus, à la racine de la clé :

    - ``AUTOBOOT.HFE`` : la disquette « sélecteur de fichiers » du CPC
      (archive officielle : ``File_Selector/Amstrad_CPC/``),
    - ``HXCSDFE.CFG``  : le fichier de configuration du sélecteur,
    - éventuellement le fichier de mise à jour du firmware ``*.UPD``
      (``Firmwares_Updates/Generic_Gotek/Standard_Firmware/``), flashé en
      démarrant le Gotek boutons enfoncés.

Ces fichiers sont la propriété d'HxC2001 et ne sont **pas** distribués
avec CPC DISK : l'utilisateur les place dans un dossier ``HXC/`` (voir
:func:`find_hxc_folder`).

Ce module :

    - trouve le dossier HxC (:func:`find_hxc_folder`),
    - choisit les fichiers à copier (:func:`hxc_payload`),
    - nomme les disquettes en 8.3 (:func:`dsk_names_83`),
    - copie le tout sur une clé montée (:func:`prepare_hxc_drive`),
    - ou fabrique une image FAT32 à flasher (:func:`create_hxc_fat32_image`),
    - et, sous Windows uniquement, interroge un lecteur (:func:`drive_info`)
      et ouvre la boîte « Formater » de Windows (:func:`open_format_dialog`)
      — CPC DISK ne formate jamais lui-même.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from cpc_dsk.core.adf import ADFDisk, ADFError
from cpc_dsk.core.fat32 import Fat32Error, write_fat32_image

REQUIRED = ("AUTOBOOT.HFE", "HXCSDFE.CFG")
ENV_VAR = "CPC_DISK_HXC"
DEFAULT_IMAGE_MB = 64

# Caractères autorisés dans un nom court FAT (hors lettres/chiffres).
_83_EXTRA = set("!#$%&'()-@^_`{}~")


class HxcError(Exception):
    """Erreur de préparation d'une clé HxC."""


# --------------------------------------------------------------------------- #
# Dossier des fichiers HxC
# --------------------------------------------------------------------------- #
def _has_required(folder: str) -> bool:
    if not folder or not os.path.isdir(folder):
        return False
    try:
        present = {n.upper() for n in os.listdir(folder)}
    except OSError:
        return False
    return all(r in present for r in REQUIRED)


def candidate_folders(extra: Optional[str] = None) -> List[str]:
    """Dossiers examinés par :func:`find_hxc_folder`, dans l'ordre."""
    out: List[str] = []
    if extra:
        out.append(extra)
    env = os.environ.get(ENV_VAR)
    if env:
        out.append(env)
    if getattr(sys, "frozen", False):
        out.append(os.path.join(os.path.dirname(sys.executable), "HXC"))
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out.append(os.path.join(os.path.dirname(pkg), "HXC"))
    out.append(os.path.join(os.getcwd(), "HXC"))
    return out


def find_hxc_folder(extra: Optional[str] = None) -> Optional[str]:
    """Premier dossier existant contenant ``AUTOBOOT.HFE`` et
    ``HXCSDFE.CFG`` parmi : ``extra`` ; la variable d'environnement
    ``CPC_DISK_HXC`` ; ``HXC/`` à côté de l'exécutable (PyInstaller) ;
    ``HXC/`` à la racine du projet ; ``HXC/`` dans le dossier courant.
    Renvoie ``None`` si aucun ne convient."""
    for folder in candidate_folders(extra):
        if _has_required(folder):
            return os.path.abspath(folder)
    return None


def _real_name(folder: str, upper: str) -> Optional[str]:
    """Chemin réel d'un fichier du dossier (nom insensible à la casse)."""
    for n in os.listdir(folder):
        if n.upper() == upper:
            return os.path.join(folder, n)
    return None


def _version_key(name: str) -> Tuple:
    """Clé de tri d'un nom de firmware : ``HXCFEUSB_V3_1_23_1a.UPD`` ->
    ``((3, ''), (1, ''), (23, ''), (1, 'a'))``."""
    stem = os.path.splitext(name)[0].lower()
    return tuple((int(n), s) for n, s in re.findall(r"(\d+)([a-z]*)", stem))


def pick_firmware(folder: str) -> Optional[str]:
    """Le ``*.UPD`` de plus haute version du dossier (ou ``None``)."""
    upds = [n for n in os.listdir(folder) if n.upper().endswith(".UPD")
            and os.path.isfile(os.path.join(folder, n))]
    if not upds:
        return None
    return os.path.join(folder, max(upds, key=lambda n: (_version_key(n), n)))


def hxc_payload(folder: str,
                with_firmware: bool = False) -> List[Tuple[str, bytes]]:
    """Fichiers HxC à poser à la racine de la clé : ``[(nom 8.3, données)]``.

    ``AUTOBOOT.HFE`` et ``HXCSDFE.CFG``, plus le firmware ``.UPD`` si
    demandé (celui de plus haute version). Jamais de ``.ROM`` (ROM côté
    CPC), de ``FF.CFG`` (FlashFloppy) ni d'autre fichier."""
    if not folder or not os.path.isdir(folder):
        raise HxcError(f"Dossier HxC introuvable : {folder}")
    out: List[Tuple[str, bytes]] = []
    for req in REQUIRED:
        path = _real_name(folder, req)
        if path is None:
            raise HxcError(f"{req} manquant dans {folder}")
        with open(path, "rb") as fh:
            out.append((req, fh.read()))
    if with_firmware:
        upd = pick_firmware(folder)
        if upd is None:
            raise HxcError(
                f"Aucun fichier de mise à jour du firmware (.UPD) dans {folder}")
        with open(upd, "rb") as fh:
            out.append((short_name(os.path.basename(upd), "UPD"), fh.read()))
    return out


# --------------------------------------------------------------------------- #
# Noms 8.3
# --------------------------------------------------------------------------- #
def _clean(part: str) -> str:
    out = []
    for ch in part.upper():
        if ch == " " or ch == ".":
            continue
        if ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in _83_EXTRA:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def short_name(filename: str, ext: str) -> str:
    """Nom 8.3 majuscule d'extension ``ext`` : la base du nom d'origine si
    elle est valide, sinon nettoyée (caractères interdits -> ``_``) et
    tronquée à 8 caractères."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    base = _clean(stem)[:8] or "DISK"
    return f"{base}.{ext.upper()[:3]}"


def dsk_names_83(paths: Sequence[str],
                 taken: Iterable[str] = ()) -> List[str]:
    """Noms 8.3 (``.DSK``) des disquettes, dédoublonnés avec ``~1``,
    ``~2``… (en évitant aussi les noms de ``taken``)."""
    used = {n.upper() for n in taken}
    names: List[str] = []
    for p in paths:
        name = short_name(p, "DSK")
        base, ext = name.rsplit(".", 1)
        k = 0
        while name in used:
            k += 1
            suffix = f"~{k}"
            name = f"{base[:8 - len(suffix)]}{suffix}.{ext}"
        used.add(name)
        names.append(name)
    return names


def _load_disks(paths: Sequence[str],
                taken: Iterable[str]) -> List[Tuple[str, bytes]]:
    """Valide chaque ``.dsk`` (:meth:`ADFDisk.load`) et renvoie
    ``[(nom 8.3, données)]``."""
    out: List[Tuple[str, bytes]] = []
    for name, path in zip(dsk_names_83(paths, taken), paths):
        try:
            ADFDisk.load(path)
            with open(path, "rb") as fh:
                data = fh.read()
        except (OSError, ADFError, ValueError) as exc:
            raise HxcError(
                f"Disquette invalide ou illisible : {path} — {exc}") from exc
        out.append((name, data))
    return out


def hxc_files(folder: str, dsk_paths: Sequence[str],
              with_firmware: bool = False) -> List[Tuple[str, bytes]]:
    """Tout ce qui va à la racine de la clé : fichiers HxC + disquettes."""
    payload = hxc_payload(folder, with_firmware)
    return payload + _load_disks(dsk_paths, (n for n, _ in payload))


# --------------------------------------------------------------------------- #
# Clé montée / image FAT32
# --------------------------------------------------------------------------- #
def prepare_hxc_drive(root: str, folder: str, dsk_paths: Sequence[str],
                      with_firmware: bool = False) -> List[str]:
    """Copie les fichiers HxC et les disquettes à la racine ``root`` d'une
    clé déjà montée. N'écrase que les fichiers de même nom ; tout est
    validé avant la première écriture. Renvoie les noms écrits."""
    if not root or not os.path.isdir(root):
        raise HxcError(f"Dossier de destination introuvable : {root}")
    files = hxc_files(folder, dsk_paths, with_firmware)
    if with_firmware:
        # Procédure HxC2001 : « Remove any older *.upd file from the USB
        # stick » — le bootloader prend un .upd quelconque de la racine.
        keep = {name.upper() for name, _ in files}
        for entry in os.listdir(root):
            if entry.lower().endswith(".upd") and entry.upper() not in keep:
                path = os.path.join(root, entry)
                if os.path.isfile(path):
                    os.remove(path)
    written: List[str] = []
    for name, data in files:
        with open(os.path.join(root, name), "wb") as fh:
            fh.write(data)
        written.append(name)
    return written


def image_size_mb(files: Sequence[Tuple[str, bytes]],
                  minimum: int = DEFAULT_IMAGE_MB) -> int:
    """Taille d'image suffisante (Mo) pour ``files`` (au moins ``minimum``)."""
    need = sum(len(d) + 4096 for _, d in files)
    return max(minimum, need * 11 // 10 // (1024 * 1024) + 8)


def create_hxc_fat32_image(out_img: str, folder: str,
                           dsk_paths: Sequence[str],
                           with_firmware: bool = False,
                           size_mb: int = DEFAULT_IMAGE_MB,
                           label: str = "CPC-HXC") -> str:
    """Fabrique une image FAT32 (``.img``, sans MBR) contenant les
    fichiers HxC et les disquettes, à écrire sur la clé avec Rufus,
    balenaEtcher ou ``dd``."""
    files = hxc_files(folder, dsk_paths, with_firmware)
    try:
        return write_fat32_image(out_img, files, int(size_mb) * 1024 * 1024,
                                 volume_label=label)
    except Fat32Error as exc:
        raise HxcError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Windows : informations sur un lecteur, boîte « Formater »
# --------------------------------------------------------------------------- #
DRIVE_REMOVABLE = 2
SHFMT_ERROR = 0xFFFFFFFF
SHFMT_CANCEL = 0xFFFFFFFE
SHFMT_NOFORMAT = 0xFFFFFFFD


def drive_root(path: str) -> str:
    """Racine du lecteur d'un chemin Windows (``E:/x`` -> ``E:\\``)."""
    drive = os.path.splitdrive(path)[0] or path[:2]
    return drive.rstrip("\\/") + "\\"


def drive_info(root: str) -> Optional[Dict]:
    """Infos d'un lecteur Windows : ``type_removable``, ``fs`` (« FAT32 »,
    « NTFS »…), ``label``, ``total`` et ``free`` (octets). Renvoie
    ``None`` hors Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    root = drive_root(root)
    dtype = k32.GetDriveTypeW(ctypes.c_wchar_p(root))
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    serial, maxlen, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    ok = k32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), label, 261, ctypes.byref(serial),
        ctypes.byref(maxlen), ctypes.byref(flags), fs, 261)
    avail, total, tfree = (ctypes.c_ulonglong(), ctypes.c_ulonglong(),
                           ctypes.c_ulonglong())
    ok2 = k32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(root), ctypes.byref(avail),
                                  ctypes.byref(total), ctypes.byref(tfree))
    return dict(type_removable=(dtype == DRIVE_REMOVABLE),
                fs=fs.value if ok else "",
                label=label.value if ok else "",
                total=int(total.value) if ok2 else 0,
                free=int(tfree.value) if ok2 else 0)


def open_format_dialog(root: str, hwnd: int = 0) -> str:
    """Ouvre la boîte « Formater » de Windows (``SHFormatDrive``) sur le
    lecteur ``root`` : c'est l'utilisateur qui confirme le formatage.

    Renvoie ``"ok"``, ``"cancel"``, ``"noformat"`` ou ``"error"``. Lève
    :class:`HxcError` hors Windows."""
    if sys.platform != "win32":
        raise HxcError("La boîte de formatage n'existe que sous Windows.")
    import ctypes
    from ctypes import wintypes

    letter = drive_root(root)[:1].upper()
    if not "A" <= letter <= "Z":
        raise HxcError(f"Lecteur invalide : {root}")
    fn = ctypes.windll.shell32.SHFormatDrive
    fn.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
    fn.restype = wintypes.DWORD
    res = fn(hwnd or None, ord(letter) - ord("A"), 0xFFFF, 0)
    return {SHFMT_ERROR: "error", SHFMT_CANCEL: "cancel",
            SHFMT_NOFORMAT: "noformat"}.get(res, "ok")
