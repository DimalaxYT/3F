# G36 — Heckler & Koch G36 (5,56 × 45 mm)

Modèle game-ready du fusil d'assaut allemand, construit pièce par pièce aux
**cotes réelles** (longueur totale 998 mm avec crosse sortie, canon 480 mm).

![Planche QA](qa_game_sheet.png)

## Lancer la génération

```bash
# Version exemple (30 840 tris de détail, textures Unreal 2048²)
python3 -c "
import sys, importlib.util; sys.path.insert(0,'scripts')
import game_ready as gr
spec = importlib.util.spec_from_file_location('g36','examples/g36_rifle/build_g36.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
gr.export_game_package(m.ground(m.build()), out_dir='exports/g36_rifle', name='g36_rifle',
                       lod0_tris=9200, tex_size=2048, engine='roblox_unreal')
"

# Ou la recette du catalogue (pipeline complet en une commande)
python3 scripts/turbo_forge.py g36 -o exports/g36 --target hero --tex-size 2048
```

## Ce qui est modélisé

| Zone | Détail reproduit |
|---|---|
| Boîtier | loft continu en polymère, arêtes arrondies, goupilles d'assemblage traversantes |
| Pontet-rail | barre surélevée + **fenêtre triangulaire de délestage** + rail Picatinny cranté 18 dents |
| Optique | point rouge intégré : corps, oculaire, objectif, lentille, **réticule émissif** (Neon Roblox), molettes |
| Crosse | volumétrique qui s'élargit vers l'arrière, **plaque de couche caoutchouc** débordante, fente de grenadière |
| Poignée | trapue à section constante, bouchon chanfreiné, stries de préhension |
| Détente | pontet **massif moulé** + détente lame cintrée (pas un fil) |
| Chargeur | 13 sections sur une **courbe qui plonge vers l'avant**, semelle débordante, nervures |
| Garde-main | 3 **lumières oblongues traversantes** par flanc, rail bas + rail latéral, grenadière |
| Canon | canon, bloc de gaz, hausse à **ailes de protection**, guidon, **flash-hider à dents** |
| Mécanique | poignée d'armement latérale, fenêtre d'éjection, déflecteur, sélecteurs ambidextres |

## Livrables

- `g36_rifle_game.glb` — LOD0 9 102 tris, 3 draw calls, 10 sockets gameplay
- `g36_rifle_LOD1.glb` / `_LOD2.glb` — 3 671 / 2 159 tris
- `roblox/` — `g36_rifle_roblox.glb` + 4 cartes **1024²** (plafond moteur) + `setup_g36_rifle.lua`
- `unreal/` — `SM_g36_rifle.glb` + `UCX_*` + `BC` / `ORM` / `N` DirectX / `N_gl` **2048²**
- `g36_rifle.stl` — watertight, imprimable
- `g36_rifle.zip` — bundle complet (30 Mo)

## Mesures

```
LOD0 9 102 tris · LOD1 3 671 · LOD2 2 159 · 47 → 3 draw calls
6 UCX · 10 sockets · 1 Neon (réticule)
0,40 × 3,53 × 1,21 Studs Roblox
gates --target hero : 24/24 LIVRABLE
```

## Pièges rencontrés (corrigés)

1. **`ring_perp` normalisait son axe en place** via `np.asarray` : le vecteur
   partagé entre sections successives était corrompu et le chargeur partait à
   `z = -1,17 m`. `np.array(..., copy=True)` obligatoire.
2. **`unmerge_vertices()` retourne `None`** (opère en place) — et surtout il
   casse l'étanchéité sur les pièces issues du CSG : il faut `merge_vertices()`
   + `fill_holes()` derrière, sinon `mk.union` refuse la pièce.
3. **Normales lissées autour des découpes** : `renderer._gather` lisse une arête
   dès que `dot(vnormale, normale_face) > 0.72` sur les 3 sommets, ce qui faisait
   baver la lumière sur les cloisons des évents. Les pièces usinées passent par
   `crisp()` (face-split) et un loft dense (`loft_y_fn`, 40 sections).
4. **`tex_size=4096` dépasse la RAM** (OOM à 3 Go) sur le bake PBR de
   `game_ready`. 2048² passe à 2,7 Go et suffit : `rbx_res = min(tex_size, 1024)`
   garde Roblox dans son plafond moteur automatiquement.
