"""Géométrie standard des disquettes Amstrad CPC.

Constantes physiques / logiques d'une disquette CPC double face (3 pouces) :

    - 40 pistes (cylindres) par face
    - 2 faces (A et B)
    - 10 secteurs par piste
    - 256 octets par secteur

Capacité utilisateur totale :
    40 * 2 * 10 * 256 = 204 800 octets  (200 Ko)

C'est la géométrie bien établie du format standard CPC, celle utilisée par les
émulateurs (Fuse, CPCJS). Si un autre mode (simple face, 40/80 pistes…) est
nécessaire, ces constantes sont le point unique d'ajustement.
"""

from __future__ import annotations

TRACKS_PER_SIDE = 40
NUM_SIDES = 2
SECTORS_PER_TRACK = 10
SECTOR_SIZE = 256

# Capacité totale de données utilisateur, en octets (200 Ko).
DATA_CAPACITY = TRACKS_PER_SIDE * NUM_SIDES * SECTORS_PER_TRACK * SECTOR_SIZE


def sector_count(tracks: int = TRACKS_PER_SIDE,
                 sides: int = NUM_SIDES,
                 sectors_per_track: int = SECTORS_PER_TRACK) -> int:
    """Nombre total de secteurs de la disquette."""
    return tracks * sides * sectors_per_track


def is_valid_address(track: int, side: int, sector: int,
                     tracks: int = TRACKS_PER_SIDE,
                     sides: int = NUM_SIDES,
                     sectors_per_track: int = SECTORS_PER_TRACK) -> bool:
    """Vérifie qu'une adresse (piste, face, secteur) est dans les bornes."""
    return (0 <= track < tracks
            and 0 <= side < sides
            and 0 <= sector < sectors_per_track)
