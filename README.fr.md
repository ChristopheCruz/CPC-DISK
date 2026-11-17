<div align="center">

<img src="docs/logo.png" width="140" alt="CPC Disk Editor">

```
 ██████╗██████╗  ██████╗    ██████╗ ██╗███████╗██╗  ██╗
██╔════╝██╔══██╗██╔════╝    ██╔══██╗██║██╔════╝██║ ██╔╝
██║     ██████╔╝██║         ██║  ██║██║███████╗█████╔╝
██║     ██╔═══╝ ██║         ██║  ██║██║╚════██║██╔═██╗
╚██████╗██║     ╚██████╗    ██████╔╝██║███████║██║  ██╗
 ╚═════╝╚═╝      ╚═════╝    ╚═════╝ ╚═╝╚══════╝╚═╝  ╚═╝
        É D I T E U R   .DSK  ·  G O T E K  ·  A M S D O S

Ready
█
```

**Éditeur d'images disquette `.dsk` pour Amstrad CPC, avec préparation de clé USB pour lecteur Gotek.**
Une interface au look « écran CPC », en pur Python, sans aucune dépendance externe.

![Python](https://img.shields.io/badge/Python-3.8%2B-000080?style=flat-square&labelColor=FFFF00&logo=python&logoColor=000080)
![GUI](https://img.shields.io/badge/GUI-tkinter-000080?style=flat-square&labelColor=00FFFF)
![Dépendances](https://img.shields.io/badge/d%C3%A9pendances-aucune-000080?style=flat-square&labelColor=00FF00)
![Licence](https://img.shields.io/badge/licence-MIT-000080?style=flat-square&labelColor=FF8000)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-soutenir-000080?style=flat-square&labelColor=FFDD00&logo=buymeacoffee&logoColor=000000)](https://www.buymeacoffee.com/ChristopheCruz)

[🇫🇷 Français](README.fr.md) · [🇬🇧 English](README.md)

</div>

---

![CPC Disk Editor — onglet Disquette](docs/screenshot.png)

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Installation](#installation)
- [Lancement](#lancement)
- [Utilisation](#utilisation)
- [Raccourcis clavier](#raccourcis-clavier)
- [Structure du projet](#structure-du-projet)
- [Soutenir le projet](#soutenir-le-projet)
- [Crédits](#crédits)
- [Licence](#licence)

## Fonctionnalités

### Onglet Disquette (`.dsk`)

- **Ouvrir, créer, sauver** des images disquette au format EXTENDED CPC DSK (les `.adf` sont aussi acceptés).
- **Catalogue AMSDOS** : le même que celui que lit le CPC (64 entrées, blocs de 1 Ko), pour les disquettes DATA (`&C1..&C9`) et SYSTEM/CP-M (`&41..&49`). Nom, type, longueur, adresse ; numéros d'utilisateur (`1:JEU.BAS`).
- **Ajouter un fichier local** : nom 8.3, type (Basic ou binaire), adresse de chargement, **avec en-tête AMSDOS** (comme `SAVE`) ou **en données brutes** (texte, programme CP/M). L'espace est pris dans les blocs libres, comme le fait AMSDOS.
- **Extraire** un fichier vers le disque local (`MONPROG.BAS` → `monprog.bas`), sans son en-tête.
- Une disquette d'un format inconnu est lue « au mieux » par l'ancien balayage d'en-têtes.
- **Supprimer** un fichier, avec confirmation.
- **Dump hexadécimal** d'un fichier ou d'un secteur, sur trois colonnes alignées : offset, octets, ASCII.
- **Carte des secteurs** cliquable : la géométrie est lue sur l'image, les secteurs libres (remplis de `E5` ou de `00`) sont distingués des secteurs occupés, et ceux du fichier sélectionné sont surlignés.

### Support CP/M 2.2

- **Disques système CP/M 2.2 amorçables** (« System format », 40 pistes × 9 × 512, IDs de secteur `&41..&49`) : le bouton **Nouveau CP/M** (ou `cpc-dsk new x.dsk --cpm`) en génère un à partir d'une image de référence extraite d'un cpm22.dsk réel — CP/M 2.2 + Amsdos 2.0 (`AMSDOS.COM`, `DISCKIT2.COM`, `LOGO2.COM`, `LOGO2.SUB`), prêt à tester sur un Gotek réel.
- **Détection automatique** des disques CP/M : le catalogue est celui de CP/M 2.2 (piste 2, 64 entrées, blocs de 1 Ko). Les fichiers avec en-tête AMSDOS sont reconnus (ex. `RITDEMO.BIN`, 11 264 o).
- Spécificités des disques réels gérées : bits d'attribut dans les noms (Planetfall), ordre des IDs de secteur séquentiel ou entrelacé (Track-Infos identiques à WinAPE sur les disques générés).

### Onglet Gotek (clé USB)

- **Liste de sources** `.dsk` / `.adf`, réordonnable avec ▲ ▼.
- **Patron de noms** (par défaut `DISK%03d.adf`), sous-dossier et index de départ, avec un aperçu des noms en direct.
- **Générer** le répertoire à copier sur la clé USB du Gotek.
- **Vérifier** un dossier existant.
- **Créer une image FAT16** complète de la clé (32 Mo) grâce à un rédacteur FAT intégré, sans outil externe.
- **Charger une image `.img`** existante : liste de son contenu, renvoi des disquettes vers la pile de sources, ou extraction dans un dossier.

### Interface

- Look **Amstrad CPC** : palette du firmware (bleu, jaune vif, cyan), polices pixel, boutons en relief de 4 px, sélection en vidéo inverse et curseur `Ready` clignotant.
- **Deux moniteurs** : couleur (CTM644) ou vert (GT65), à basculer avec F3.
- **Trois langues d'interface** : anglais, français et espagnol — détectées depuis la locale système, changeables dans la fenêtre.
- **Glisser-déposer** depuis l'explorateur Windows.
- Compatible **haute résolution** : les polices pixel restent nettes à 125 %, 150 % et au-delà.

L'interface dans les deux autres langues (le visuel ci-dessus est en français) :

<table>
  <tr>
    <td align="center"><img src="docs/screenshot-en.png" width="49%"></td>
    <td align="center"><img src="docs/screenshot-gotek-en.png" width="49%"></td>
  </tr>
  <tr>
    <td align="center"><em>Anglais — onglet Disquette</em></td>
    <td align="center"><em>Anglais — onglet Gotek</em></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/screenshot-es.png" width="49%"></td>
    <td align="center"><img src="docs/screenshot-gotek-es.png" width="49%"></td>
  </tr>
  <tr>
    <td align="center"><em>Espagnol — onglet Disquette</em></td>
    <td align="center"><em>Espagnol — onglet Gotek</em></td>
  </tr>
</table>

## Installation

Python 3.8 ou plus récent suffit. `tkinter` est fourni avec Python sous Windows et macOS.

```bash
git clone https://github.com/ChristopheCruz/AmstradCPC.git
cd AmstradCPC
```

Sous Linux, `tkinter` est parfois livré à part :

```bash
sudo apt install python3-tk      # Debian / Ubuntu
```

Les polices **Press Start 2P** et **VT323** sont fournies dans `cpc_dsk/fonts/`. Sous Windows, elles sont chargées pour l'application seule, sans rien installer sur le système. Ailleurs, ou si le dossier est absent, l'interface utilise automatiquement une police à chasse fixe. Pour avoir le rendu pixel sous Linux ou macOS, installe les deux `.ttf` dans tes polices utilisateur.

## Lancement

```bash
python -m cpc_dsk.gui
```

## Utilisation

### Éditer une disquette

1. **Ouvrir** une image `.dsk`, ou **Nouveau** pour partir d'une disquette vierge.
2. Sélectionne un fichier dans le catalogue : son contenu s'affiche en hexadécimal à droite.
3. **Ajouter**, **Extraire** ou **Supprimer** des fichiers. La disquette est sauvegardée après chaque modification.
4. Pour inspecter un secteur précis, saisis `piste secteur` (par exemple `0 0`) puis **Afficher**, ou clique directement dans la carte des secteurs (vue **Secteurs**, F4).

### Créer un disque système CP/M

1. **Nouveau CP/M** (ou `cpc-dsk new cpm.dsk --cpm`) → un disque CP/M 2.2 « System format » amorçable, avec les utilitaires Amsdos. `--no-utils` produit un système nu (répertoire vide).
2. **Ajoute** tes programmes (données brutes pour un `.COM`, en-tête AMSDOS pour un binaire CPC), puis **Sauve**.
3. Copie l'image sur la clé du Gotek (onglet Gotek, `DISK001.adf`) et amorçes-la sur un vrai CPC : le BIOS `|CPM` charge le secteur de boot, le système démarre sur `A>` et lit le répertoire de la piste 2.
4. Les disques CP/M existants (réels ou home-brew) sont détectés automatiquement : ouvre-en un, le catalogue liste ses fichiers CP/M.

```bash
cpc-dsk list cpm.dsk --source cpm       # répertoire CP/M
cpc-dsk list cpm.dsk --source amsdos    # objets AMSDOS
cpc-dsk read cpm.dsk PROG.COM --out prog.com
cpc-dsk write cpm.dsk MYPGM.BIN mypgm.bin --load 0x4000
```

### Préparer une clé pour le Gotek

1. Dans l'onglet **Gotek** (F2), **Ajoute** les disquettes, puis mets-les dans l'ordre voulu avec ▲ ▼.
2. Ajuste si besoin le patron de noms, le sous-dossier et l'index de départ. La colonne « → clé USB » montre le nom que portera chaque image.
3. Choisis le dossier de sortie (la racine de la clé, par exemple), puis **Générer USB**.
4. Pour une clé neuve, **Image FAT** produit à la place une image `.img` complète, à graver sur la clé.

![CPC Disk Editor — onglet Gotek](docs/screenshot-gotek.png)

### Glisser-déposer (Windows)

| Ce que tu déposes | Onglet actif | Résultat |
|---|---|---|
| `.dsk` / `.adf` | Disquette, aucun disque ouvert | la disquette s'ouvre |
| `.dsk` / `.adf` | Disquette, un disque ouvert | ajouté aux sources Gotek |
| `.dsk` / `.adf` | Gotek | ajouté aux sources |
| tout autre fichier | n'importe lequel | ajouté à la disquette ouverte |

## Raccourcis clavier

| Touche | Action |
|---|---|
| <kbd>F1</kbd> / <kbd>F2</kbd> | Onglet Disquette / Gotek |
| <kbd>F3</kbd> | Moniteur couleur / vert |
| <kbd>F4</kbd> | Vue Fichiers / Secteurs |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Ouvrir une disquette |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | Nouvelle disquette |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Sauver |
| <kbd>Suppr</kbd> | Supprimer le fichier ou la source sélectionnés |
| <kbd>Entrée</kbd> (champ secteur) | Afficher le secteur |

## Structure du projet

```
cpc_dsk/
├── gui.py            Interface graphique tkinter (habillage pixel art)
├── cli.py            Interface en ligne de commande
├── i18n.py           Chaînes d'interface (en / fr / es)
├── data/
│   └── cpm22_system.bin   CP/M 2.2 + Amsdos 2.0 : pistes système + 4 utilitaires (scripts/make_cpm_reference.py)
├── fonts/            Press Start 2P et VT323 (licence OFL)
└── core/
    ├── adf.py        Lecture et écriture des images disquette
    ├── amsdos.py     Catalogue AMSDOS / CP/M (formats DATA et SYSTEM) : lecture, écriture, suppression
    ├── cpcfs.py      En-têtes AMSDOS, balayage de secours (formats inconnus)
    ├── cpm.py        CP/M 2.2 (« System format ») : système de fichiers + générateur de disque
    └── gotek.py      Préparation de la clé USB et rédacteur FAT16
```

## Soutenir le projet

CPC Disk Editor est gratuit et le restera. S'il t'a évité quelques heures de manipulations de disquettes, ou s'il a redonné vie à un vieux 6128 grâce au Gotek, tu peux m'offrir un café : ça finance du temps pour les prochaines fonctionnalités.

<div align="center">

<a href="https://www.buymeacoffee.com/ChristopheCruz" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="50">
</a>

```
10 PRINT "MERCI !"
20 GOTO 10
```

</div>

Une étoile ⭐ sur le dépôt, un signalement de bug ou une idée dans les *issues* aident tout autant.

## Crédits

- **Press Start 2P** par CodeMan38 et **VT323** par Peter Hull, distribuées sous [SIL Open Font License 1.1](https://openfontlicense.org). Leurs licences sont dans `cpc_dsk/fonts/`.
- Amstrad et CPC sont des marques de leurs détenteurs respectifs. Ce projet n'est affilié à aucun d'eux.

## Licence

[MIT](LICENSE) — voir le fichier `LICENSE` à la racine du dépôt.
