"""Tests du répertoire Filer (DOS CPC d'origine) — lecture et écriture."""

import os

import pytest

from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.cpcfs import (
    AMSDOS_HEADER_SIZE,
    DIR_EMPTY_ENTRY,
    DIR_ENTRY_SIZE,
    CpcError,
    CpcFilesystem,
    FT_BASIC,
    FT_BINARY,
)

GREED = "/tmp/greed.dsk"
ROBOT = "/tmp/robot.dsk"


def _save_reload(disk, tmp_path, name="x.dsk") -> ADFDisk:
    path = os.path.join(tmp_path, name)
    disk.save(path)
    return ADFDisk.load(path)


def test_filer_write_read_roundtrip(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    prog = b'10 PRINT "HELLO"\n20 GOTO 10\n'
    fs.write_file("TEST    BAS", prog, file_type=FT_BASIC, mode="filer")
    d2 = _save_reload(d, tmp_path)
    fs2 = CpcFilesystem(d2)
    # Lecture Filer = région allouée (arrondie au multiple de 128 o).
    data = fs2.read_file("TEST    BAS", source="filer")
    units = (len(prog) + 127) // 128
    assert data == prog + bytes(units * 128 - len(prog))
    assert len(data) == units * 128


def test_filer_directory_entry_layout(tmp_path):
    d = ADFDisk.new_blank()
    CpcFilesystem(d).write_file("TEST    BAS", b"x" * 100, mode="filer")
    sec = d.get_sector(0, 0)
    e = sec[:DIR_ENTRY_SIZE]
    # Champ de nom (8.3) avec 0x00 initial, chunk 0, [13:15] = 0, [15] = 1 unité.
    assert e[0] == 0
    assert e[1:12] == b"TEST    BAS"
    assert e[12] == 0
    assert e[13:15] == b"\x00\x00"
    assert e[15] == 1
    # Queue : ceil(128/1024) = 1 octet de compteur, premier = 0x02.
    assert e[16] == 0x02
    assert e[17:32] == b"\x00" * 15
    # Entrées suivantes vides (zéro sur disquette vierge).
    assert sec[DIR_ENTRY_SIZE:] == b"\x00" * (512 - DIR_ENTRY_SIZE)
    # Données au début du paquet : secteur 1 de la piste 0.
    assert d.get_sector(0, 1)[:100] == b"x" * 100


def test_filer_both_layers(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    data = b"0123456789" * 3
    fs.write_file("DUAL    BIN", data, file_type=FT_BINARY, mode="both")
    d2 = _save_reload(d, tmp_path)
    fs2 = CpcFilesystem(d2)
    # La lecture automatique préfère AMSDOS (longueur exacte).
    assert fs2.read_file("DUAL    BIN") == data
    assert fs2.read_file("DUAL    BIN", source="amsdos") == data
    units = (len(data) + 127) // 128
    assert fs2.read_file("DUAL    BIN", source="filer") == \
        data + bytes(units * 128 - len(data))
    # Les deux couches sont listées.
    sources = {f.source for f in fs2.list_files()
               if f.name == "DUAL    BIN"}
    assert sources == {"FILER", "AMSDOS"}


def test_filer_chunking_16k(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("BIG     BIN", b"\xAB" * 20000, mode="filer")
    entries = fs.read_directory()
    assert [e.chunk_index for e in entries] == [0, 1]
    assert [e.size_units for e in entries] == [128, 29]
    # Compteur continu : 16 valeurs (16 Ko) puis ceil(29*128/1024) = 4.
    assert entries[0].tail_max == 0x02 + 16 - 1
    assert entries[1].tail_max == 0x02 + 16 + 4 - 1
    files = fs.list_directory_files()
    assert files[0].length == 157 * 128  # 20096 o


def test_filer_16k_boundary_single_entry(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("EDGE    BIN", b"\x00" * 16384, mode="filer")
    entries = fs.read_directory()
    assert len(entries) == 1
    assert entries[0].size_units == 0x80


def test_filer_directory_full(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    for i in range(16):
        fs.write_file(f"F{i:02d}    BIN", b"z", mode="filer")
    with pytest.raises(CpcError):
        fs.write_file("F16     BIN", b"z", mode="filer")


def test_filer_delete_and_repack(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("AAA     BIN", b"A" * 100, mode="filer")
    fs.write_file("BBB     BIN", b"B" * 300, mode="filer")
    fs.write_file("CCC     BIN", b"C" * 500, mode="filer")
    # Position initiale : paquet depuis 0x400 (AAA arrondi à 128 o).
    off_a = 0x400
    fs.delete_file("BBB     BIN")
    d2 = _save_reload(d, tmp_path)
    fs2 = CpcFilesystem(d2)
    files = fs2.list_directory_files()
    assert [f.name for f in files] == ["AAA     BIN", "CCC     BIN"]
    # CCC a recollé juste derrière AAA.
    assert files[1].offset == off_a + 128
    assert fs2.read_file("CCC     BIN", source="filer")[:500] == b"C" * 500
    assert fs2.find("BBB     BIN", source="filer") is None
    # Entrée supprimée = 0xE5.
    sec = d2.get_sector(0, 0)
    assert sec[DIR_ENTRY_SIZE:2 * DIR_ENTRY_SIZE] == DIR_EMPTY_ENTRY


def test_filer_delete_slot_reuse(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("AAA     BIN", b"A" * 100, mode="filer")
    fs.write_file("BBB     BIN", b"B" * 100, mode="filer")
    fs.write_file("CCC     BIN", b"C" * 100, mode="filer")
    fs.delete_file("BBB     BIN")
    fs.write_file("DDD     BIN", b"D" * 100, mode="filer")
    # DDD réutilise le slot 1 (après AAA, avant CCC).
    entries = fs.read_directory()
    assert [e.name for e in entries] == ["AAA     BIN", "DDD     BIN",
                                         "CCC     BIN"]
    files = fs.list_directory_files()
    base = 0x400
    assert [f.offset for f in files] == [base, base + 128, base + 256]
    assert fs.read_file("DDD     BIN", source="filer")[:100] == b"D" * 100
    assert fs.read_file("CCC     BIN", source="filer")[:100] == b"C" * 100


def test_name_dot_encoding(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("YOGI1.B.N", b"123", mode="filer")
    sec = d.get_sector(0, 0)
    assert sec[1:12] == b"YOGI1   B\xc9N"
    names = [f.name for f in fs.list_directory_files()]
    assert names == ["YOGI1   B.N"]
    # Recherche par les deux notations (point / espace).
    assert fs.find("yogi1 b.n") is not None
    assert fs.find("YOGI1.B.N") is not None
    assert fs.read_file("YOGI1 B.N", source="filer")[:3] == b"123"


def test_filer_only_no_amsdos_object(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("PURE    BIN", b"\x11\x22\x33" * 40, mode="filer")
    assert all(f.name != "PURE    BIN" for f in fs._scan_amsdos())


def test_amsdos_end_stack(tmp_path):
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    fs.write_file("ONE     BIN", b"x" * 100, mode="amsdos")
    fs.write_file("TWO     BIN", b"y" * 200, mode="amsdos")
    one = fs.find("ONE     BIN", source="amsdos")
    two = fs.find("TWO     BIN", source="amsdos")
    # TWO (écrit en second) est juste avant ONE (pile descendante).
    assert two.offset + AMSDOS_HEADER_SIZE + 200 == one.offset


def test_write_rejects_ambiguous_disk():
    # Un disque dont le paquet Filer contient des objets AMSDOS (disques
    # réels d'époque) doit être protégé contre la réorganisation Filer.
    for path in (GREED, ROBOT):
        if not os.path.exists(path):
            pytest.skip("disque de référence absent")
        d = ADFDisk.load(path)
        fs = CpcFilesystem(d)
        with pytest.raises(CpcError):
            fs.write_file("NOUVEAU BIN", b"abc", mode="filer")
        # La lecture reste possible.
        assert len(fs.list_files()) > 0


# --- Tests optionnels sur les disquettes de référence ---
@pytest.mark.skipif(not os.path.exists(GREED),
                    reason="greed.dsk de référence absent")
def test_real_greed_directory():
    d = ADFDisk.load(GREED)
    fs = CpcFilesystem(d)
    files = fs.list_directory_files()
    assert [(f.name, f.length) for f in files] == [
        ("YOGI    BAS", 768),
        ("YOGI1   B.N", 25344),
        ("YOGI2   B.N", 40960),
        ("YOGI3   B.N", 7680),
    ]
    assert files[0].offset == 0x400
    # Le premier fichier (code) est bien au secteur 1 de la piste 0.
    assert bytes(d._raw[0x400:0x400 + 8]) == b"\x00T\xa8ET\xa8\xfc\xfc"
    # 7 entrées (YOGI1 et YOGI2 sont en 2 et 3 chunks).
    assert len(fs.read_directory()) == 7


@pytest.mark.skipif(not os.path.exists(ROBOT),
                    reason="robot.dsk de référence absent")
def test_real_robot_directory():
    d = ADFDisk.load(ROBOT)
    fs = CpcFilesystem(d)
    files = fs.list_directory_files()
    assert len(files) == 10
    assert files[0].name == "LARA    DOC"
    assert files[0].offset == 0x400
    assert files[0].length == 16384 + 16384 + 12544
    entries = fs.read_directory()
    assert len(entries) == 12
    # Le compteur d'allocation couvre 0x02..0x81 (128 unités de 1 Ko).
    assert max(e.tail_max for e in entries) == 0x81
    # LARA BAS : 8 unités (787 o de données + remplissage).
    bas = [e for e in entries if e.name == "LARA    BAS"]
    assert [e.size_units for e in bas] == [8]
