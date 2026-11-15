<div align="center">

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
- **Catalogue des fichiers** sur les deux couches, **Filer** et **AMSDOS** : nom, type, longueur et adresse.
- **Ajouter un fichier local** sur la disquette : nom 8.3, type (Basic ou binaire), adresse de chargement, et choix de la couche d'écriture (Filer, AMSDOS ou les deux).
- **Extraire** un fichier vers le disque local, en conservant son extension (`MONPROG BAS` → `monprog.bas`).
- **Supprimer** un fichier, avec confirmation.
- **Dump hexadécimal** d'un fichier ou d'un secteur, sur trois colonnes alignées : offset, octets, ASCII.
- **Carte des secteurs** cliquable : la géométrie est lue sur l'image, les secteurs libres (remplis de `E5` ou de `00`) sont distingués des secteurs occupés, et ceux du fichier sélectionné sont surlignés.

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
├── fonts/            Press Start 2P et VT323 (licence OFL)
└── core/
    ├── adf.py        Lecture et écriture des images disquette
    ├── cpcfs.py      Systèmes de fichiers Filer et AMSDOS
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
