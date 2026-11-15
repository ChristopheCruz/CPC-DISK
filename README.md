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
│   │   ├── cpcfs.py   #   Système de fichiers : répertoire Filer + AMSDOS
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
  nb de faces `0x31`, tableau des tailles de piste `0x34` (1 o/piste × 256).
- **Blocs piste** : en-tête `Track-Info` (256 o, nb de secteurs `0x15`) +
  données de secteurs contiguës.
- Géométrie type : 40 pistes × 1 face, bloc de 4864 o (9 secteurs × **512 o**)
  → fichier de 194 816 o, identique à une disquette CPC réelle.

### Répertoires et fichiers

Deux couches coexistent sur une disquette CPC (vérifié sur images réelles) :

1. **Le répertoire Filer** (DOS d'origine du CPC) — c'est lui que lit le vrai
   DOS, et donc le **Gotek sur matériel réel**.

   Piste 0, secteur 0 : 16 entrées de 32 o. Entrée occupée :

   | Offset | Taille | Champ |
   |--------|--------|-------|
   | 0x00   | 1  | 0x00 |
   | 0x01   | 11 | nom 8.3, `.` codé 0xC9 |
   | 0x0C   | 1  | index du chunk dans le fichier (0, 1, …) |
   | 0x0D   | 2  | 0x00 0x00 |
   | 0x0F   | 1  | taille du chunk en unités de 128 o (max 0x80 = 16 Ko) |
   | 0x10   | 16 | `ceil(chunk/1024)` octets de compteur d'allocation (compteur global démarrant à 0x02), puis zéros |

   Entrée vide = 32 o 0xE5. Les données des fichiers sont empilées
   séquentiellement dans l'ordre du répertoire, à partir du secteur 1 de la
   piste 0 ; un fichier > 16 Ko occupe plusieurs entrées (chunks). Le Filer
   recolle le paquet à l'insertion/suppression. Fichier Filer = données
   brutes, longueur réelle arrondie au multiple de 128 o.

2. **Les en-têtes AMSDOS** (DOS tiers « Amsdos ») : chaque fichier est
   préfixé d'un en-tête de 128 o (nom, type, adresses de chargement/entrée,
   longueur, checksum) localisé par balayage — c'est la méthode de l'émulateur
   CERMU, qui ne lit pas le répertoire Filer.

## Installation

```bash
pip install -e .
```

Sans installation : `python -m cpc_dsk.cli …` et `python -m cpc_dsk.gui`.

## Utilisation (GUI)

```bash
python -m cpc_dsk.gui
```

Deux onglets :

- **Disquette (.dsk)** : ouvrir / créer / sauvegarder, liste des fichiers
  avec leur couche (`FILER` / `AMSDOS`), ajout d'un fichier local (nom 8.3,
  type, adresse de chargement, couche `both`/`filer`/`amsdos`), extraction,
  suppression, hexdumper de fichier ou de secteur brut.
- **Gotek (clé USB)** : pile de sources `.dsk`/`.adf`, options de nommage
  (`DISK%03d.adf`, sous-dossier, index de départ), génération du répertoire à
  copier sur la clé, vérification des images, et création d'une image FAT
  complète quand `mformat`/`mkfs.fat` est disponible.

## Exécutable autonome (PyInstaller)

L'application peut être livrée sans Python ni installation :

- **Windows** : depuis un PC Windows (Python 3.10+ requis pour la seule
  génération), lancer `build_exe.bat` → produit `dist\cpc-dsk-gui.exe`.
- **Linux / WSL** :
  ```bash
  python3 -m pip install pyinstaller
  python3 -m PyInstaller --onefile --windowed --name cpc-dsk-gui run_gui.py
  ```
  → produit `dist/cpc-dsk-gui`.

L'exécutable embarque Python + tkinter : il s'ouvre directement sur la
machine cible (testé sous WSL).

## Utilisation (CLI)

```bash
# Créer une disquette vierge
cpc-dsk new monjeu.dsk

# Géométrie + liste des fichiers (Filer + AMSDOS)
cpc-dsk info monjeu.dsk
cpc-dsk list monjeu.dsk [--source filer|amsdos]

# Extraire un fichier de la disquette vers un fichier local
cpc-dsk read monjeu.dsk "MONPROG BAS" --out monprog.bas [--source filer|amsdos]

# Copier un fichier local sur la disquette
cpc-dsk write monjeu.dsk "MONPROG BAS" monprog.bas --type basic --load 0x4000 [--fs both|filer|amsdos]

# Supprimer un fichier
cpc-dsk delete monjeu.dsk "MONPROG BAS"

# Accès bas niveau (secteurs bruts)
cpc-dsk hex monjeu.dsk 0 0
cpc-dsk sector monjeu.dsk 0 0 --write-file brut.bin
```

**Modes d'écriture** (`--fs`) :

- `both` (défaut) : écrit les **deux** couches — fichier Filer (données
  brutes + entrées du répertoire) **et** objet AMSDOS (en-tête + données). Le
  disque est lisible par le vrai DOS/Gotek *et* les émulateurs.
- `filer` : répertoire Filer seulement (DOS/Gotek, pas d'émulateurs basés sur
  le balayage AMSDOS).
- `amsdos` : objet AMSDOS seulement (émulateurs).

Allocation : les fichiers Filer grandissent vers l'avant depuis le secteur
répertoire (contrainte du format) ; les objets AMSDOS sont empilés vers
l'arrière depuis la fin du disque. Les disques réels d'époque dont le paquet
Filer contient des objets AMSDOS (agencement ambigu) sont protégés : la
lecture fonctionne, l'écriture Filer est refusée.

## Clé USB Gotek

La clé USB du Gotek est un répertoire FAT16/FAT32 contenant des fichiers
`.dsk`/`.adf`, servis un à un par le firmware Gotek comme des disquettes
virtuelles.

```bash
# (via le noyau) préparer le répertoire à copier sur la clé
from cpc_dsk.core.gotek import GotekConfig, prepare_usb_directory
prepare_usb_directory("cle_usb/", ["jeu1.dsk", "jeu2.dsk"], GotekConfig())
```

Voir `cpc_dsk/core/gotek.py` : validation des sources, préfixage
`DISK000.adf…`, sous-dossier, index de départ, vérification du résultat et
création optionnelle d'une image FAT complète (nécessite `mformat` ou
`mkfs.fat`).

## Validation du format

- Le conteneur, le répertoire Filer et les fichiers AMSDOS sont **testés**
  (`pytest`, 28 tests) et **vérifiés sur des disquettes réelles** :
  - `greed.dsk` (*Yogi Bear*) : 4 fichiers Filer (768 / 25344 / 40960 / 7680 o)
    + 4 objets AMSDOS,
  - `robot.dsk` (*Robot PD 14400*) : 10 fichiers Filer en 12 entrées
    (chunks de 16 Ko, compteur d'allocation 0x02..0x81) + 2 objets AMSDOS.
- Un aller-retour **écriture → relecture** est vérifié (modes `filer` et
  `both`), ainsi que la suppression avec recollage du paquet.

## Limites connues

- La longueur exacte d'un fichier Filer n'est pas stockée dans le répertoire
  (unités de 128 o) : la lecture `--source filer` renvoie la région allouée
  complète (remplissage à zéro inclus), comme la charge réelle du Filer.
- L'image FAT complète pour cloner directement la clé Gotek dépend d'un outil
  `mformat`/`mkfs.fat` (sinon on copie le répertoire généré sur une clé
  formatée FAT16/FAT32).

## Licence

MIT
