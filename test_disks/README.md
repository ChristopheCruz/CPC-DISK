# Disquettes de test

Cinq disquettes `.dsk` (format EXTENDED CPC DSK, géométrie CPC 40 pistes ×
9 secteurs × 512 o sauf avis contraire) pour tester l'éditeur et l'onglet
Gotek, sans avoir à télécharger quoi que ce soit.

| Disquette | Origine | Contenu | À tester |
|-----------|---------|---------|----------|
| `greed.dsk` | réelle (Internet Archive, *Yogi Bear*) | 4 fichiers Filer + 4 objets AMSDOS | Lister, extraire `YOGI BAS`, hexdumper. **Écriture Filer refusée** (disque ambigu : objets AMSDOS dans le paquet Filer) — la protection doit s'afficher. |
| `robot.dsk` | réelle (Internet Archive, *Robot PD 14400*) | 10 fichiers Filer en 12 entrées (chunks 16 Ko) + 2 AMSDOS | Fichiers > 16 Ko : `LARA DOC` (45 312 o = 3 chunks), `LARA BIN` (8 576 o). Même protection à l'écriture Filer. |
| `abbey.dsk` | réelle, produite par SAM/WinAPE | Disque de boot, **aucun fichier** | S'ouvre sans erreur malgré la variante SAM : 42 pistes déclarées pour 39 réelles, pistes 1-38 en 15 secteurs × 256 o, traînée `Offset-Info` en fin de fichier. |
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

> **Attention** : `greed.dsk`, `robot.dsk` et `abbey.dsk` sont des disques
> réels d'époque. Travaillez sur des **copies** si vous voulez expérimenter
> la sauvegarde (l'outil n'écrit que sur le fichier ouvert, mais il vaut
> mieux préserver les originaux).
