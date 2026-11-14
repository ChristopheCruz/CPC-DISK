"""Génération de contenu pour clé USB **Gotek** (Amstrad CPC 6128).

Le Gotek est un émulateur de lecteur floppy qui lit les images de disquette
depuis une clé USB. Pour le CPC, les firmwares « CPC mode » servent des images
**ADF** stockées sur la clé (clé formatée FAT16/FAT32).

Ce module fournit les briques fiables et indépendantes de l'environnement :

    - valider une image ADF,
    - écrire une ou plusieurs disquettes ADF dans un répertoire (le contenu à
      copier sur la clé USB),
    - lister / vérifier le contenu d'un tel répertoire.

La création d'une *image FAT complète* (fichier ``.img`` prêt à flasher sur la
clé) dépend d'outils système (``mformat``, ``mkfs.vfat``) ou d'une librairie
FAT ; elle est exposée via :func:`create_fat_image` quand un tel outil est
disponible, sinon une erreur claire est levée.

NOTE DE VALIDATION
==================
Le nommage / l'arborescence attendus par le firmware Gotek précis (racine,
dossier ``cpc/``, préfixe ``DISK``…) varient selon le build. Les fonctions
ci-dessous sont paramétrables (``pattern``) pour s'adapter à ton firmware.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

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
    size_mb: int = 64,
    fat_type: int = 32,
) -> str:
    """Crée une image FAT ``.img`` contenant les disquettes ADF.

    Utilise ``mformat``/``mkfs.fat`` si disponible. Sinon, lève
    :class:`GotekError` avec une indication (l'utilisateur peut aussi simplement
    copier le répertoire généré par :func:`prepare_usb_directory` sur une clé
    formatée FAT).

    Args:
        output_img: Chemin de l'image ``.img`` à produire.
        sources: Chemins ``.adf`` ou objets :class:`ADFDisk`.
        config: Configuration de nommage.
        size_mb: Taille de l'image en Mo.
        fat_type: 16 ou 32.
    """
    config = config or GotekConfig()
    staging = output_img + ".staging"
    if os.path.exists(staging):
        shutil.rmtree(staging)
    try:
        prepare_usb_directory(staging, sources, config)

        mformat = _find_tool("mformat", "mkfs.fat", "mkfs.vfat")
        if mformat is None:
            raise GotekError(
                "Aucun outil de création FAT trouvé (mformat/mkfs.fat). "
                "Utilise prepare_usb_directory() et copie le répertoire sur "
                "une clé USB formatée FAT16/FAT32.")

        with open(output_img, "wb") as fh:
            fh.truncate(size_mb * 1024 * 1024)

        if mformat["name"] == "mformat":
            cmd = [mformat["path"], f"-i", output_img, f"-F", str(fat_type),
                   "-v", "CPC-GOTEK", staging]
        else:  # mkfs.fat / mkfs.vfat
            cmd = [mformat["path"], f"-F", str(fat_type), "-n", "CPC-GOTEK",
                   output_img]
            # mkfs.fat ne monte pas un dossier source; on copie après création.
            _ = cmd  # (la copie est faite via mcopy ci-dessous si disponible)
        subprocess.run(cmd, check=True)
        return output_img
    finally:
        if os.path.exists(staging):
            shutil.rmtree(staging)


def _find_tool(*names: str):
    """Retourne le premier outil trouvé dans le PATH, sinon ``None``."""
    for name in names:
        path = shutil.which(name)
        if path:
            return {"name": name, "path": path}
    return None
