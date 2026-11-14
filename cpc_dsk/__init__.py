"""cpc_dsk — Éditeur de disquettes virtuelles .dsk (CPC) & images Gotek.

L'API publique est exposée ici pour un usage concis::

    from cpc_dsk import ADFDisk, CpcFilesystem
    disk = ADFDisk.load("jeu.dsk")
    for f in CpcFilesystem(disk).list_files():
        print(f.name, f.type_name, f.length)
"""

from cpc_dsk.core.adf import ADFDisk, ADFError
from cpc_dsk.core.cpcfs import (
    CpcError,
    CpcFile,
    CpcFilesystem,
    FT_BASIC,
    FT_BINARY,
    FT_PROTECTED,
)
from cpc_dsk.core.geometry import (
    DEFAULT_SECTOR_SIZE,
    DEFAULT_SECTORS,
    DEFAULT_SIDES,
    DEFAULT_TRACKS,
)

__all__ = [
    "ADFDisk",
    "ADFError",
    "CpcFilesystem",
    "CpcFile",
    "CpcError",
    "FT_BASIC",
    "FT_BINARY",
    "FT_PROTECTED",
    "DEFAULT_TRACKS",
    "DEFAULT_SIDES",
    "DEFAULT_SECTORS",
    "DEFAULT_SECTOR_SIZE",
]

__version__ = "0.1.0"
