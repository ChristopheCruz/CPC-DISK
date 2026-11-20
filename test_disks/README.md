# Disquettes de test

Cinq disquettes `.dsk` (format EXTENDED CPC DSK, géométrie CPC 40 pistes ×
9 secteurs × 512 o) pour tester l'éditeur, l'onglet Gotek et le support
CP/M 2.2, sans avoir à télécharger quoi que ce soit.

**Droits d'auteur.** Les disquettes de jeux commerciaux qui ont servi
pendant le développement (Infocom *Planetfall* et *Starcross*, *Yogi Bear*,
*Sooty & Sweep*, une compilation de jeux, un disque de boot) ne sont plus
fournies : elles sont protégées par le droit d'auteur. Les tests qui les
utilisaient sont sautés. Pour les relancer, place tes propres copies dans
ce dossier sous les mêmes noms (`planetfall_cpm.dsk`, `starcross_cpm.dsk`,
`greed.dsk`, `sooty.dsk`, `compilation190.dsk`, `abbey.dsk`) : elles sont
ignorées par git.

| Disquette | Origine | Contenu | À tester |
|-----------|---------|---------|----------|
| `robot.dsk` | réelle (Internet Archive, *Robot PD 14400*) | 10 fichiers Filer en 12 entrées (chunks 16 Ko) + 2 AMSDOS | Fichiers > 16 Ko : `LARA DOC` (45 312 o = 3 chunks), `LARA BIN` (8 576 o). Même protection à l'écriture Filer. |
| `cpm22.dsk` | réelle (Internet Archive, CP/M 2.2 + Amsdos 2.0) | Système CP/M 2.2 « System format » : 24 fichiers (répertoire piste 2) + 3 objets AMSDOS « legacy » | **Base de référence du module CP/M** : la génération `new --cpm` reproduit ses Track-Infos à l'octet près. Lister (24 fichiers), extraire `DISCKIT2.COM` (brut) ou `RITDEMO.BIN` (legacy → 11 264 o via l'objet AMSDOS), `DISC.BAS` (21 331 o). |
| `vierge.dsk` | créée par l'outil | rien | Créer/modifier une disquette vierge : ajouter un premier fichier (les 3 modes), sauvegarder, rouvrir. |
| `demo_edition.dsk` | créée par l'outil (catalogue AMSDOS) | `BONJOUR.BAS` (BASIC ASCII, sans en-tête), `DONNEES.BIN` (20 224 o, binaire avec en-tête, 2 extensions) et `README.MD` | Extraire, supprimer `DONNEES.BIN`, ajouter un fichier, sauvegarder, relister. |
| `seq16.dsk` | produite par RASM (projet SEQ-16) | `SEQ16.BIN`, 9 banques `.SMP`, 13 banques `.INS` : 23 fichiers, au-delà des 16 entrées du premier secteur du catalogue | Le catalogue complet (64 entrées) ; ajouter un fichier sans abîmer les autres. |

## Scénario de test rapide (GUI)

1. **Ouvrir** `demo_edition.dsk` → 4 lignes (2 fichiers × 2 couches).
2. **Extraire** `BONJOUR BAS` → un fichier `.bas` de 74 o contenant un
   programme BASIC « BONJOUR CPC ».
3. **Extraire** `DONNEES BIN` (couche `AMSDOS`) → 20 224 o de motif
   binaire `00 01 02 … FF` répété.
4. **Supprimer** `DONNEES BIN` → la liste passe à 2 lignes ; rouvrir le
   disque : la disquette fait toujours 194 816 o et `BONJOUR BAS` reste
   intact.
5. **Ouvrir** `seq16.dsk` → 23 fichiers (au-delà des 16 entrées du premier
   secteur du catalogue) ; ajouter un fichier, sauvegarder, relister.
6. **Onglet Gotek** : ajouter `seq16.dsk` et `robot.dsk` en sources,
   générer le répertoire → `DISK001.adf`, `DISK002.adf`.
7. **Nouveau CP/M** → bouton « Nouveau CP/M » (ou `cpc-dsk new x.dsk --cpm`)
   → disque système CP/M 2.2 amorçable avec `AMSDOS.COM`, `DISCKIT2.COM`,
   `LOGO2.COM`, `LOGO2.SUB` : extraire/ajouter/supprimer des fichiers,
   sauvegarder, puis tester sur le Gotek (le vrai CP/M lit le répertoire
   de la piste 2).

## Scénario CP/M sur disques réels (CLI)

```
cpc-dsk info  test_disks/cpm22.dsk        # format CP/M 2.2 (SYSTEM)
cpc-dsk list  test_disks/cpm22.dsk        # 24 fichiers du catalogue CP/M
cpc-dsk read  test_disks/cpm22.dsk RITDEMO.BIN --out ritdemo.bin  # 11 264 o
```

> **Attention** : `robot.dsk` et `cpm22.dsk` sont des disques réels
> d'époque. Travaillez sur des **copies** si vous voulez expérimenter la
> sauvegarde (l'outil n'écrit que sur le fichier ouvert, mais il vaut
> mieux préserver les originaux).

## Catalogue AMSDOS

Toutes ces disquettes utilisent le catalogue AMSDOS
standard (64 entrées de 32 o dans les blocs 0 et 1, blocs de 1 Ko repérés
par ID de secteur). C'est ce catalogue que lisent le CPC, CP/M et le
Gotek, et c'est lui que l'outil lit et écrit (`cpc_dsk/core/amsdos.py`).
Vérification : `LARA.DOC` de `robot.dsk` se lit sans coupure d'un secteur
à l'autre (`tests/test_amsdos.py`).
