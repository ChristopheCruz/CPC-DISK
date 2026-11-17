"""dskio.py : ajouter ou relire une banque sur une disquette CPC (.dsk).

Remplace l'ancien ``tools/amsdsk.py`` de SEQ-16 : tout passe par le
catalogue AMSDOS de CPC DISK (:mod:`cpc_dsk.core.amsdos`). Mêmes règles
qu'amsdsk :

  - disquette au format DATA (#C1) seulement ;
  - fichier binaire avec en-tête AMSDOS (mode « amsdos »), adresse de
    chargement 0, exécution 0 ;
  - un fichier du même nom est remplacé.

Chaque fonction accepte un chemin de fichier .dsk (lu, puis réécrit si
besoin) ou une disquette déjà chargée (:class:`cpc_dsk.core.adf.ADFDisk`,
modifiée en mémoire sans être sauvée). Les erreurs sont des ``ValueError``
(comme amsdsk) ou des ``OSError`` (fichier).
"""
from ..core import amsdos
from ..core.adf import ADFDisk, ADFError
from ..core.cpcfs import CpcError

LOAD_ADDR = 0x0000          # adresse de chargement écrite par amsdsk.add_file


def _open(dsk):
    """(disquette, système de fichiers) ; dsk = chemin ou ADFDisk."""
    try:
        disk = dsk if isinstance(dsk, ADFDisk) else ADFDisk.load(dsk)
        if amsdos.detect_format(disk) is not amsdos.DATA:
            raise ValueError("disquette au format DATA (#C1) attendue")
        return disk, amsdos.AmsdosFilesystem(disk, amsdos.DATA)
    except (ADFError, CpcError) as exc:
        raise ValueError(str(exc))


def add_file(dsk, name, data, load=LOAD_ADDR):
    """Ajoute (ou remplace) un fichier binaire AMSDOS. dsk = chemin (réécrit)
    ou ADFDisk (modifié en mémoire). Renvoie la taille écrite, en-tête compris.

    En cas d'erreur (disquette pleine...), la disquette n'est pas touchée :
    l'écriture se fait sur une copie, recopiée seulement si tout a réussi
    (write_file efface l'ancien fichier avant de chercher la place)."""
    disk, _ = _open(dsk)
    work = ADFDisk(bytes(disk._raw))
    try:
        amsdos.AmsdosFilesystem(work, amsdos.DATA).write_file(
            name, bytes(data), load_addr=load, exec_addr=0,
            mode="amsdos", overwrite=True)
    except (CpcError, ADFError) as exc:
        raise ValueError(str(exc))
    if isinstance(dsk, ADFDisk):
        dsk._raw[:] = work._raw
    else:
        work.save(dsk)
    return 128 + len(data)


def read_file(dsk, name, keep_header=False):
    """Relit un fichier ; renvoie les données sans l'en-tête AMSDOS."""
    _, fs = _open(dsk)
    if fs.find(name) is None:
        raise FileNotFoundError(name + " absent de la disquette")
    return fs.read_raw(name) if keep_header else fs.read_file(name)


def list_files(dsk):
    """{nom: taille au catalogue (multiple de 128 octets)}."""
    _, fs = _open(dsk)
    return {f.name: f.records * 128 for f in fs.list_files()}
