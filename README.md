# Amstrad CPC — Éditeur de disquettes .dsk & images Gotek

Outil **Python** pour créer et éditer :

- des **disquettes virtuelles `.dsk`** au format **ADF** (format CPC standard, utilisé par les émulateurs Fuse/CPCJS),
- des **images de clé USB** pour **Gotek** (lecteur floppy USB) sur Amstrad CPC 6128.

## Structure du projet

```
AmstradCPC/
├── cpc_dsk/
│   ├── core/          # Noyau sans dépendance GUI : format ADF, géométrie disquette, Gotek
│   │   ├── adf.py     #   Lecture/écriture du format binaire ADF
│   │   ├── geometry.py#   Constantes CPC (pistes, faces, secteurs, taille)
│   │   └── gotek.py   #   Génération d'image USB pour Gotek
│   ├── cli.py         # Interface en ligne de commande
│   └── gui.py         # Interface graphique (tkinter)
├── tests/
├── pyproject.toml
└── README.md
```

## Architecture

Un **noyau commun** (`cpc_dsk.core`) implémente toute la logique (lecture/écriture ADF,
système de fichiers CPC, image Gotek). La **CLI** et la **GUI** sont de fins
« adapteurs » qui s'appuient sur ce noyau :

- `cpc-dsk` (CLI) — scriptable, idéal pour automatiser la création de disquettes/clé USB.
- GUI (tkinter) — explorateur visuel de la disquette, édition des fichiers.

## Installation

```bash
pip install -e .
```

## Utilisation (CLI)

```bash
# Créer une disquette ADF vierge (double face, 40 pistes, 200 Ko)
cpc-dsk new disc1.dsk

# Afficher la géométrie / les informations d'une disquette
cpc-dsk info disc1.dsk

# Hexdump d'un secteur brut (piste, face, secteur)
cpc-dsk hex disc1.dsk 0 0 0

# Écrire le contenu d'un fichier local (256 o) dans un secteur brut
cpc-dsk sector disc1.dsk 0 0 0 --write-file fichier_local

# Exporter un secteur brut vers un fichier
cpc-dsk dump disc1.dsk 0 0 0 --out secteur.bin
```

Sans installation, on peut aussi lancer directement :

```bash
python -m cpc_dsk.cli new disc1.dsk
python -m cpc_dsk.gui          # interface graphique (tkinter)
```

## État actuel & roadmap

**Implémenté et testé** (suites `pytest` : 9/9) :
- Noyau ADF : géométrie standard CPC (40 pistes × 2 faces × 10 secteurs ×
  256 o = 200 Ko), lecture/écriture de secteurs bruts, aller-retour fichier.
- CLI : `new`, `info`, `sector`, `hex`, `dump`.
- GUI (tkinter) : ouverture, géométrie, arborescence pistes/faces/secteurs,
  inspection hex.
- Gotek : préparation d'un répertoire de disquettes `.adf` pour la clé USB,
  validation des images.

**À venir** :
- Système de fichiers CPC (annuaire + fichiers nommés) au-dessus du noyau ADF,
  pour copier des programmes / données vers la disquette (niveaux `list`,
  `write`, `read` à la façon du Filer CPC).
- Image FAT complète `.img` pour cloner directement la clé Gotek (dépend d'un
  outil `mformat`/`mkfs.fat`).

> **Validation du format** : la disposition octet par octet de l'en-tête ADF et
> des secteurs est documentée dans `cpc_dsk/core/adf.py` et est autocohérente.
> À valider contre un émulateur (Fuse/CPCJS) et/ou un fichier `.dsk` de
> référence ; les constantes de format y sont centralisées.

## Licence

MIT
