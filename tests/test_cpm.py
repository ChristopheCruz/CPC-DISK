"""Tests du module CP/M 2.2 (cpc_dsk.core.cpm).

Couvre : la détection des disques CP/M (disques réels vs Filer vierges),
la génération d'un disque système (Track-Infos identiques à l'octet au
cpm22.dsk réel — validité WinAPE, secteurs système, utilitaires), la
lecture/écriture/suppression du système de fichiers CP/M (répertoire
piste 2, paquet, en-têtes AMSDOS, fichiers « legacy », jeu de
caractères CP/M).
"""

import os

import pytest

from cpc_dsk.core.adf import ADFDisk, TRACK_INFO_SIZE
from cpc_dsk.core.cpcfs import CpcError, CpcFilesystem, FT_BINARY
from cpc_dsk.core.cpm import (
    CPM_CAPACITY,
    CPM_DIR_OFFSET,
    CPM_PACK_START,
    CPM_TRACK_BLOCK_SIZE,
    CPM22_SYSTEM_SIZE,
    BOOT_PREFIX,
    CONFIG_PREFIX,
    CpmFilesystem,
    is_cpm_disk,
    new_cpm_system_disk,
    _reference_bin,
    _sector_by_id,
    CPM_BOOT_ID,
    CPM_CONFIG_ID,
    CPM_SYS1_ID,
    CPM_SYS2_ID,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DISKS = os.path.join(HERE, "..", "test_disks")
CPM22 = os.path.join(DISKS, "cpm22.dsk")
PLANETFALL = os.path.join(DISKS, "planetfall_cpm.dsk")
STARCROSS = os.path.join(DISKS, "starcross_cpm.dsk")
GREED = os.path.join(DISKS, "greed.dsk")
VIERGE = os.path.join(DISKS, "vierge.dsk")


def _track_infos(disk: ADFDisk) -> list:
    return [
        bytes(disk._raw[disk.track_offsets[t]:disk.track_offsets[t] + TRACK_INFO_SIZE])
        for t in range(disk.num_tracks)
    ]


def _cpm22_track_infos() -> list:
    raw = open(CPM22, "rb").read()
    n = raw[0x30]
    offs = []
    off = 256
    for t in range(n):
        offs.append(off)
        off += raw[0x34 + t] * 256
    return [raw[o:o + TRACK_INFO_SIZE] for o in offs]


# --------------------------------------------------------------------------- #
# Détection
# --------------------------------------------------------------------------- #
def test_is_cpm_disk_generated():
    assert is_cpm_disk(new_cpm_system_disk())
    assert is_cpm_disk(new_cpm_system_disk(with_utils=False))


def test_is_cpm_disk_not_cpm():
    assert not is_cpm_disk(ADFDisk.new_blank())
    assert not is_cpm_disk(ADFDisk.new_blank(tracks=10))
    assert not is_cpm_disk(ADFDisk.new_blank(sectors=15, sector_size=256))
    # Filer avec IDs CP/M mais pas de secteurs système : non.
    d = ADFDisk.new_blank(sector_ids=(0x41, 0x46, 0x42, 0x47, 0x43,
                                      0x48, 0x44, 0x49, 0x45), gap3=0x2A)
    assert not is_cpm_disk(d)


@pytest.mark.skipif(not os.path.exists(CPM22),
                    reason="cpm22.dsk de référence absent")
def test_is_cpm_disk_real_disks():
    assert is_cpm_disk(ADFDisk.load(CPM22))
    if os.path.exists(PLANETFALL):
        assert is_cpm_disk(ADFDisk.load(PLANETFALL))
    if os.path.exists(STARCROSS):
        assert is_cpm_disk(ADFDisk.load(STARCROSS))
    if os.path.exists(GREED):
        assert not is_cpm_disk(ADFDisk.load(GREED))
    if os.path.exists(VIERGE):
        assert not is_cpm_disk(ADFDisk.load(VIERGE))


def test_cpm_filesystem_rejects_filer_disk(tmp_path):
    path = os.path.join(tmp_path, "f.dsk")
    ADFDisk.new_blank().save(path)
    with pytest.raises(CpcError):
        CpmFilesystem(ADFDisk.load(path))


# --------------------------------------------------------------------------- #
# Génération du disque système
# --------------------------------------------------------------------------- #
def test_new_cpm_geometry():
    d = new_cpm_system_disk()
    assert d.num_tracks == 40
    assert d.num_sides == 1
    assert all(t == CPM_TRACK_BLOCK_SIZE for t in d.track_sizes)
    assert d.file_size == 256 + 40 * CPM_TRACK_BLOCK_SIZE


@pytest.mark.skipif(not os.path.exists(CPM22),
                    reason="cpm22.dsk de référence absent")
def test_new_cpm_track_infos_byte_equal_cpm22():
    """Les 40 Track-Infos sont identiques à l'octet au cpm22.dsk réel."""
    d = new_cpm_system_disk()
    assert _track_infos(d) == _cpm22_track_infos()


def test_new_cpm_system_sectors():
    """Secteurs système identiques à l'image de référence (par ID)."""
    d = new_cpm_system_disk()
    ref = _reference_bin()
    assert d.file_size >= CPM22_SYSTEM_SIZE
    assert _sector_by_id(d, 0, CPM_BOOT_ID) == ref[0:512]
    assert _sector_by_id(d, 0, CPM_BOOT_ID)[:6] == BOOT_PREFIX
    assert _sector_by_id(d, 0, CPM_CONFIG_ID) == ref[512:1024]
    assert _sector_by_id(d, 0, CPM_CONFIG_ID)[:8] == CONFIG_PREFIX
    assert _sector_by_id(d, 0, CPM_SYS1_ID) == ref[1024:1536]
    assert _sector_by_id(d, 0, CPM_SYS1_ID)[:3] == b"\xC3\x5C\x9A"  # JP &9A5C
    assert _sector_by_id(d, 0, CPM_SYS2_ID) == ref[1536:2048]
    assert d.get_track_data(1) == ref[2048:2048 + 4608]


@pytest.mark.skipif(not os.path.exists(CPM22),
                    reason="cpm22.dsk de référence absent")
def test_new_cpm_track1_byte_equal_cpm22():
    d = new_cpm_system_disk()
    raw = open(CPM22, "rb").read()
    off = 256 + (TRACK_INFO_SIZE + 4608) + TRACK_INFO_SIZE  # données piste 1
    assert d.get_track_data(1) == raw[off:off + 4608]


def test_new_cpm_with_utils():
    d = new_cpm_system_disk()
    fs = CpmFilesystem(d)
    files = fs.list_files()
    assert [f.name for f in files] == [
        "AMSDOS.COM", "DISCKIT2.COM", "LOGO2.COM", "LOGO2.SUB"]
    assert [f.length for f in files] == [1024, 6144, 32768, 128]
    assert all(f.source == "CPM" for f in files)
    # Entrées de répertoire : identiques à la référence (5 entrées × 32 o).
    ref = _reference_bin()
    helper = CpcFilesystem(d)
    assert helper._read_linear(CPM_DIR_OFFSET, 160) == ref[6656:6816]
    # Paquet : identique à la référence (40064 o), puis remplissage 0xE5.
    assert helper._read_linear(CPM_PACK_START, 40064) == \
        ref[6816:CPM22_SYSTEM_SIZE]
    tail = helper._read_linear(CPM_PACK_START + 40064, 512)
    assert all(b == 0xE5 for b in tail)


def test_new_cpm_without_utils():
    d = new_cpm_system_disk(with_utils=False)
    fs = CpmFilesystem(d)
    assert fs.list_files() == []
    assert fs.read_directory() == []
    helper = CpcFilesystem(d)
    # Répertoire et paquet vierges (0xE5).
    assert all(b == 0xE5 for b in helper._read_linear(CPM_DIR_OFFSET, 1536))
    assert all(b == 0xE5
               for b in helper._read_linear(CPM_PACK_START, 4608))


def test_new_cpm_reference_size():
    assert len(_reference_bin()) == CPM22_SYSTEM_SIZE


# --------------------------------------------------------------------------- #
# Lecture des disques réels
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.path.exists(CPM22),
                    reason="cpm22.dsk de référence absent")
def test_cpm22_directory():
    fs = CpmFilesystem(ADFDisk.load(CPM22))
    entries = fs.read_directory()
    assert len(entries) == 27  # 24 fichiers, LOGO2/ROINTIME/DISC.BAS en 2 chunks
    names = [e.name for e in entries]
    assert names[0] == "AMSDOS.COM"
    assert "DISCKIT2.COM" in names
    assert names.count("LOGO2.COM") == 2
    assert names.count("DISC.BAS") == 2
    by_name = {}
    for e in entries:
        by_name.setdefault(e.name, []).append(e)
    assert by_name["AMSDOS.COM"][0].size_units == 8
    assert by_name["AMSDOS.COM"][0].tail_max == 0x02
    assert by_name["DISCKIT2.COM"][0].size_units == 48
    assert [c.chunk_index for c in by_name["LOGO2.COM"]] == [0, 1]
    assert all(c.size_units == 128 for c in by_name["LOGO2.COM"])
    assert by_name["DISC.BAS"][0].size_units == 128
    assert by_name["DISC.BAS"][1].size_units == 40


@pytest.mark.skipif(not os.path.exists(CPM22),
                    reason="cpm22.dsk de référence absent")
def test_cpm22_list_and_read():
    fs = CpmFilesystem(ADFDisk.load(CPM22))
    files = fs.list_files()
    assert len(files) == 24
    assert files[0].name == "AMSDOS.COM"
    assert files[0].type_name == "BIN"
    # Fichiers bruts du paquet : lecture = région allouée.
    assert len(fs.read_file("AMSDOS.COM")) == 1024
    assert len(fs.read_file("DISCKIT2.COM")) == 6144
    # Fichiers « legacy » : contenu réel = objet AMSDOS (longueurs exactes).
    assert len(fs.read_file("RITDEMO.BIN")) == 11264
    assert len(fs.read_file("DISC.BAS")) == 21331
    assert len(fs.read_file("ROINTIME.DEM")) == 26624
    # Pas de doublon : les 3 objets AMSDOS sont réclamés par le répertoire.
    assert [f.name for f in fs.list_files(source="amsdos")] == \
        ["RITDEMO BIN", "RITDEMO BIN", "DISC    BAS"]


@pytest.mark.skipif(not os.path.exists(PLANETFALL),
                    reason="planetfall_cpm.dsk de référence absent")
def test_planetfall_cpm_charset():
    """Noms en jeu de caractères CP/M (0xC1..0xD6 = A..Z)."""
    fs = CpmFilesystem(ADFDisk.load(PLANETFALL))
    files = fs.list_files()
    assert [f.name for f in files] == [
        "PLANET.COM", "PLAN64.COM", "PLAN128.COM", "PLAN256.COM",
        "PLANETFA.DAT"]
    assert files[0].length == 256
    # PLANETFA.DAT : 7 chunks (2 × ... ) — 856 unités au total.
    assert files[4].length == 856 * 128
    data = fs.read_file("PLANET.COM")
    assert len(data) == 256


@pytest.mark.skipif(not os.path.exists(STARCROSS),
                    reason="starcross_cpm.dsk de référence absent")
def test_starcross():
    fs = CpmFilesystem(ADFDisk.load(STARCROSS))
    files = fs.list_files()
    assert [f.name for f in files] == ["STARCROS.COM", "STARCROS.DAT"]
    assert files[0].length == 8192


@pytest.mark.skipif(not os.path.exists(CPM22),
                    reason="cpm22.dsk de référence absent")
def test_cpm22_delete_legacy():
    d = ADFDisk.load(CPM22)
    fs = CpmFilesystem(d)
    fs.delete_file("RITDEMO.BIN")
    assert "RITDEMO.BIN" not in [f.name for f in fs.list_files()]
    # Les deux objets AMSDOS « RITDEMO » sont mis à zéro.
    assert [f.name for f in fs.list_files(source="amsdos")] == ["DISC    BAS"]


# --------------------------------------------------------------------------- #
# Écriture / suppression (disque généré)
# --------------------------------------------------------------------------- #
def _disk():
    return new_cpm_system_disk()


def test_cpm_write_read_roundtrip():
    d = _disk()
    fs = CpmFilesystem(d)
    payload = bytes(range(256)) * 7  # 1792 o
    f = fs.write_file("HELLO.BIN", payload, load_addr=0x4000)
    assert f.name == "HELLO.BIN"
    assert f.source == "CPM"
    assert f.length == len(payload)
    assert fs.read_file("HELLO.BIN") == payload
    assert "HELLO.BIN" in [x.name for x in fs.list_files()]


def test_cpm_write_name_11_chars_dotted():
    """Nom 11 caractères ponctué (cas RITDEMO.BIN)."""
    d = _disk()
    fs = CpmFilesystem(d)
    fs.write_file("RITDEMO.BIN", b"legacy test data")
    assert fs.read_file("RITDEMO.BIN") == b"legacy test data"
    assert fs.read_file("RITDEMO BIN") == b"legacy test data"


def test_cpm_write_multichunk_and_counter():
    """Fichier > 16 Ko : 2 chunks, compteur d'allocation continué."""
    d = _disk()
    fs = CpmFilesystem(d)
    payload = bytes(20000)
    fs.write_file("BIGFILE.BIN", payload)
    assert fs.read_file("BIGFILE.BIN") == payload
    entries = fs.read_directory()
    big = [e for e in entries if e.name == "BIGFILE.BIN"]
    assert [e.chunk_index for e in big] == [0, 1]
    assert big[0].size_units == 128  # 16 Ko
    assert big[1].size_units == (20000 + 128 + 127) // 128 - 128
    # Compteur continué après le maximum du disque de référence (0x29).
    assert big[0].tail_max >= 0x2A
    # Octets de compteur consécutifs d'un chunk à l'autre.
    helper = CpcFilesystem(d)
    raw = helper._read_linear(CPM_DIR_OFFSET, 1536)
    e0 = raw[big[0].slot * 32:(big[0].slot + 1) * 32]
    e1 = raw[big[1].slot * 32:(big[1].slot + 1) * 32]
    n0 = (e0[0x0F] * 128 + 1023) // 1024
    assert e1[0x10] == (e0[0x10 + n0 - 1] + 1) & 0xFF


def test_cpm_write_amsdos_mode():
    d = _disk()
    fs = CpmFilesystem(d)
    f = fs.write_file("HIDDEN.BIN", b"secret", mode="amsdos")
    assert f.source == "AMSDOS"
    assert "HIDDEN.BIN" not in [x.name for x in fs.list_files(source="cpm")]
    # Le scan AMSDOS restitue le nom du champ d'en-tête (séparateur espace).
    assert any("HIDDEN" in x.name
               for x in fs.list_files(source="amsdos"))
    assert fs.read_file("HIDDEN.BIN") == b"secret"
    # Le disque reste lisible en CP/M (le système n'est pas touché).
    assert len(fs.read_file("AMSDOS.COM")) == 1024


def test_cpm_delete():
    d = _disk()
    fs = CpmFilesystem(d)
    fs.write_file("TEMP.BIN", b"t" * 500)
    fs.delete_file("TEMP.BIN")
    assert "TEMP.BIN" not in [x.name for x in fs.list_files()]
    assert "TEMP.BIN" not in [x.name for x in fs.list_files(source="amsdos")]
    # L'espace libéré est réutilisable.
    fs.write_file("REUSE.BIN", b"ok")
    assert fs.read_file("REUSE.BIN") == b"ok"
    # Les utilitaires initiaux sont intacts.
    assert len(fs.read_file("DISCKIT2.COM")) == 6144


def test_cpm_write_errors():
    d = _disk()
    fs = CpmFilesystem(d)
    with pytest.raises(CpcError):
        fs.write_file("AMSDOS.COM", b"dup")
    with pytest.raises(CpcError):
        fs.write_file("EMPTY.BIN", b"")
    with pytest.raises(CpcError):
        fs.write_file("X.BIN", b"x", mode="both")


def test_cpm_save_reload(tmp_path):
    d = _disk()
    fs = CpmFilesystem(d)
    fs.write_file("KEPT.BIN", b"keep me")
    path = os.path.join(tmp_path, "cpm.dsk")
    d.save(path)
    d2 = ADFDisk.load(path)
    assert is_cpm_disk(d2)
    fs2 = CpmFilesystem(d2)
    assert [f.name for f in fs2.list_files()] == [
        "AMSDOS.COM", "DISCKIT2.COM", "LOGO2.COM", "LOGO2.SUB", "KEPT.BIN"]
    assert fs2.read_file("KEPT.BIN") == b"keep me"
    assert len(fs2.read_file("LOGO2.COM")) == 32768


def test_cpm_delete_not_found():
    d = _disk()
    fs = CpmFilesystem(d)
    with pytest.raises(CpcError):
        fs.delete_file("NOPE.BIN")
    with pytest.raises(CpcError):
        fs.read_file("NOPE.BIN")
