"""Tests du module Gotek (préparation clé USB + image FAT16 intégrée)."""

import os
import struct

import pytest

from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.gotek import (
    GotekConfig,
    GotekError,
    create_fat_image,
    list_fat_image,
    prepare_usb_directory,
    verify_usb_directory,
)
from cpc_dsk.gui import _fmt_size, _suggest_83


# --- Mini-lecteur FAT16 (indépendant) pour valider les images produites --- #
def _parse_fat16(img: bytes) -> dict:
    """Lecture structurelle d'une image FAT16 (BPB + FAT + racine + données)."""
    bps = struct.unpack_from("<H", img, 0x0B)[0]
    assert bps == 512
    spc = img[0x0D]
    assert spc == 1
    assert struct.unpack_from("<H", img, 0x0E)[0] == 1   # réservés
    nfats = img[0x10]
    assert nfats == 2
    root_ent = struct.unpack_from("<H", img, 0x11)[0]
    # Convention dosfstools : total est stocké « total − 8 ».
    total = (struct.unpack_from("<H", img, 0x13)[0]
             or struct.unpack_from("<I", img, 0x20)[0]) + 8
    k = struct.unpack_from("<H", img, 0x16)[0]
    assert k > 0, "taille FAT (16 o) doit être renseignée"
    assert img[0x26] == 0x29                       # signature (BPB compact)
    assert img[0x2B:0x36] == b"CPC-GOTEK  "
    assert img[0x36:0x3E] == b"FAT16   "
    assert img[0x1FE:0x200] == b"\x55\xaa"

    fat1 = img[512:512 + k * 512]
    fat2 = img[512 * (1 + k):512 * (1 + k) + k * 512]
    assert fat1 == fat2, "FAT1 et FAT2 doivent être identiques"

    data_start = 1 + 2 * k + (root_ent * 32 + 511) // 512
    n_clusters = total - data_start
    assert len(fat1) >= 2 * (n_clusters + 2)

    def fat16(c):
        return struct.unpack_from("<H", fat1, 2 * c)[0]

    assert fat16(0) == 0xFFF8
    assert fat16(1) == 0xFFFF

    root = img[512 * (1 + 2 * k):512 * (1 + 2 * k) + root_ent * 32]
    files = {}
    for i in range(root_ent):
        ent = root[32 * i:32 * (i + 1)]
        if ent[0] == 0x00:
            break
        if ent[0] == 0xE5:
            continue
        if ent[11] & 0x08:  # entrée VOLUME ID (libellé), pas un fichier
            continue
        name = ent[0:11].decode("latin1").strip()
        base, ext = name[:8].strip(), name[8:11].strip()
        first = struct.unpack_from("<H", ent, 26)[0]
        size = struct.unpack_from("<I", ent, 28)[0]
        # Suis la chaîne de clusters et rassemble les données.
        data = bytearray()
        c = first
        while c < 0xFFF8:
            data += img[512 * (data_start + (c - 2)):
                        512 * (data_start + (c - 2)) + 512]
            c = fat16(c)
        assert c >= 0xFFF8, "chaîne FAT sans fin de chaîne"
        files[f"{base}.{ext}" if ext else base] = bytes(data[:size])
    return {"files": files, "total": total, "k": k, "data_start": data_start}


def test_fat16_image_structure_and_data(tmp_path):
    """Image FAT16 intégrée : BPB valide, FAT chaînée, données intègres."""
    disk = ADFDisk.new_blank()
    disk.save(str(tmp_path / "d1.adf"))
    d2 = ADFDisk.new_blank()
    d2.save(str(tmp_path / "d2.adf"))

    out = str(tmp_path / "cle.img")
    create_fat_image(out, [str(tmp_path / "d1.adf"), str(tmp_path / "d2.adf")],
                     GotekConfig(), size_mb=4)

    img = open(out, "rb").read()
    assert len(img) == 4 * 1024 * 1024
    info = _parse_fat16(img)
    assert set(info["files"]) == {"DISK001.ADF", "DISK002.ADF"}
    expected = open(str(tmp_path / "d1.adf"), "rb").read()
    assert info["files"]["DISK001.ADF"] == expected
    assert info["files"]["DISK002.ADF"] == expected


def test_fat16_image_many_disks(tmp_path):
    """Plusieurs disquettes (chaînes multi-clusters) : tout est récupérable."""
    src = str(tmp_path / "src.adf")
    ADFDisk.new_blank().save(src)
    out = str(tmp_path / "many.img")
    create_fat_image(out, [src] * 8, GotekConfig(), size_mb=8)
    info = _parse_fat16(open(out, "rb").read())
    expected = open(src, "rb").read()
    for i in range(1, 9):
        assert info["files"][f"DISK{i:03d}.ADF"] == expected


def test_fat16_image_too_small(tmp_path):
    with pytest.raises(GotekError):
        create_fat_image(str(tmp_path / "x.img"), [], size_mb=0)


def test_create_fat_image_no_sources(tmp_path):
    out = str(tmp_path / "empty.img")
    create_fat_image(out, [], GotekConfig(), size_mb=4)
    info = _parse_fat16(open(out, "rb").read())
    assert info["files"] == {}


def test_list_fat_image_roundtrip(tmp_path):
    """list_fat_image relit une image produite par create_fat_image."""
    d1 = str(tmp_path / "d1.adf")
    ADFDisk.new_blank().save(d1)
    d2 = str(tmp_path / "d2.adf")
    d2_data = bytes(ADFDisk.new_blank()._raw)
    ADFDisk.new_blank().save(d2)

    out = str(tmp_path / "cle.img")
    create_fat_image(out, [d1, d2], GotekConfig(), size_mb=4)

    files = list_fat_image(out)
    assert [f.name for f in files] == ["DISK001.ADF", "DISK002.ADF"]
    expected = open(d1, "rb").read()
    assert files[0].size == len(expected)
    assert files[0].data == expected
    assert files[1].data == d2_data[:files[1].size]


def test_list_fat_image_many(tmp_path):
    """8 disquettes (chaînes multi-clusters) : tout est récupéré intact."""
    src = str(tmp_path / "src.adf")
    ADFDisk.new_blank().save(src)
    out = str(tmp_path / "many.img")
    create_fat_image(out, [src] * 8, GotekConfig(), size_mb=8)

    files = list_fat_image(out)
    assert [f.name for f in files] == [f"DISK{i:03d}.ADF" for i in range(1, 9)]
    expected = open(src, "rb").read()
    for f in files:
        assert f.size == len(expected)
        assert f.data == expected


def test_list_fat_image_empty(tmp_path):
    out = str(tmp_path / "vide.img")
    create_fat_image(out, [], GotekConfig(), size_mb=4)
    assert list_fat_image(out) == []


def test_list_fat_image_rejects_junk(tmp_path):
    p = str(tmp_path / "junk.img")
    with open(p, "wb") as fh:
        fh.write(b"\x00" * 8192)
    with pytest.raises(GotekError):
        list_fat_image(p)


def test_prepare_and_verify_usb_directory(tmp_path):
    src = str(tmp_path / "src.dsk")
    ADFDisk.new_blank().save(src)
    outdir = str(tmp_path / "usb")
    created = prepare_usb_directory(outdir, [src, src], GotekConfig())
    assert [os.path.basename(c) for c in created] == ["DISK001.adf",
                                                      "DISK002.adf"]
    assert verify_usb_directory(outdir) == created


def test_suggest_83_keeps_extension():
    assert _suggest_83("monprog.bas") == "MONPROG BAS"
    assert _suggest_83("data.bin") == "DATA BIN"
    assert _suggest_83("archive.zip") == "ARCHIVE ZIP"
    assert _suggest_83("noext") == "NOEXT"
    # base 8 + ext 3 : l'extension reste INTACTE (notation espace = 12 o,
    # le champ Filer 8+3 sans séparateur est de 11 o après normalisation).
    assert _suggest_83("longuename.bin") == "LONGUENA BIN"


def test_suggest_83_long_base_keeps_full_extension():
    from cpc_dsk.core.cpcfs import _normalize_83
    # Une base de 8 caractères ne doit pas rogner la 3e lettre de l'extension.
    sug = _suggest_83("programme.bas")
    assert sug == "PROGRAMM BAS"
    # La normalisation donne un champ 8.3 de 11 o, extension complète.
    assert _normalize_83(sug) == "PROGRAMM BAS"[:8].ljust(8) + "BAS"


def test_fmt_size_units_by_language():
    """Régression : _fmt_size appelait ``t(...)`` (non défini au module) →
    NameError au premier affichage de taille (bouton « Ajouter »)."""
    from cpc_dsk.i18n import get_language, set_language
    prev = get_language()
    try:
        set_language("en")
        assert _fmt_size(512) == "512 B"
        assert _fmt_size(2048) == "2.0 KB"
        assert _fmt_size(3 * 1024 * 1024) == "3.0 MB"
        set_language("fr")
        assert _fmt_size(512) == "512 o"
        assert _fmt_size(2048) == "2.0 Ko"
        assert _fmt_size(3 * 1024 * 1024) == "3.0 Mo"
    finally:
        set_language(prev)
