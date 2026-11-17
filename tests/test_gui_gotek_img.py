"""Tests de régression : extraction de fichiers d'une image Gotek (GUI).

Le panneau Gotek liste les fichiers d'une image ``.img`` chargée dans une
liste sélectionnable ; « Extraire… » sort le(s) fichier(s) sélectionné(s)
(sans le(s) retirer de l'image), ou tous si aucune sélection.

Nécessitent un affichage (sinon ignorés).
"""

import os
import tempfile
from unittest import mock

import tkinter as tk

import pytest


def _display_available() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


HAS_DISPLAY = _display_available()


def _app_with_image():
    from cpc_dsk.gui import DskEditorApp
    from cpc_dsk.core.adf import ADFDisk
    from cpc_dsk.core.gotek import GotekConfig, create_fat_image

    root = tk.Tk()
    root.withdraw()
    app = DskEditorApp(root)
    root.update()
    tmp = tempfile.mkdtemp()
    paths = []
    for n in ("a", "b", "c"):
        p = os.path.join(tmp, f"{n}.adf")
        ADFDisk.new_blank().save(p)
        paths.append(p)
    img = os.path.join(tmp, "cle.img")
    create_fat_image(img, paths, GotekConfig(), size_mb=4)
    with mock.patch("cpc_dsk.gui.filedialog.askopenfilename",
                    return_value=img):
        app.gotek_load_image()
    root.update()
    return root, app, img


@pytest.mark.skipif(not HAS_DISPLAY, reason="pas d'affichage disponible")
def test_gotek_img_load_populates_selectable_list():
    """Charger une image remplit la liste sélectionnable (nom + taille)."""
    root, app, _ = _app_with_image()
    kids = app.gtk_img_tree.get_children()
    assert len(kids) == 3
    vals = [app.gtk_img_tree.item(k, "values") for k in kids]
    assert [v[0] for v in vals] == ["DISK001.ADF", "DISK002.ADF",
                                    "DISK003.ADF"]
    assert app.gtk_img_label.cget("text").endswith("cle.img")
    root.destroy()


@pytest.mark.skipif(not HAS_DISPLAY, reason="pas d'affichage disponible")
def test_gotek_img_extract_selected_only_image_untouched():
    """Extraire le(s) fichier(s) sélectionné(s) → seul(s) lui/elles sort,
    l'image n'est pas modifiée. Sans sélection → tous les fichiers."""
    from cpc_dsk.core.gotek import list_fat_image

    root, app, img = _app_with_image()
    kids = app.gtk_img_tree.get_children()

    # Sélection multiple (1er + 3e) → exactement ces deux fichiers.
    app.gtk_img_tree.selection_set(kids[0], kids[2])
    out = tempfile.mkdtemp()
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory", return_value=out):
        app.gotek_img_extract()
    assert sorted(os.listdir(out)) == ["DISK001.ADF", "DISK003.ADF"]

    # Sans sélection → tous les fichiers.
    app.gtk_img_tree.selection_remove(*kids)
    out2 = tempfile.mkdtemp()
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory", return_value=out2):
        app.gotek_img_extract()
    assert sorted(os.listdir(out2)) == ["DISK001.ADF", "DISK002.ADF",
                                        "DISK003.ADF"]

    # L'image n'a pas été modifiée par les extractions (lecture seule).
    assert [f.name for f in list_fat_image(img)] == \
        ["DISK001.ADF", "DISK002.ADF", "DISK003.ADF"]
    root.destroy()
