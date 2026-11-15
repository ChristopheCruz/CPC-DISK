"""Tests du conteneur ADF (format EXTENDED CPC DSK)."""

import os

import pytest

from cpc_dsk.core.adf import ADFDisk, ADFError, DISK_INFO_SIZE


def test_new_blank_geometry():
    d = ADFDisk.new_blank()
    assert d.extended is True
    assert d.num_tracks == 40
    assert d.num_sides == 1
    # Bloc piste = 256 (Track-Info) + 9*512 = 4864.
    assert d.track_sizes == [4864] * 40
    # 256 + 40*4864 = 194816 (identique à une disquette CPC réelle).
    assert d.file_size == DISK_INFO_SIZE + 40 * 4864 == 194816


def test_new_blank_is_loadable(tmp_path):
    d = ADFDisk.new_blank()
    p = os.path.join(tmp_path, "v.dsk")
    d.save(p)
    d2 = ADFDisk.load(p)
    assert d2.num_tracks == d.num_tracks
    assert d2.track_sizes == d.track_sizes


def test_save_load_roundtrip_identical(tmp_path):
    d = ADFDisk.new_blank()
    p = os.path.join(tmp_path, "rt.dsk")
    d.save(p)
    d2 = ADFDisk.load(p)
    assert bytes(d2._raw) == bytes(d._raw)


def test_bad_magic_raises():
    with pytest.raises(ADFError):
        ADFDisk(b"NOT A DISK AT ALL" + bytes(300))


def test_sector_roundtrip():
    d = ADFDisk.new_blank()
    payload = bytes(range(256)) * 2  # 512 o
    d.set_sector(3, 5, payload)
    assert d.get_sector(3, 5) == payload
    assert d.get_sector(3, 6) == bytes(512)


def test_sector_size_is_512():
    d = ADFDisk.new_blank()
    assert len(d.get_sector(0, 0)) == 512
    assert d.num_sectors(0) == 9


def test_out_of_bounds():
    d = ADFDisk.new_blank()
    with pytest.raises(ADFError):
        d.get_sector(40, 0)
    with pytest.raises(ADFError):
        d.get_sector(0, 9)


def test_sam_variant_zero_padded_table_and_trailer(tmp_path):
    """Image SAM/WinAPE : tableau des pistes complété à zéro + traînée
    « Offset-Info » après la dernière piste."""
    d = ADFDisk.new_blank(tracks=5)
    raw = bytearray(d._raw)
    raw[0x30] = 7  # 5 pistes réelles + 2 zéros dans le tableau
    trailer = b"Offset-Info\r\n" + bytes(24)
    raw += trailer
    d2 = ADFDisk(bytes(raw))
    assert d2.num_tracks == 5
    assert d2.track_sizes == [4864] * 5
    # La traînée est conservée telle quelle.
    assert bytes(d2._raw)[d2.track_offsets[-1] + 4864:] == trailer
    # Les données de secteurs restent accessibles.
    assert d2.get_sector(0, 0) == bytes(512)
    # Sauvegarde : fichier byte-identique (traînée comprise).
    p = os.path.join(tmp_path, "sam.dsk")
    d2.save(p)
    assert open(p, "rb").read() == bytes(raw)


def test_truncated_file_still_raises():
    d = ADFDisk.new_blank(tracks=5)
    raw = bytes(d._raw)[:-1000]  # coupé au milieu de la dernière piste
    with pytest.raises(ADFError):
        ADFDisk(raw)


# --- Tests optionnels sur de vraies disquettes (si téléchargées) ---
@pytest.mark.skipif(not os.path.exists("/tmp/greed.dsk"),
                    reason="greed.dsk de référence absent")
def test_real_greed_dsk():
    d = ADFDisk.load("/tmp/greed.dsk")
    assert d.extended is True
    assert d.num_tracks == 40
    assert d.file_size == os.path.getsize("/tmp/greed.dsk")


@pytest.mark.skipif(not os.path.exists("/tmp/abbey.dsk"),
                    reason="abbey.dsk de référence absent")
def test_real_abbey_dsk_sam_variant():
    """abbey.dsk : 42 pistes déclarées, 39 réelles + traînée Offset-Info."""
    d = ADFDisk.load("/tmp/abbey.dsk")
    assert d.num_tracks == 39
    assert d.track_sizes[0] == 4864   # piste 0 : 9 × 512 o
    assert d.track_sizes[1] == 4096   # autres : 15 × 256 o
    assert d.num_sectors(0) == 9
    assert d.num_sectors(1) == 15
