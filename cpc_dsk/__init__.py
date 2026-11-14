"""cpc_dsk — Éditeur de disquettes virtuelles .dsk (ADF) & images Gotek pour Amstrad CPC.

Package principal. L'API publique est exposée ici pour un usage concis :

    from cpc_dsk import ADFDisk
    disk = ADFDisk.new_blank()
    disk.save("ma_disc.dsk")
"""

from cpc_dsk.core.adf import ADFDisk
from cpc_dsk.core.geometry import (
    DATA_CAPACITY,
    NUM_SIDES,
    SECTORS_PER_TRACK,
    SECTOR_SIZE,
    TRACKS_PER_SIDE,
)

__all__ = [
    "ADFDisk",
    "TRACKS_PER_SIDE",
    "NUM_SIDES",
    "SECTORS_PER_TRACK",
    "SECTOR_SIZE",
    "DATA_CAPACITY",
]

__version__ = "0.1.0"
