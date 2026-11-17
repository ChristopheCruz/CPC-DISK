"""Tests du conteneur ADF (format EXTENDED CPC DSK)."""

import os

import pytest

from cpc_dsk.core.adf import (
    ADFDisk,
    ADFError,
    DISK_INFO_SIZE,
    TRACK_INFO_NUM_SECTORS_OFFSET,
)


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
    assert d.get_sector(3, 6) == b"\xE5" * 512  # vierge = remplissage formatage


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
    assert d2.get_sector(0, 0) == b"\xE5" * 512
    # Sauvegarde : fichier byte-identique (traînée comprise).
    p = os.path.join(tmp_path, "sam.dsk")
    d2.save(p)
    assert open(p, "rb").read() == bytes(raw)


def test_truncated_file_still_raises():
    d = ADFDisk.new_blank(tracks=5)
    raw = bytes(d._raw)[:-1000]  # coupé au milieu de la dernière piste
    with pytest.raises(ADFError):
        ADFDisk(raw)


def test_new_blank_track_info_matches_real_disks():
    """Track-Info de new_blank : structure des disquettes réelles
    (ce que WinAPE valide à l'ouverture — « invalid track sizes » sinon)."""
    d = ADFDisk.new_blank()
    raw = d._raw
    for t in (0, 1, 39):
        off = d.track_offsets[t]
        ti = raw[off:off + 256]
        assert ti[:12] == b"Track-Info\r\n"
        assert ti[0x14] == 2          # taille de secteur 128<<2 = 512 o
        assert ti[0x15] == 9          # 9 secteurs
        assert ti[0x17] == 0xE5       # octet de remplissage
        for i in range(9):
            rec = ti[0x18 + i * 8: 0x18 + i * 8 + 8]
            assert rec[0] == t        # cylindre
            assert rec[3] == 2        # code taille
            assert rec[6] | (rec[7] << 8) == 512
    # Ordre physique réel des IDs de secteurs (pistes réelles : C1 C6 C2 …).
    ti0 = raw[d.track_offsets[0]: d.track_offsets[0] + 256]
    assert [ti0[0x18 + i * 8 + 2] for i in range(9)] == [
        0xC1, 0xC6, 0xC2, 0xC7, 0xC3, 0xC8, 0xC4, 0xC9, 0xC5]
    # Piste vierge remplie à 0xE5 (formatage réel, répertoire Filer compris).
    assert d.get_track_data(0) == b"\xE5" * 4608


def test_new_blank_track_info_byte_equal_greed():
    """Track-Info[0] byte-par-byte identique à greed.dsk (référence réelle)."""
    ref = os.path.join(os.path.dirname(__file__), "..", "test_disks",
                       "greed.dsk")
    if not os.path.exists(ref):
        pytest.skip("greed.dsk absent")
    real = open(ref, "rb").read()
    gen = ADFDisk.new_blank()
    off = gen.track_offsets[0]
    assert real[256:256 + 256] == bytes(gen._raw[off:off + 256])


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


SOOTY = os.path.join(os.path.dirname(__file__), "..", "test_disks",
                     "sooty.dsk")


@pytest.mark.skipif(not os.path.exists(SOOTY),
                    reason="sooty.dsk de référence absent")
def test_real_sooty_mixed_geometry():
    """sooty.dsk (CPCDiskXP) : 40 pistes 9×512 + 2 pistes Track-Info seules
    (table = 0x01, 256 o, 0 secteur) — géométrie mixte tolérée."""
    d = ADFDisk.load(SOOTY)
    assert d.num_tracks == 42
    assert d.track_sizes[:40] == [4864] * 40
    assert d.track_sizes[40:] == [256, 256]
    assert d.num_sectors(0) == 9
    assert d.num_sectors(41) == 0
    assert d.get_track_data(41) == b""
    assert d.file_size == os.path.getsize(SOOTY)
    # Piste 41 : Track-Info seul (0x15 = 0 secteur).
    ti = bytes(d._raw[d.track_offsets[41]:d.track_offsets[41] + 256])
    assert ti[TRACK_INFO_NUM_SECTORS_OFFSET] == 0


def test_sum_geometry_i18n():
    """Barre d'info (sum_geometry) : localisée en en/fr/es, valeurs intactes.

    Régression : la barre d'info affichait ``disk.summary()`` (français
    durci) dans les trois langues ; la GUI passe par la clé i18n.
    """
    from cpc_dsk.i18n import LANGUAGES, get_language, set_language, t
    prev = get_language()
    try:
        d = ADFDisk.new_blank()
        for lang in LANGUAGES:
            set_language(lang)
            s = t("sum_geometry",
                  fmt="Extended" if d.extended else "Standard",
                  tracks=d.num_tracks, sides=d.num_sides,
                  n=d.file_size, sizes=sorted(set(d.track_sizes)))
            # Les valeurs géométriques sont présentes dans toutes les langues.
            assert "Extended" in s
            assert str(d.num_tracks) in s
            assert str(d.file_size) in s
        # Le français conserve la formulation technique d'origine.
        set_language("fr")
        fr = t("sum_geometry", fmt="Extended", tracks=40, sides=1,
               n=194816, sizes=[4864])
        assert fr == ("format=Extended pistes=40 faces=1 "
                      "taille_fichier=194816 o tailles_pistes=[4864]")
        # L'anglais n'est plus français (plus de « pistes »/« faces »).
        set_language("en")
        en = t("sum_geometry", fmt="Extended", tracks=40, sides=1,
               n=194816, sizes=[4864])
        assert "pistes" not in en and "faces" not in en
        assert "tracks=40" in en and "sides=1" in en
        assert "file_size=194816 B" in en
    finally:
        set_language(prev)
