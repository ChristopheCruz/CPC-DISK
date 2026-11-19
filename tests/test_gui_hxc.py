"""Tests GUI du bloc « Clé HxC » de l'onglet Gotek (faux fichiers HxC).

Nécessitent un affichage (sinon ignorés).
"""

import os
import sys
from unittest import mock

import tkinter as tk

import pytest

from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.gotek import list_fat_image


def _display_available() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


HAS_DISPLAY = _display_available()
pytestmark = pytest.mark.skipif(not HAS_DISPLAY,
                                reason="pas d'affichage disponible")


def _fake_hxc(folder):
    os.makedirs(folder, exist_ok=True)
    for name, size in (("AUTOBOOT.HFE", 4096), ("HXCSDFE.CFG", 8192),
                       ("HXCFEUSB_V3_1_23_1a.UPD", 2048), ("HXC35.ROM", 100)):
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(os.urandom(size))
    return folder


@pytest.fixture
def app(monkeypatch, tmp_path):
    from cpc_dsk.core import hxc
    from cpc_dsk.gui import DskEditorApp

    monkeypatch.delenv(hxc.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    # Pas de dossier HXC à la racine du projet pendant les tests.
    monkeypatch.setattr(hxc, "candidate_folders",
                        lambda extra=None: [extra] if extra else [])
    root = tk.Tk()
    root.withdraw()
    a = DskEditorApp(root)
    root.update()
    yield a
    root.destroy()


def test_hxc_block_builds(app):
    assert app.hxc_panel.winfo_exists()
    for w in (app.hxc_prepare_btn, app.hxc_image_btn, app.hxc_change_btn,
              app.hxc_fw_check):
        assert w.winfo_exists()
    assert app.hxc_fw.get() is False
    from cpc_dsk.i18n import t as L
    assert app.hxc_folder_lbl.cget("text") == L("hxc_notfound")


def test_hxc_choose_folder_and_language_rebuild(app, tmp_path):
    d = _fake_hxc(str(tmp_path / "HXC"))
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory", return_value=d):
        app.hxc_choose_folder()
    assert app.hxc_folder_lbl.cget("text").endswith("HXC")
    # Le choix survit à la reconstruction de l'interface (langue).
    other = "fr" if app._lang != "fr" else "en"
    app.lang_var.set(other)
    app.root.update()
    assert app.hxc_folder_lbl.cget("text").endswith("HXC")
    assert app._hxc_folder() == os.path.abspath(d)


def test_hxc_choose_bad_folder(app, tmp_path):
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory",
                    return_value=str(tmp_path)), \
            mock.patch.object(app, "error") as err:
        app.hxc_choose_folder()
    err.assert_called_once()
    assert app._hxc_folder_choice is None


def test_hxc_buttons_without_folder(app):
    with mock.patch.object(app, "error") as err:
        app.hxc_prepare()
        app.hxc_image()
    assert err.call_count == 2


def test_hxc_prepare_to_folder(app, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    app._hxc_folder_choice = _fake_hxc(str(tmp_path / "HXC"))
    dsk = str(tmp_path / "robot.dsk")
    ADFDisk.new_blank().save(dsk)
    app.gotek_add_paths([dsk])
    app.hxc_fw.set(True)
    key = tmp_path / "key"
    key.mkdir()
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory",
                    return_value=str(key)), \
            mock.patch.object(app, "ask", return_value=True) as ask:
        app.hxc_prepare()
    msg = ask.call_args[0][1]
    assert "ROBOT.DSK" in msg and "HXCFEUSB.UPD" in msg
    assert sorted(os.listdir(key)) == ["AUTOBOOT.HFE", "HXCFEUSB.UPD",
                                       "HXCSDFE.CFG", "ROBOT.DSK"]
    assert [n for n, _ in app._gtk_last] == ["AUTOBOOT.HFE", "HXCSDFE.CFG",
                                             "HXCFEUSB.UPD", "ROBOT.DSK"]


def test_hxc_prepare_cancel_writes_nothing(app, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    app._hxc_folder_choice = _fake_hxc(str(tmp_path / "HXC"))
    key = tmp_path / "key"
    key.mkdir()
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory",
                    return_value=str(key)), \
            mock.patch.object(app, "ask", return_value=False) as ask:
        app.hxc_prepare()
    from cpc_dsk.i18n import t as L
    assert L("hxc_no_disks") in ask.call_args[0][1]   # liste vide signalée
    assert os.listdir(key) == []


def test_hxc_prepare_windows_checks(app, tmp_path, monkeypatch):
    """Chemin Windows simulé : lecteur fixe refusé ; NTFS -> boîte
    Formater proposée puis revérification."""
    app._hxc_folder_choice = _fake_hxc(str(tmp_path / "HXC"))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("cpc_dsk.gui.drive_root", lambda p: str(tmp_path))
    fixed = dict(type_removable=False, fs="NTFS", label="DATA",
                 total=1 << 30, free=0)
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory",
                    return_value="E:/"), \
            mock.patch("cpc_dsk.gui.drive_info", return_value=fixed), \
            mock.patch.object(app, "error") as err, \
            mock.patch("cpc_dsk.gui.prepare_hxc_drive") as prep:
        app.hxc_prepare()
    err.assert_called_once()
    prep.assert_not_called()

    ntfs = dict(fixed, type_removable=True)
    fat32 = dict(ntfs, fs="FAT32", label="HXC")
    with mock.patch("cpc_dsk.gui.filedialog.askdirectory",
                    return_value="E:/"), \
            mock.patch("cpc_dsk.gui.drive_info",
                       side_effect=[ntfs, fat32]), \
            mock.patch("cpc_dsk.gui.open_format_dialog",
                       return_value="ok") as fmt, \
            mock.patch.object(app, "ask", return_value=True), \
            mock.patch("cpc_dsk.gui.prepare_hxc_drive",
                       return_value=["AUTOBOOT.HFE"]) as prep:
        app.hxc_prepare()
    fmt.assert_called_once()
    prep.assert_called_once()


def test_hxc_image(app, tmp_path):
    app._hxc_folder_choice = _fake_hxc(str(tmp_path / "HXC"))
    dsk = str(tmp_path / "jeu.dsk")
    ADFDisk.new_blank().save(dsk)
    app.gotek_add_paths([dsk])
    out = str(tmp_path / "cle.img")
    with mock.patch("cpc_dsk.gui.filedialog.asksaveasfilename",
                    return_value=out), \
            mock.patch.object(app, "info_box") as info:
        app.hxc_image()
    assert "Rufus" in info.call_args[0][1]
    assert {f.name for f in list_fat_image(out)} == {
        "AUTOBOOT.HFE", "HXCSDFE.CFG", "JEU.DSK"}
