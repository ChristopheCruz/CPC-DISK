"""Outils SEQ-16 intégrés à CPC DISK : banques de samples .SMP.

- :mod:`cpc_dsk.seq16.wav2smp`  : conversion WAV -> banque .SMP (ligne de
  commande : ``python -m cpc_dsk.seq16.wav2smp``) ;
- :mod:`cpc_dsk.seq16.smp_model` : modèle de l'éditeur (sans interface) ;
- :mod:`cpc_dsk.seq16.smp_gui`  : éditeur graphique, autonome
  (``python -m cpc_dsk.seq16.smp_gui``) ou onglet « SAMPLES SEQ-16 » de
  CPC DISK ;
- :mod:`cpc_dsk.seq16.dskio`    : ajout / relecture d'un fichier sur une
  disquette DATA, par le catalogue AMSDOS de :mod:`cpc_dsk.core.amsdos`.

Le format .SMP est celui du lecteur Z80 de SEQ-16 : ces modules ne
changent pas les octets produits.
"""
