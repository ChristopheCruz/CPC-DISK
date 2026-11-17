"""Refait cpc_dsk/data/cpm22_system.bin à partir de test_disks/cpm22.dsk.

Contenu du fichier produit :

    0      512   secteur &41 (boot)
    512    512   secteur &42 (configuration)
    1024   512   secteur &48 (CP/M, partie 1)
    1536   512   secteur &49 (CP/M, partie 2)
    2048   4608  piste 1 entière (CCP + BDOS), ordre physique
    6656   ...   utilitaires : pour chacun, nom 8+3 (11 o), longueur (LE32),
                 puis les données telles qu'au catalogue

Les utilitaires sont lus par le catalogue CP/M (blocs de 1 Ko), et non
par position physique : l'entrelacement des secteurs n'a donc pas d'effet.

    python scripts/make_cpm_reference.py
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cpc_dsk.core.adf import ADFDisk  # noqa: E402
from cpc_dsk.core.amsdos import AmsdosFilesystem, to_field11  # noqa: E402
from cpc_dsk.core.cpm import _sector_by_id  # noqa: E402

UTILS = ("AMSDOS.COM", "DISCKIT2.COM", "LOGO2.COM", "LOGO2.SUB")


def main() -> None:
    disk = ADFDisk.load(os.path.join(ROOT, "test_disks", "cpm22.dsk"))
    out = bytearray()
    for sid in (0x41, 0x42, 0x48, 0x49):
        out += _sector_by_id(disk, 0, sid)
    out += disk.get_track_data(1)
    fs = AmsdosFilesystem(disk)
    for name in UTILS:
        data = fs.read_raw(name)
        out += to_field11(name).encode("latin1") + struct.pack("<I", len(data)) + data
    path = os.path.join(ROOT, "cpc_dsk", "data", "cpm22_system.bin")
    with open(path, "wb") as fh:
        fh.write(out)
    print(f"{path} : {len(out)} o")


if __name__ == "__main__":
    main()
