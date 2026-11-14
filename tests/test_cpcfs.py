"""Tests du système de fichiers CPC (fichiers AMSDOS)."""

import os

import pytest

from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.cpcfs import (
    CpcError,
    CpcFilesystem,
    FT_BASIC,
    FT_BINARY,
)


def test_write_read_roundtrip(tmp_path):
    d = ADFDisk.new_blank()
    p = os.path.join(tmp_path, "x.dsk")
    d.save(p)

    prog = b'10 PRINT "HELLO CPC"\n20 GOTO 10\n'
    CpcFilesystem(d).write_file("TEST    BAS", prog, file_type=FT_BASIC)
    d.save(p)

    d2 = ADFDisk.load(p)
    fs = CpcFilesystem(d2)
    assert fs.read_file("TEST    BAS") == prog


def test_list_files(tmp_path):
    d = ADFDisk.new_blank()
    p = os.path.join(tmp_path, "l.dsk")
    d.save(p)
    fs = CpcFilesystem(d)
    fs.write_file("AAA     BIN", b"\x01\x02\x03", file_type=FT_BINARY)
    fs.write_file("BBB     BAS", b'10 REM hi\n', file_type=FT_BASIC)
    d.save(p)

    names = {f.name for f in CpcFilesystem(ADFDisk.load(p)).list_files()}
    assert "AAA     BIN" in names
    assert "BBB     BAS" in names


def test_read_missing_raises():
    d = ADFDisk.new_blank()
    with pytest.raises(CpcError):
        CpcFilesystem(d).read_file("NOPE    BIN")


def test_write_duplicate_raises(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("DUP     BIN", b"xx")
    with pytest.raises(CpcError):
        fs.write_file("DUP     BIN", b"yy")


def test_file_metadata():
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    f = fs.write_file("META    BIN", b"0123456789", file_type=FT_BINARY,
                      load_addr=0x4000)
    assert f.name == "META    BIN"
    assert f.length == 10
    assert f.file_type == FT_BINARY
    assert f.load_addr == 0x4000
    assert f.type_name == "BIN"


# --- Test optionnel sur une vraie disquette ---
@pytest.mark.skipif(not os.path.exists("/tmp/greed.dsk"),
                    reason="greed.dsk de référence absent")
def test_real_greed_files():
    d = ADFDisk.load("/tmp/greed.dsk")
    fs = CpcFilesystem(d)
    files = fs.list_files()
    names = {f.name for f in files}
    assert "YOGI    BAS" in names
    assert "YOGI1   BIN" in names
    # Le fichier BASIC doit être lisible.
    assert len(fs.read_file("YOGI    BAS")) > 0
    # Le répertoire (vue secondaire) doit lister des noms.
    assert len(fs.read_directory_names()) > 0
