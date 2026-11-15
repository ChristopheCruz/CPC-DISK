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
├── test_disks/        # Disquettes de test (3 réelles d'époque + 2 générées)
├── tests/
├── pyproject.toml
└── README.md
```

## Format géré

**Conteneur « EXTENDED CPC DSK »** (vérifié) :

- **Disk-Info** (256 o) : magic `EXTENDED CPC DSK File…`, nb de pistes `0x30`,
  nb de faces `0x31`, tableau des tailles de piste `0x34` (1 o/piste × 256).
- **Blocs piste** : en-tête `Track-Info` (256 o : taille de secteur `0x14`,
  nb de secteurs `0x15`, gap3 `0x16`, filler `0x17`, puis un enregistrement
  de 8 o par secteur — cylindre, face, ID, code taille, st1, st2, longueur
  LE16) + données de secteurs contiguës. WinAPE valide ces enregistrements
  à l'ouverture (« invalid track sizes » sinon) ; les disques générés par
  l'outil les reproduisent fidèlement et remplissent les secteurs vierges à
  `0xE5`, comme après un formatage réel.
- Géométrie type : 40 pistes × 1 face, bloc de 4864 o (9 secteurs × **512 o**)
  → fichier de 194 816 o, identique à une disquette CPC réelle.
- **Variantes SAM / WinAPE tolérées** (vérifiées sur `test_disks/abbey.dsk`) :
  tableau des pistes complété à zéro (premier zéro = fin des pistes réelles),
  traînée `Offset-Info` en fin de fichier (conservée à la sauvegarde),
  taille de secteur variable par piste (ex. 15 × 256 o).

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

   Les objets AMSDOS vivent dans le **flux physique** du disque : un fichier
   traverse les pistes et les en-têtes `Track-Info` du conteneur restent
   intacts entre ses octets (vérifié sur `greed.dsk` : `YOGI1 BIN`, 25 192 o,
   traverse 5 pistes). Le balayage, la lecture, l'écriture et la suppression
   se font donc toutes dans ce flux linéaire, jamais dans l'image brute.

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
  avec leur couche (`FILER` / `AMSDOS`), ajout d'un fichier local (nom 8.3
  **préserver l'extension**, type, adresse de chargement, couche `filer`
  par défaut / `both` / `amsdos`), extraction (le nom proposé retrouve son
  extension), suppression, hexdumper de fichier ou de secteur brut.
- **Gotek (clé USB)** : pile de sources `.dsk`/`.adf`, options de nommage
  (`DISK%03d.adf`, sous-dossier, index de départ), génération du répertoire à
  copier sur la clé, vérification des images, et création d'une image
  **FAT16 complète** (rédacteur intégré, aucune dépendance — compatible
  `mkfs.fat` 4.2, vérifiée avec `fsck.fat` et `blkid`).

**Glisser-déposer (Windows)** : depuis l'explorateur, déposer directement
sur la fenêtre — `.dsk`/`.adf` s'ouvrent (ou rejoignent les sources Gotek
selon l'onglet actif), les autres fichiers s'ajoutent à la disquette ouverte
(dialogue 8.3). Implémenté avec l'API `RegisterDragHook` (aucune
dépendance externe) ; inactif sous Linux/macOS.

## Exécutable autonome (PyInstaller)

L'application peut être livrée sans Python ni installation :

- **Windows (natif)** : depuis un PC Windows (Python 3.10+ requis pour la
  seule génération), lancer `build_exe.bat` → produit `dist\cpc-dsk-gui.exe`.
- **Windows (croix-compilation depuis WSL, testée)** : avec `wine` installé,
  utiliser un CPython 64-bit portable « python-build-standalone » (pas
  d'installateur requis, tkinter inclus) et y installer `pyinstaller`, puis :
  ```bash
  wine /chemin/cpython/python.exe -m pip install pyinstaller
  # depuis la racine du projet, copié sur un chemin Linux NATIF (hors /mnt/c)
  wine /chemin/cpython/python.exe -m PyInstaller --onefile --windowed --clean --name cpc-dsk-gui run_gui.py
  ```
  → produit `dist/cpc-dsk-gui.exe` (PE32+ x86-64). Le montage WSL `/mnt/c`
  fait échouer l'étape « BeginUpdateResource » de PyInstaller sous wine.
- **Linux / WSL** :
  ```bash
  python3 -m pip install pyinstaller
  python3 -m PyInstaller --onefile --windowed --name cpc-dsk-gui run_gui.py
  ```
  → produit `dist/cpc-dsk-gui`.

L'exécutable embarque Python + tkinter : il s'ouvre directement sur la
machine cible (testé sous WSL).

## Disquettes de test

Le dossier `test_disks/` contient 5 disquettes prêtes à l'emploi
(3 réelles d'époque + 2 générées par l'outil) : `greed.dsk`, `robot.dsk`,
`abbey.dsk`, `vierge.dsk`, `demo_edition.dsk`. Voir
[`test_disks/README.md`](test_disks/README.md) pour le contenu de chacune et
un scénario de test complet (listage, extraction, suppression, protection
des disques ambigus, onglet Gotek).

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
`DISK%03d.adf…`, sous-dossier, index de départ, vérification du résultat et
création d'une image FAT16 complète (32 Mo par défaut, fichiers à la racine)
par le **rédacteur intégré** : son secteur d'amorçage reproduit byte-par-byte
la disposition « compacte » de `mkfs.fat` 4.2 (celle qu'attendent fsck.fat et
libblkid — pas la variante « extended BPB » du manuel Microsoft).

## Validation du format

- Le conteneur, le répertoire Filer, les fichiers AMSDOS et l'image FAT16
  Gotek sont **testés** (`pytest`, 40 tests) et **vérifiés sur des
  disquettes réelles** :
  - `greed.dsk` (*Yogi Bear*) : 4 fichiers Filer (768 / 25344 / 40960 / 7680 o)
    + 4 objets AMSDOS,
  - `robot.dsk` (*Robot PD 14400*) : 10 fichiers Filer en 12 entrées
    (chunks de 16 Ko, compteur d'allocation 0x02..0x81) + 2 objets AMSDOS,
  - `abbey.dsk` : disque de boot SAM/WinAPE — variante du conteneur
    (39/42 pistes, secteurs 256 o, traînée `Offset-Info`).
- Un aller-retour **écriture → relecture** est vérifié (modes `filer` et
  `both`), ainsi que la suppression avec recollage du paquet.

## Limites connues

- La longueur exacte d'un fichier Filer n'est pas stockée dans le répertoire
  (unités de 128 o) : la lecture `--source filer` renvoie la région allouée
  complète (remplissage à zéro inclus), comme la charge réelle du Filer.
- L'image FAT16 (rédacteur intégré) est plafonnée à ~32 Mo avec cette
  géométrie (512 o/secteur, 1 secteur/cluster) : de quoi couvrir les clés
  Gotek classiques. Pour une clé plus grande, copier le répertoire généré
  sur une clé formatée FAT16/FAT32.

## Licence

MIT
