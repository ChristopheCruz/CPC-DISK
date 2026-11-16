# Disquettes de test

Dix disquettes `.dsk` (format EXTENDED CPC DSK, géométrie CPC 40 pistes ×
9 secteurs × 512 o sauf avis contraire) pour tester l'éditeur, l'onglet
Gotek et le support CP/M 2.2, sans avoir à télécharger quoi que ce soit.

| Disquette | Origine | Contenu | À tester |
|-----------|---------|---------|----------|
| `greed.dsk` | réelle (Internet Archive, *Yogi Bear*) | 4 fichiers Filer + 4 objets AMSDOS | Lister, extraire `YOGI BAS`, hexdumper. **Écriture Filer refusée** (disque ambigu : objets AMSDOS dans le paquet Filer) — la protection doit s'afficher. |
| `robot.dsk` | réelle (Internet Archive, *Robot PD 14400*) | 10 fichiers Filer en 12 entrées (chunks 16 Ko) + 2 AMSDOS | Fichiers > 16 Ko : `LARA DOC` (45 312 o = 3 chunks), `LARA BIN` (8 576 o). Même protection à l'écriture Filer. |
| `abbey.dsk` | réelle, produite par SAM/WinAPE | Disque de boot, **aucun fichier** | S'ouvre sans erreur malgré la variante SAM : 42 pistes déclarées pour 39 réelles, pistes 1-38 en 15 secteurs × 256 o, traînée `Offset-Info` en fin de fichier. |
| `sooty.dsk` | réelle (Internet Archive, *Sooty & Sweep*) | 5 objets AMSDOS seulement, géométrie **mixte** : 40 pistes 9×512 + 2 pistes Track-Info seules (CPCDiskXP) | S'ouvre malgré les 42 pistes (2 vides de 256 o) ; lister/extraire les objets AMSDOS (`DISK BIN`, `SCREEN DL`) ; carte des secteurs (2 pistes vides). |
| `compilation190.dsk` | réelle (Internet Archive, *Compilation Disk 190*, CPDRead) | 11 fichiers Filer + 17 objets AMSDOS (jeux *Arkano* et *Cyber* + utilitaires) | Les deux couches : `ARKANO BIN` (Filer, 35 712 o, 2 chunks), `GRUGEUR BAS` (AMSDOS, 1 743 o), `A BAS` dans les deux couches (186 o AMSDOS / 384 o Filer). |
| `cpm22.dsk` | réelle (Internet Archive, CP/M 2.2 + Amsdos 2.0) | Système CP/M 2.2 « System format » : 24 fichiers (répertoire piste 2) + 3 objets AMSDOS « legacy » | **Base de référence du module CP/M** : la génération `new --cpm` reproduit ses Track-Infos à l'octet près. Lister (24 fichiers), extraire `DISCKIT2.COM` (brut) ou `RITDEMO.BIN` (legacy → 11 264 o via l'objet AMSDOS), `DISC.BAS` (21 331 o). |
| `planetfall_cpm.dsk` | réelle (Internet Archive, Infocom *Planetfall*) | Système CP/M + jeu : 5 fichiers, noms en **jeu de caractères CP/M** (0xC1..0xD6 = A..Z) | Détection CP/M (IDs séquentiels 41..49), noms traduits : `PLANET.COM`, `PLAN64/128/256.COM`, `PLANETFA.DAT` (7 chunks, 109 568 o). |
| `starcross_cpm.dsk` | réelle (Internet Archive, Infocom *Starcross*) | Système CP/M + jeu : `STARCROS.COM` (8 192 o) + `STARCROS.DAT` (83 968 o) | Autre variante CP/M réelle (détection + lecture). |
| `vierge.dsk` | créée par l'outil | rien | Créer/modifier une disquette vierge : ajouter un premier fichier (les 3 modes), sauvegarder, rouvrir. |
| `demo_edition.dsk` | créée par l'outil | `BONJOUR BAS` (BASIC, 74 o, Filer+AMSDOS) et `DONNEES BIN` (20 224 o, binaire, 2 chunks Filer, Filer+AMSDOS) | Le test complet : extraire les 2 fichiers (comparer avec les originaux), supprimer `DONNEES BIN` (recolle du paquet), ajouter un fichier, sauvegarder, relister. |

## Scénario de test rapide (GUI)

1. **Ouvrir** `demo_edition.dsk` → 4 lignes (2 fichiers × 2 couches).
2. **Extraire** `BONJOUR BAS` → un fichier `.bas` de 74 o contenant un
   programme BASIC « BONJOUR CPC ».
3. **Extraire** `DONNEES BIN` (couche `AMSDOS`) → 20 224 o de motif
   binaire `00 01 02 … FF` répété.
4. **Supprimer** `DONNEES BIN` → la liste passe à 2 lignes ; rouvrir le
   disque : la disquette fait toujours 194 816 o et `BONJOUR BAS` reste
   intact.
5. **Ouvrir** `greed.dsk` → essayer d'ajouter un fichier en mode
   `filer` : le message de protection doit apparaître.
6. **Onglet Gotek** : ajouter `greed.dsk` et `robot.dsk` en sources,
   générer le répertoire → `DISK001.adf`, `DISK002.adf`.
7. **Nouveau CP/M** → bouton « Nouveau CP/M » (ou `cpc-dsk new x.dsk --cpm`)
   → disque système CP/M 2.2 amorçable avec `AMSDOS.COM`, `DISCKIT2.COM`,
   `LOGO2.COM`, `LOGO2.SUB` : extraire/ajouter/supprimer des fichiers,
   sauvegarder, puis tester sur le Gotek (le vrai CP/M lit le répertoire
   de la piste 2).

## Scénario CP/M sur disques réels (CLI)

```
cpc-dsk info  test_disks/cpm22.dsk        # « Type de disque : CP/M 2.2 »
cpc-dsk list  test_disks/cpm22.dsk --source cpm
cpc-dsk list  test_disks/cpm22.dsk --source amsdos   # objets « legacy »
cpc-dsk read  test_disks/cpm22.dsk RITDEMO.BIN --out ritdemo.bin  # 11 264 o
cpc-dsk list  test_disks/planetfall_cpm.dsk          # PLANET.COM, PLANETFA.DAT…
```

> **Attention** : `greed.dsk`, `robot.dsk`, `abbey.dsk`, `sooty.dsk`,
> `compilation190.dsk` et les trois disques CP/M sont des disques réels
> d'époque. Travaillez sur des **copies** si vous voulez expérimenter la
> sauvegarde (l'outil n'écrit que sur le fichier ouvert, mais il vaut
> mieux préserver les originaux).
