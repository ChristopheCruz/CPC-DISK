"""Tests du catalogue AMSDOS (cpc_dsk.core.amsdos), format DATA et SYSTEM.

Les disquettes réelles de test_disks/ servent de référence : un fichier
texte lu par le catalogue doit être continu d'un secteur à l'autre, et
une disquette écrite par l'outil doit être relue à l'identique.
"""

import os

import pytest

from cpc_dsk import cli
from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.amsdos import (
    DATA,
    SYSTEM,
    AmsdosFilesystem,
    build_header,
    detect_format,
    parse_header,
    to_field11,
)
from cpc_dsk.core.cpcfs import CpcError, FT_BASIC

HERE = os.path.dirname(os.path.abspath(__file__))
DISKS = os.path.join(HERE, "..", "test_disks")


def disk(name):
    path = os.path.join(DISKS, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} absent")
    return ADFDisk.load(path)


# --------------------------------------------------------------------------- #
# Détection, noms, en-têtes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name,fmt", [
    ("robot.dsk", DATA), ("greed.dsk", DATA), ("compilation190.dsk", DATA),
    ("seq16.dsk", DATA), ("vierge.dsk", DATA), ("cpm22.dsk", SYSTEM),
    ("planetfall_cpm.dsk", SYSTEM), ("starcross_cpm.dsk", SYSTEM),
    ("abbey.dsk", None),
])
def test_detect_format(name, fmt):
    assert detect_format(disk(name)) is fmt


def test_field11():
    assert to_field11("arkano2.bin") == "ARKANO2 BIN"
    assert to_field11("LARA-RAM.SRC") == "LARA-RAMSRC"
    assert to_field11("ROINTIMEDEM") == "ROINTIMEDEM"
    assert to_field11("A.BAS") == "A       BAS"
    with pytest.raises(CpcError):
        to_field11("BEAUCOUPTROPLONG.BIN")


def test_header_roundtrip():
    h = build_header("JEU     BAS", 1234, FT_BASIC, 0x170, 0)
    assert len(h) == 128
    assert parse_header(h + bytes(10)) == {
        "type": FT_BASIC, "load": 0x170, "exec": 0, "length": 1234}
    assert parse_header(bytes(128)) is None
    bad = bytearray(h)
    bad[0x43] ^= 1
    assert parse_header(bytes(bad)) is None


# --------------------------------------------------------------------------- #
# Lecture de disquettes réelles
# --------------------------------------------------------------------------- #
def test_robot_text_is_continuous():
    """LARA.DOC (45 Ko, 3 extensions) : le texte continue aux jonctions."""
    fs = AmsdosFilesystem(disk("robot.dsk"))
    doc = fs.read_file("LARA.DOC")
    assert len(doc) == 45312
    assert b"\xe5" * 32 not in doc            # aucun secteur vide intercalé
    assert doc[1536:1560].startswith(b"*****\r\n\r\n\r\nLetzte")
    names = [f.name for f in fs.list_files()]
    assert len(names) == 10 and "DW-DESK.SRC" in names


def test_compilation190_full_catalog():
    """18 fichiers au catalogue (au-delà des 16 entrées du premier secteur)."""
    fs = AmsdosFilesystem(disk("compilation190.dsk"))
    files = fs.list_files()
    assert len(files) == 18
    byname = {f.name: f for f in files}
    assert byname["ARKANO.BIN"].has_header
    assert byname["ARKANO.BIN"].length == 35461
    assert byname["GRUGEUR.BAS"].length == 1743
    # BASIC sauvé en ASCII (SAVE "x",A) : pas d'en-tête, texte brut.
    assert not byname["ROMGET.BAS"].has_header
    assert fs.read_file("ROMGET.BAS").startswith(b"100 REM ROMGET")


def test_seq16_disk():
    fs = AmsdosFilesystem(disk("seq16.dsk"))
    byname = {f.name: f for f in fs.list_files()}
    assert "SEQ16.BIN" in byname and "BRUITS.INS" in byname
    seq = byname["SEQ16.BIN"]
    assert seq.has_header and seq.load_addr == 0x3F00   # SEQ-16 commence en #3F00
    assert fs.read_file("USINE.INS")[:4] == b"SQ16"
    assert len(fs.read_file("USINE.INS")) == 848


def test_cpm22_text_file():
    fs = AmsdosFilesystem(disk("cpm22.dsk"))
    assert len(fs.list_files()) == 24
    assert fs.read_file("LOGO2.SUB").startswith(b"drlkeys\r\nlogo2\r\nfwreset")
    rit = fs.find("RITDEMO.BIN")
    assert rit.has_header and rit.length == 11264


def test_file_sectors_match_blocks():
    fs = AmsdosFilesystem(disk("greed.dsk"))
    f = fs.find("YOGI.BAS")
    secs = fs.file_sectors(f)
    assert len(secs) == 2 * len(f.blocks)
    contents = sorted(fs.disk.get_sector(t, i) for t, i in secs)
    expected = []
    for b in f.blocks:
        blk = fs.read_block(b)
        expected += [blk[:512], blk[512:]]
    assert contents == sorted(expected)


# --------------------------------------------------------------------------- #
# Écriture sur une disquette DATA
# --------------------------------------------------------------------------- #
def test_write_on_seq16_keeps_files(tmp_path):
    """Ajouter un fichier sur seq16.dsk : les autres restent intacts."""
    d = disk("seq16.dsk")
    fs = AmsdosFilesystem(d)
    before = {f.name: fs.read_file(f.name) for f in fs.list_files()}
    payload = bytes(range(256)) * 9
    fs.write_file("TEST.SMP", payload)
    path = os.path.join(tmp_path, "s.dsk")
    d.save(path)
    fs2 = AmsdosFilesystem(ADFDisk.load(path))
    assert fs2.read_file("TEST.SMP") == payload
    for name, data in before.items():
        assert fs2.read_file(name) == data, name


def test_blank_disk_cycle():
    d = ADFDisk.new_blank()
    fs = AmsdosFilesystem(d)
    assert fs.list_files() == []
    assert fs.free_bytes() == 178 * 1024
    assert fs.free_entries() == 64
    fs.write_file("A.BIN", b"a" * 3000)
    fs.write_file("B.BIN", b"b" * 70000)          # 5 extensions
    fs.write_file("C.BIN", b"c" * 10)
    fs.delete_file("A.BIN")
    fs.write_file("D.BIN", b"d" * 2000)           # réutilise les blocs de A
    assert fs.find("D.BIN").blocks[0] == 2
    assert fs.read_file("B.BIN") == b"b" * 70000
    assert fs.read_file("C.BIN") == b"c" * 10
    assert fs.free_entries() == 64 - 1 - 5 - 1


def test_user_areas():
    fs = AmsdosFilesystem(ADFDisk.new_blank())
    fs.write_file("JEU.BAS", b"0", user=0)
    fs.write_file("1:JEU.BAS", b"1")
    names = [f.name for f in fs.list_files()]
    assert names == ["JEU.BAS", "1:JEU.BAS"]
    assert fs.read_file("1:JEU.BAS") == b"1"
    fs.delete_file("1:JEU.BAS")
    assert fs.read_file("JEU.BAS") == b"0"


def test_disk_full():
    fs = AmsdosFilesystem(ADFDisk.new_blank())
    fs.write_file("BIG.BIN", bytes(170 * 1024))
    with pytest.raises(CpcError, match="pleine"):
        fs.write_file("MORE.BIN", bytes(10 * 1024))


# --------------------------------------------------------------------------- #
# Ligne de commande
# --------------------------------------------------------------------------- #
def test_cli_write_list_read(tmp_path, capsys):
    path = str(tmp_path / "t.dsk")
    cli.main(["new", path])
    src = tmp_path / "prog.bin"
    src.write_bytes(b"\xc9" * 300)
    cli.main(["write", path, "PROG.BIN", str(src), "--load", "0x8000"])
    cli.main(["list", path])
    out = capsys.readouterr().out
    assert "PROG.BIN" in out and "0x8000" in out
    dst = tmp_path / "back.bin"
    cli.main(["read", path, "PROG.BIN", "--out", str(dst)])
    assert dst.read_bytes() == b"\xc9" * 300
    with pytest.raises(SystemExit):
        cli.main(["write", path, "PROG.BIN", str(src)])
    cli.main(["write", path, "PROG.BIN", str(src), "--force", "--fs", "raw"])
    fs = AmsdosFilesystem(ADFDisk.load(path))
    assert not fs.find("PROG.BIN").has_header
