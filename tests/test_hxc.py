"""Tests de la clé HxC (cpc_dsk.core.hxc) et du rédacteur FAT32.

Les fichiers HxC utilisés ici sont des FAUX (octets aléatoires portant les
bons noms) : le vrai firmware HxC2001 n'est jamais copié dans les tests.
Un test optionnel lit le vrai dossier si ``CPC_DISK_HXC_REAL`` est défini
(sans rien y écrire).
"""

import os
import shutil
import subprocess
import sys
from unittest import mock

import pytest

from cpc_dsk.core import hxc
from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.fat32 import Fat32Error, min_size_mb, write_fat32_image
from cpc_dsk.core.gotek import list_fat_image

FSCK = shutil.which("fsck.fat") or (
    "/usr/sbin/fsck.fat" if os.path.exists("/usr/sbin/fsck.fat") else None)


def _fake_hxc(folder, upds=("HXCFEUSB_V3_1_23_1a.UPD",), extra=True):
    os.makedirs(folder, exist_ok=True)
    files = {"AUTOBOOT.HFE": 300_000, "HXCSDFE.CFG": 8192}
    for u in upds:
        files[u] = 93_184
    if extra:
        files.update({"HXC35.ROM": 15_455, "FF.CFG": 6650,
                      "HXCSDFE_ma_cle.CFG": 8192, "notes.txt": 10})
    for name, size in files.items():
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(os.urandom(size))
    return folder


def _dsk(path):
    ADFDisk.new_blank().save(path)
    return path


def _fsck(img):
    r = subprocess.run([FSCK, "-n", img], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# --------------------------------------------------------------------------- #
# Détection du dossier
# --------------------------------------------------------------------------- #
def test_find_folder_extra_then_env(tmp_path, monkeypatch):
    a = _fake_hxc(str(tmp_path / "a"))
    b = _fake_hxc(str(tmp_path / "b"))
    monkeypatch.setenv(hxc.ENV_VAR, b)
    assert hxc.find_hxc_folder(a) == os.path.abspath(a)
    assert hxc.find_hxc_folder() == os.path.abspath(b)
    # extra invalide : on passe à la variable d'environnement
    assert hxc.find_hxc_folder(str(tmp_path / "nope")) == os.path.abspath(b)


def test_find_folder_requires_both_files(tmp_path, monkeypatch):
    d = tmp_path / "half"
    d.mkdir()
    (d / "AUTOBOOT.HFE").write_bytes(b"x")
    monkeypatch.delenv(hxc.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    with mock.patch.object(hxc, "candidate_folders",
                           return_value=[str(d)]):
        assert hxc.find_hxc_folder() is None
    (d / "hxcsdfe.cfg").write_bytes(b"y")     # casse indifférente
    assert hxc.find_hxc_folder(str(d)) == str(d)


def test_find_folder_cwd_and_frozen(tmp_path, monkeypatch):
    monkeypatch.delenv(hxc.ENV_VAR, raising=False)
    exe_dir = tmp_path / "exe"
    _fake_hxc(str(exe_dir / "HXC"))
    cwd = tmp_path / "cwd"
    _fake_hxc(str(cwd / "HXC"))
    monkeypatch.chdir(cwd)
    cands = hxc.candidate_folders()
    assert cands[-1] == os.path.join(str(cwd), "HXC")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "cpc-dsk-gui.exe"))
    cands = hxc.candidate_folders()
    assert cands[0] == os.path.join(str(exe_dir), "HXC")
    assert hxc.find_hxc_folder() == os.path.join(str(exe_dir), "HXC")


# --------------------------------------------------------------------------- #
# Sélection des fichiers
# --------------------------------------------------------------------------- #
def test_payload_without_firmware(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    names = [n for n, _ in hxc.hxc_payload(d)]
    assert names == ["AUTOBOOT.HFE", "HXCSDFE.CFG"]


def test_payload_firmware_highest_version(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"), upds=(
        "HXCFEUSB_V3_1_9_1a.UPD", "HXCFEUSB_V3_1_23_1a.UPD",
        "HXCFEUSB_V3_1_23_1.UPD", "HXCFEUSB_V2_9_99_9z.UPD"))
    with open(os.path.join(d, "HXCFEUSB_V3_1_23_1a.UPD"), "rb") as fh:
        expected = fh.read()
    payload = hxc.hxc_payload(d, with_firmware=True)
    names = [n for n, _ in payload]
    assert names == ["AUTOBOOT.HFE", "HXCSDFE.CFG", "HXCFEUSB.UPD"]
    assert payload[2][1] == expected
    assert not any(n.endswith(".ROM") or n == "FF.CFG" for n in names)


def test_payload_firmware_missing(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"), upds=())
    with pytest.raises(hxc.HxcError):
        hxc.hxc_payload(d, with_firmware=True)
    assert len(hxc.hxc_payload(d)) == 2


def test_payload_missing_required(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    os.remove(os.path.join(d, "HXCSDFE.CFG"))
    with pytest.raises(hxc.HxcError):
        hxc.hxc_payload(d)


# --------------------------------------------------------------------------- #
# Noms 8.3
# --------------------------------------------------------------------------- #
def test_names_83_keep_sanitize_dedupe():
    names = hxc.dsk_names_83([
        "x/robot.dsk", "y/ROBOT.DSK", "z/Very long name é.dsk",
        "w/very long name 2.dsk", "v/abbey.adf", "u/a.b.c.dsk",
        "t/robot.dsk"])
    assert names == ["ROBOT.DSK", "ROBOT~1.DSK", "VERYLONG.DSK",
                     "VERYLO~1.DSK", "ABBEY.DSK", "ABC.DSK", "ROBOT~2.DSK"]
    for n in names:
        base, ext = n.split(".")
        assert 1 <= len(base) <= 8 and ext == "DSK"


def test_names_83_avoid_taken():
    assert hxc.dsk_names_83(["autoboot.dsk"], ["AUTOBOOT.DSK"]) == \
        ["AUTOBO~1.DSK"]


# --------------------------------------------------------------------------- #
# Copie sur une clé montée
# --------------------------------------------------------------------------- #
def test_prepare_drive(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    key = tmp_path / "key"
    key.mkdir()
    (key / "OTHER.TXT").write_bytes(b"keep me")
    (key / "ROBOT.DSK").write_bytes(b"old")
    src = [_dsk(str(tmp_path / "robot.dsk")),
           _dsk(str(tmp_path / "Mon jeu préféré.dsk"))]
    written = hxc.prepare_hxc_drive(str(key), d, src, with_firmware=True)
    assert written == ["AUTOBOOT.HFE", "HXCSDFE.CFG", "HXCFEUSB.UPD",
                       "ROBOT.DSK", "MONJEUPR.DSK"]
    assert (key / "OTHER.TXT").read_bytes() == b"keep me"
    assert (key / "ROBOT.DSK").read_bytes() == open(src[0], "rb").read()
    assert (key / "AUTOBOOT.HFE").read_bytes() == \
        open(os.path.join(d, "AUTOBOOT.HFE"), "rb").read()
    assert not (key / "HXC35.ROM").exists()
    assert not (key / "FF.CFG").exists()


def test_prepare_drive_removes_old_upd_only_with_firmware(tmp_path):
    """Procédure HxC2001 : retirer les anciens .upd avant d'en copier un."""
    d = _fake_hxc(str(tmp_path / "h"))
    key = tmp_path / "key"
    key.mkdir()
    (key / "HXCFEUSB_V3_0_0_1a.UPD").write_bytes(b"old fw")
    (key / "old.upd").write_bytes(b"older fw")
    hxc.prepare_hxc_drive(str(key), d, [], with_firmware=False)
    assert (key / "old.upd").exists()          # sans firmware : on n'y touche pas
    hxc.prepare_hxc_drive(str(key), d, [], with_firmware=True)
    upds = sorted(p.name for p in key.iterdir() if p.suffix.lower() == ".upd")
    assert upds == ["HXCFEUSB.UPD"]


def test_prepare_drive_invalid_dsk_writes_nothing(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    key = tmp_path / "key"
    key.mkdir()
    bad = tmp_path / "bad.dsk"
    bad.write_bytes(b"not a disk" * 100)
    with pytest.raises(hxc.HxcError):
        hxc.prepare_hxc_drive(str(key), d, [str(bad)])
    assert os.listdir(key) == []


def test_prepare_drive_missing_root(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    with pytest.raises(hxc.HxcError):
        hxc.prepare_hxc_drive(str(tmp_path / "nokey"), d, [])


# --------------------------------------------------------------------------- #
# Image FAT32
# --------------------------------------------------------------------------- #
def test_fat32_image_readback(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    src = [_dsk(str(tmp_path / f"disk{i}.dsk")) for i in range(3)]
    img = str(tmp_path / "hxc.img")
    hxc.create_hxc_fat32_image(img, d, src, with_firmware=True)
    assert os.path.getsize(img) == 64 * 1024 * 1024
    with open(img, "rb") as fh:
        boot = fh.read(512)
    assert boot[0x52:0x5A] == b"FAT32   "      # superfloppy : pas de MBR
    assert boot[0x47:0x52] == b"CPC-HXC    "
    files = {f.name: f.data for f in list_fat_image(img)}
    expected = dict(hxc.hxc_files(d, src, with_firmware=True))
    assert files == expected
    assert set(files) == {"AUTOBOOT.HFE", "HXCSDFE.CFG", "HXCFEUSB.UPD",
                          "DISK0.DSK", "DISK1.DSK", "DISK2.DSK"}


def test_fat32_image_selector_only(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    img = str(tmp_path / "sel.img")
    hxc.create_hxc_fat32_image(img, d, [])
    assert [f.name for f in list_fat_image(img)] == ["AUTOBOOT.HFE",
                                                     "HXCSDFE.CFG"]


@pytest.mark.skipif(FSCK is None, reason="fsck.fat absent")
@pytest.mark.parametrize("size_mb", [min_size_mb(), 64, 300])
def test_fat32_fsck_clean(tmp_path, size_mb):
    d = _fake_hxc(str(tmp_path / "h"))
    src = [_dsk(str(tmp_path / "a.dsk")), _dsk(str(tmp_path / "b.dsk"))]
    img = str(tmp_path / "hxc.img")
    hxc.create_hxc_fat32_image(img, d, src, with_firmware=True,
                               size_mb=size_mb)
    rc, out = _fsck(img)
    assert rc == 0, out           # -n : code 0 = aucune erreur trouvée


@pytest.mark.skipif(FSCK is None, reason="fsck.fat absent")
def test_fat32_many_files_multi_cluster_root(tmp_path):
    # 40 entrées : la racine dépasse un cluster de 512 o (16 entrées).
    files = [(f"F{i:03d}.BIN", os.urandom(i * 37)) for i in range(40)]
    img = str(tmp_path / "many.img")
    write_fat32_image(img, files, 40 * 1024 * 1024, volume_label="TEST")
    rc, out = _fsck(img)
    assert rc == 0, out
    assert {f.name: f.data for f in list_fat_image(img)} == dict(files)


def test_fat32_size_errors(tmp_path):
    d = _fake_hxc(str(tmp_path / "h"))
    img = str(tmp_path / "x.img")
    with pytest.raises(hxc.HxcError, match="petite"):
        hxc.create_hxc_fat32_image(img, d, [], size_mb=min_size_mb() - 1)
    with pytest.raises(hxc.HxcError, match="grande"):
        hxc.create_hxc_fat32_image(img, d, [], size_mb=64 * 1024)
    with pytest.raises(Fat32Error, match="saturée"):
        write_fat32_image(img, [("BIG.BIN", b"\0" * (40 << 20))], 40 << 20)
    assert min_size_mb() == 33


def test_image_size_grows_with_content():
    assert hxc.image_size_mb([("A", b"x" * 1000)]) == 64
    assert hxc.image_size_mb([("A", b"x" * (100 << 20))]) > 100


# --------------------------------------------------------------------------- #
# Windows uniquement
# --------------------------------------------------------------------------- #
def test_windows_helpers_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert hxc.drive_info("E:\\") is None
    with pytest.raises(hxc.HxcError):
        hxc.open_format_dialog("E:\\")


def test_drive_root():
    assert hxc.drive_root("E:/") == "E:\\"
    assert hxc.drive_root("e:/sub/dir") == "e:\\"


@pytest.mark.skipif(sys.platform == "win32", reason="mock de ctypes.windll")
def test_windows_helpers_mocked(monkeypatch):
    """Simule kernel32/shell32 pour exercer le code ctypes hors Windows."""
    import ctypes

    class K32:
        def GetDriveTypeW(self, root):
            return 2

        def GetVolumeInformationW(self, root, label, n1, s, m, f, fs, n2):
            label.value = "HXC"
            fs.value = "FAT32"
            return 1

        def GetDiskFreeSpaceExW(self, root, avail, total, tfree):
            total._obj.value = 8 << 30
            tfree._obj.value = 1 << 30
            return 1

    calls = []

    def shformat(hwnd, drive, fmtid, opts):
        calls.append((hwnd, drive, fmtid, opts))
        return 0xFFFFFFFE

    class Shell32:
        SHFormatDrive = staticmethod(shformat)

    win = mock.Mock()
    win.kernel32 = K32()
    win.shell32 = Shell32()
    monkeypatch.setattr(ctypes, "windll", win, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    info = hxc.drive_info("E:/")
    assert info == dict(type_removable=True, fs="FAT32", label="HXC",
                        total=8 << 30, free=1 << 30)
    assert hxc.open_format_dialog("E:\\", 0) == "cancel"
    assert calls == [(None, 4, 0xFFFF, 0)]


# --------------------------------------------------------------------------- #
# Vrai dossier HxC (optionnel, lecture seule)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.environ.get("CPC_DISK_HXC_REAL"),
                    reason="CPC_DISK_HXC_REAL non défini")
def test_real_hxc_folder(tmp_path):
    real = os.environ["CPC_DISK_HXC_REAL"]
    assert hxc.find_hxc_folder(real) == os.path.abspath(real)
    names = [n for n, _ in hxc.hxc_payload(real, with_firmware=True)]
    assert names[:2] == ["AUTOBOOT.HFE", "HXCSDFE.CFG"]
    assert names[2].endswith(".UPD")
    img = str(tmp_path / "real.img")
    hxc.create_hxc_fat32_image(img, real, [], with_firmware=True)
    assert {f.name for f in list_fat_image(img)} == set(names)
    if FSCK:
        rc, out = _fsck(img)
        assert rc == 0, out
