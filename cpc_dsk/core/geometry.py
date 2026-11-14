"""Géométrie par défaut pour la création de disquettes CPC vierges.

La géométrie **réelle** d'une image est lue depuis son en-tête Disk-Info (voir
:mod:`cpc_dsk.core.adf`). Ces constantes servent uniquement de valeurs par
défault lors de la création d'une nouvelle disquette vierge
(:meth:`cpc_dsk.core.adf.ADFDisk.new_blank`).

La valeur par défaut reproduit une disquette CPC réelle (40 pistes, 1 face,
9 secteurs × 512 o), connue pour être lisible par les émulateurs et le Gotek.
"""

from __future__ import annotations

DEFAULT_TRACKS = 40
DEFAULT_SIDES = 1
DEFAULT_SECTORS = 9
DEFAULT_SECTOR_SIZE = 512
