# Amstrad CPC — Éditeur de disquettes `.dsk` & images Gotek

Outil **Python** pour créer et éditer :

- des **disquettes virtuelles `.dsk`** au format **EXTENDED CPC DSK** (format
  standard des images CPC, lu par les émulateurs Fuse / CPCJS / CERMU et le
  Gotek),
- des **images de clé USB** pour **Gotek** (lecteur floppy USB) sur Amstrad
  CPC 6128.

Le format est **vérifié sur des disquettes réelles** (jeux CPC téléchargés sur
l'Internet Archive).

## Structure du projet

```
AmstradCPC/
├── cpc_dsk/
│   ├── core/          # Noyau sans dépendance GUI
│   │   ├── adf.py     #   Conteneur EXTENDED CPC DSK (Disk-Info + blocs piste)
│   │   ├── cpcfs.py   #   Système de fichiers : fichiers AMSDOS (lister/lire/écrire)
│   │   ├── geometry.py#   Géométrie par défaut (création de disquette vierge)
│   │   └── gotek.py   #   Préparation de l'image USB pour Gotek
│   ├── cli.py         # Interface en ligne de commande
│   └── gui.py         # Interface graphique (tkinter)
├── tests/
├── pyproject.toml
└── README.md
```

## Format géré

**Conteneur « EXTENDED CPC DSK »** (vérifié) :

- **Disk-Info** (256 o) : magic `EXTENDED CPC DSK File…`, nb de pistes `0x30`,
  nb de faces `0x31`, tableau des tailles de pistes `0x34` (1 o/piste × 256).
- **Blocs piste** : en-tête `Track-Info` (256 o, nb de secteurs `0x15`) +
  données de secteurs contiguës.
- Géométrie type : 40 pistes × 1 face, bloc de 4864 o (9 secteurs × **512 o**)
  → fichier de 194 816 o, identique à une disquette CPC réelle.

**Système de fichiers** : chaque fichier commence par un **en-tête AMSDOS**
(128 o : nom, type, adresses, longueur, checksum) suivi des données. Les
fichiers sont localisés par balayage des en-têtes AMSDOS à checksum valide.

## Installation

```bash
pip install -e .
```

Sans installation : `python -m cpc_dsk.cli …` et `python -m cpc_dsk.gui`.

## Utilisation (CLI)

```bash
# Créer une disquette vierge
cpc-dsk new monjeu.dsk

# Géométrie + liste des fichiers
cpc-dsk info monjeu.dsk
cpc-dsk list monjeu.dsk

# Extraire un fichier de la disquette vers un fichier local
cpc-dsk read monjeu.dsk "MONPROG BAS" --out monprog.bas

# Copier un fichier local sur la disquette
cpc-dsk write monjeu.dsk "MONPROG BAS" monprog.bas --type basic --load 0x4000

# Accès bas niveau (secteurs bruts)
cpc-dsk hex monjeu.dsk 0 0
cpc-dsk sector monjeu.dsk 0 0 --write-file brut.bin
```

## Validation du format

- Le conteneur et les fichiers AMSDOS sont **testés** (`pytest`, 14 tests) et
  **vérifiés sur une disquette réelle** (`greed.dsk` — *Yogi Bear* : 4 fichiers
  extraits, dont le programme BASIC `YOGI BAS`).
- Un aller-retour **écriture → relecture** est vérifié sur disquette vierge.

## Limites connues

- L'écriture crée des **fichiers AMSDOS** (lisibles par les lecteurs qui
  balayent les en-têtes, ex. CERMU) mais **ne met pas encore à jour le
  répertoire traditionnel CPC** (piste 0, secteur 0). À finaliser pour une
  compatibilité totale du DOS CPC / Gotek sur matériel réel.
- L'image FAT complète pour cloner directement la clé Gotek dépend d'un outil
  `mformat`/`mkfs.fat` (sinon on copie le répertoire généré sur une clé
  formatée FAT16/FAT32).

## Licence

MIT
