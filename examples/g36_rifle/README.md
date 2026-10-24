# G36E — Heckler & Koch G36 (5,56 × 45 mm), hard-surface

Modèle game-ready du fusil d'assaut allemand, reconstruit en **hard-surface** et
calé sur une **vue de profil photographique** (dépouillement au pixel, pas à l'œil).

![Planche QA](qa_game_sheet.png)

![Comparaison référence / rendu](compare_reference.png)

## La méthode (et pourquoi la v1 était ratée)

La v1 était entièrement faite de `rrect()` loftés avec un rayon de **10 mm sur un
boîtier de 42 mm de large** : 40 % de chaque flanc était arrondi. Résultat, aucun
plan, aucune arête, aucune ligne de lumière — un savon.

Ici chaque pièce est un **prisme extrudé** :

1. **Silhouette** : polygone anguleux en (y, z), extrudé le long de X.
2. **Section** : rectangle **chanfreiné** (octogone) en (x, z), extrudé le long de Y.
3. **Intersection** des deux → le corps a la bonne silhouette *et* la bonne section,
   avec un chanfrein de 2,2 mm qui court sur toute la longueur.

Un chanfrein à 45° sépare deux faces de `cos 45° = 0,707`, juste sous le seuil de
lissage de `renderer._gather` (0,72) : les arêtes restent **franches** sans
dupliquer un seul sommet. C'est ce qui donne le rendu polymère moulé / acier
phosphaté au lieu du savon.

### Contours mesurés sur la photo

Silhouette extraite par seuillage + remplissage des trous intérieurs, échelle
998 mm / 563 px, axe du canon à 33,5 % de la hauteur :

| Repère | Valeur mesurée |
|---|---|
| Longueur / hauteur | 998 × 291 mm (L/H 3,43) |
| Garde-main | y +318 → +146 mm, dessus +39, dessous −31 |
| Boîtier | y +146 → −238 mm, dessus +34, dessous −31 |
| Fenêtre de poignée de transport | y +84 → −97 mm, z +34 → +86 (**181 × 52 mm**) |
| Sommet de l'arche | z +100 |
| Bloc optique | y −97 → −238 mm, sommet +94, pente arrière jusqu'à +41 |
| Chargeur | 80 mm d'avant en arrière, pointe à −194 mm (point le plus bas) |
| Poignée pistolet | bas à −141 mm |
| Pontet | bas à −78 mm |
| Crosse squelette | dessus +24, dessous −31 → −127, fenêtre mesurée à −275/−442 |

Validation quantitative : **IoU silhouette 0,79** contre le masque de la photo
(l'overlay rouge/bleu est régénéré par le harnais décrit plus bas).

## Preview temps réel

```bash
python3 preview/serve_preview.py --port 8000   # -> http://localhost:8000
```

Visualiseur WebGL (three.js vendorisé, zéro CDN) : orbite, bascule LOD0/1/2,
affichage des arêtes franches, des sockets et des colliders UCX. Le mode
**comparaison** superpose la photo de référence à la silhouette 3D avec un
séparateur glissant — c'est le contrôle qui manquait à la v1. Voir
[`preview/README.md`](../../preview/README.md).

## Lancer la génération

```bash
# Version exemple
PYTHONPATH=scripts python3 -c "
import sys, importlib.util; sys.path.insert(0,'scripts')
import game_ready as gr
spec = importlib.util.spec_from_file_location('g36','examples/g36_rifle/build_g36.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
gr.export_game_package(m.ground(m.build()), out_dir='exports/g36_rifle', name='g36_rifle',
                       lod0_tris=9200, tex_size=2048, engine='roblox_unreal')
"

# Ou la recette du catalogue (source unique = ce même fichier)
python3 scripts/turbo_forge.py g36 -o exports/g36 --target hero --tex-size 2048
```

Contrôle rapide de la géométrie :

```bash
PYTHONPATH=scripts python3 examples/g36_rifle/build_g36.py
# 33 pièces · 2 992 tris · dims [0.073, 1.002, 0.291] · non étanches : aucune
```

## Ce qui est modélisé

| Zone | Détail reproduit |
|---|---|
| Garde-main | bloc chanfreiné **5 mm plus haut** que le boîtier (marche mesurée), **6 lumières oblongues fraisées** par flanc, âme sombre, grenadière |
| Boîtier | bloc chanfreiné, puits de chargeur, fenêtre d'éjection, 3 goupilles traversantes |
| Poignée de transport | arche en « П » à épaisseur constante, **fenêtre traversante 181 × 52 mm**, jambe avant en contrefort |
| Optique | bloc intégré, **lentille frontale encastrée**, oculaire, réticule émissif (Neon Roblox), tourelles dessus et côté |
| Crosse | **cadre squelette** de 38 mm de large, fenêtre mesurée, plaque de couche caoutchouc, charnière latérale |
| Poignée pistolet | loft chanfreiné incliné, 62 mm de large |
| Pontet | **boucle ajourée** (pas un bloc), détente lame |
| Chargeur | profil mesuré, nervures, **trous témoins** |
| Canon | Ø 20 mm, **cache-flammes ajouré Ø 23**, hausse repliée, guidon |
| Mécanique | poignée d'armement, sélecteurs ambidextres, grenadières avant/arrière |

## Livrables (`exports/g36_rifle/`)

| Fichier | Contenu |
|---|---|
| `g36_rifle_game.glb` | LOD0 — **2 860 tris**, 3 draw calls, 11 sockets |
| `g36_rifle_LOD1.glb` / `_LOD2.glb` | 1 943 / 1 263 tris |
| `g36_rifle_colliders.glb` | 6 hulls UCX (242 tris) |
| `roblox/` | GLB + PNG 1024² (SurfaceAppearance), script Luau de montage |
| `unreal/` | `SM_g36_rifle.glb` + BC / ORM / N (DirectX −Y) 2048² |
| `game_manifest.json`, `gates.json` | métadonnées et rapport de validation |
| `g36_rifle.zip` | **paquet complet (~20 Mo)** |

`python3 scripts/gates.py exports/g36_rifle --target hero` → **24/24**.

## Notes d'implémentation

- `mk.place()` ancre les boîtes **par la base en Z** mais centre en X/Y : oublier ce
  détail fait dépasser une pièce de 20 mm (ça a coûté une passe).
- `mk.extrude()` extrude vers **+Z avec base à z = 0** ; les transformations
  maison (`_M_X`, `_M_Y`) doivent donc compenser l'offset.
- Un chanfrein à 45° reste sous le seuil de lissage : ne pas le remplacer par un congé.
- Le renderer cadre sur la **sphère englobante** : sous `fov 38°` une arme de 1 m
  est rognée aux extrémités. Utiliser `fov 44°` pour le profil complet.
