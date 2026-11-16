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


def _all_track_headers_intact(d: ADFDisk) -> bool:
    raw = bytes(d._raw)
    return all(raw[t:t + 12] == b"Track-Info\r\n"
               for t in d.track_offsets)


def test_linear_space_crosses_tracks():
    """Écriture/lecture à une position profonde (au-delà de la 1re piste)
    doivent atterrir exactement à l'offset d'image attendu."""
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    cap = fs._capacity()
    data = bytes((i * 7) & 0xFF for i in range(5000))  # traverse 2+ pistes
    fs._write_linear(cap - 5000, data)
    assert fs._read_linear(cap - 5000, 5000) == data
    # Position d'image exacte (pas « piste 1 + 0 »).
    img = fs._linear_to_image(cap - 5000)
    assert bytes(d._raw)[img] == data[0]
    assert _all_track_headers_intact(d)
    # Lecture partielle à cheval sur la fin de piste.
    assert fs._read_linear(cap - 40, 40) == data[5000 - 40:]


def test_amsdos_object_crosses_tracks(tmp_path):
    """Objet AMSDOS plus grand qu'une piste : écriture en flux physique
    (en-têtes Track-Info intacts), aller-retour, ajout d'un 2e fichier
    (régression : l'ajout suivant l'écriture d'un gros fichier échouait),
    suppression."""
    d = ADFDisk.new_blank()
    fs = CpcFilesystem(d)
    payload = bytes(range(256)) * 79  # 20224 o > 4608 o (une piste)
    f = fs.write_file("GROS    BIN", payload, file_type=FT_BINARY,
                      load_addr=0x9000, mode="amsdos")
    assert _all_track_headers_intact(d)
    assert f.offset == fs._linear_to_image(fs._image_to_linear(f.offset))
    assert fs.read_file("GROS    BIN") == payload

    # Un deuxième fichier doit pouvoir s'ajouter ensuite.
    fs.write_file("DEUX    BAS", b"10 PRINT 1\n", file_type=FT_BASIC,
                  load_addr=0x4000, mode="amsdos")
    assert fs.read_file("DEUX    BAS") == b"10 PRINT 1\n"
    assert fs.read_file("GROS    BIN") == payload
    assert _all_track_headers_intact(d)

    # Suppression : le grand fichier disparaît, l'autre reste.
    d.save(os.path.join(tmp_path, "g.dsk"))
    fs2 = CpcFilesystem(ADFDisk.load(os.path.join(tmp_path, "g.dsk")))
    fs2.delete_file("GROS    BIN")
    assert "GROS    BIN" not in {f.name for f in fs2.list_files(source="amsdos")}
    assert fs2.read_file("DEUX    BAS") == b"10 PRINT 1\n"


# --- Tests optionnels sur de vraies disquettes ---
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


@pytest.mark.skipif(not os.path.exists("/tmp/greed.dsk"),
                    reason="greed.dsk de référence absent")
def test_real_greed_amsdos_physical_read():
    """Lecture AMSDOS = flux physique : les données extraites ne peuvent
    contenir les en-têtes Track-Info du conteneur (la lecture dans
    l'image brute en contenait 6 pour YOGI1 BIN, 25 192 o traversant
    5 pistes)."""
    fs = CpcFilesystem(ADFDisk.load("/tmp/greed.dsk"))
    expected = {"YOGI    BAS": 631, "YOGI1   BIN": 25192,
                "YOGI2   BIN": 40832, "YOGI3   BIN": 7552}
    for name, length in expected.items():
        data = fs.read_file(name, source="amsdos")
        assert len(data) == length
        assert b"Track-Info\r\n" not in data, name


_DISKS = os.path.join(os.path.dirname(__file__), "..", "test_disks")


def _disk(name: str) -> str:
    return os.path.join(_DISKS, name)


@pytest.mark.skipif(not os.path.exists(_disk("sooty.dsk")),
                    reason="sooty.dsk de référence absent")
def test_real_sooty_amsdos_only():
    """sooty.dsk : pas de répertoire Filer exploitable, 5 objets AMSDOS
    (dont des doublons de nom) sur une géométrie mixte 42 pistes."""
    fs = CpcFilesystem(ADFDisk.load(_disk("sooty.dsk")))
    files = fs.list_files()
    assert len(files) == 5
    assert all(f.source == "AMSDOS" for f in files)
    lengths = {f.name: f.length for f in files}
    assert lengths["DISK    BIN"] == 403
    assert lengths["SCREEN  DL"] == 370
    data = fs.read_file("DISK    BIN", source="amsdos")
    assert len(data) == 403
    assert any(b != 0xE5 for b in data)


@pytest.mark.skipif(not os.path.exists(_disk("compilation190.dsk")),
                    reason="compilation190.dsk de référence absent")
def test_real_compilation190():
    """compilation190.dsk (CPDRead) : 11 fichiers Filer + 17 objets AMSDOS
    (deux jeux : Arkano, Cyber) — les deux couches coexistent."""
    fs = CpcFilesystem(ADFDisk.load(_disk("compilation190.dsk")))
    filer = fs.list_files(source="filer")
    amsdos = fs.list_files(source="amsdos")
    assert len(filer) == 11
    assert len(amsdos) == 17
    # Fichier Filer > 16 Ko (2 chunks).
    data = fs.read_file("ARKANO  BIN", source="filer")
    assert len(data) == 35712
    assert any(b != 0xE5 for b in data)
    # Fichier AMSDOS BASIC (longueur exacte, premier octet = longueur).
    basic = fs.read_file("GRUGEUR BAS", source="amsdos")
    assert len(basic) == 1743
    # « A BAS » existe dans les deux couches : lecture par défaut = AMSDOS
    # (métadonnées complètes), 186 o contre 384 o en région Filer.
    assert len(fs.read_file("A BAS")) == 186
    assert len(fs.read_file("A BAS", source="filer")) == 384
