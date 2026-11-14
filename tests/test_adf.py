"""Tests du noyau ADF : géométrie, encodage, aller-retour disque."""

import os
import tempfile

import pytest

from cpc_dsk.core import geometry
from cpc_dsk.core.adf import ADFDisk, ADFError, SECTOR_RECORD_SIZE


def test_geometry_capacity():
    assert geometry.DATA_CAPACITY == 40 * 2 * 10 * 256
    assert geometry.DATA_CAPACITY == 204800


def test_new_blank_disk_properties():
    disk = ADFDisk.new_blank()
    assert disk.tracks == 40
    assert disk.sides == 2
    assert disk.sectors_per_track == 10
    assert disk.sector_size == 256
    assert disk.total_sectors == 800
    assert disk.data_capacity == 204800
    # Taille fichier attendue: en-tête (40) + 800 secteurs * 270 octets.
    assert disk.expected_file_size() == 40 + 800 * 270


def test_sector_roundtrip_in_memory():
    disk = ADFDisk.new_blank()
    payload = bytes(range(256))
    disk.set_sector(5, 1, 3, payload)
    assert disk.get_sector(5, 1, 3) == payload
    # Les autres secteurs restent vierges (à zéro).
    assert disk.get_sector(5, 1, 4) == bytes(256)


def test_set_sector_wrong_size_raises():
    disk = ADFDisk.new_blank()
    with pytest.raises(ADFError):
        disk.set_sector(0, 0, 0, b"trop court")


def test_out_of_bounds_address_raises():
    disk = ADFDisk.new_blank()
    with pytest.raises(ADFError):
        disk.get_sector(40, 0, 0)      # piste hors bornes
    with pytest.raises(ADFError):
        disk.get_sector(0, 2, 0)       # face hors bornes
    with pytest.raises(ADFError):
        disk.get_sector(0, 0, 10)      # secteur hors bornes


def test_save_load_roundtrip(tmp_path):
    disk = ADFDisk.new_blank()
    # On remplit quelques secteurs avec des motifs connus.
    for i, (t, s, sec) in enumerate([(0, 0, 0), (0, 0, 1), (39, 1, 9), (10, 1, 5)]):
        disk.set_sector(t, s, sec, bytes([i] * 256))

    path = os.path.join(tmp_path, "test.dsk")
    disk.save(path)

    assert os.path.exists(path)
    with open(path, "rb") as fh:
        size = os.path.getsize(path)
    assert size == disk.expected_file_size()

    loaded = ADFDisk.load(path)
    assert (loaded.tracks, loaded.sides, loaded.sectors_per_track) == (40, 2, 10)
    # Vérifie la persistance des motifs.
    for i, (t, s, sec) in enumerate([(0, 0, 0), (0, 0, 1), (39, 1, 9), (10, 1, 5)]):
        assert loaded.get_sector(t, s, sec) == bytes([i] * 256)
    # Un secteur non écrit doit revenir à zéro.
    assert loaded.get_sector(20, 0, 0) == bytes(256)


def test_load_bad_signature_raises(tmp_path):
    path = os.path.join(tmp_path, "bad.dsk")
    with open(path, "wb") as fh:
        fh.write(b"NOTADISK" + bytes(100))
    with pytest.raises(ADFError):
        ADFDisk.load(path)


def test_iter_sectors_count():
    disk = ADFDisk.new_blank()
    count = sum(1 for _ in disk.iter_sectors())
    assert count == 800


def test_single_track_disk_custom_geometry():
    disk = ADFDisk(tracks=1, sides=1, sectors_per_track=5, sector_size=128)
    assert disk.total_sectors == 5
    assert disk.data_capacity == 640
