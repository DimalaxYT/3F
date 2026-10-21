# Exemples générés par 3d-forge

Tous ces modèles ont été produits par le pipeline lui-même, de bout en bout
(recherche web → génération → photos des 6 faces → autocritique notée). Les
formats : GLB (web/moteurs), STL (impression 3D, étanche), USDZ (AR Apple).

## En arbre (légers, ~1 Mo — références de la CI visuelle)

| Dossier | Workflow | Ce que ça montre |
|---|---|---|
| [`chaise_scandinave/`](chaise_scandinave/) | **A** — recette | chaise paramétrique (style, bois, couleur d'assise), STL étanche 12,7 L |
| [`vase/`](vase/) | **A** — recette | amphore 35 cm, profil spline |
| [`rocket/`](rocket/) | **A** — recette | fusée à ailerons |

## Packs complets (~174 Mo) — restaurables à la demande

Les packs vitrine (game_ready Roblox/UE5, turntables, sculptures, specs
multi-parties) ne sont plus commités dans l'arbre : ils alourdissaient chaque
clone alors qu'ils sont **reconstructibles** et déjà stockés dans l'historique
GitHub. Pour les récupérer :

```bash
python3 scripts/fetch_examples.py                    # tous les packs
python3 scripts/fetch_examples.py --only katana      # un seul pack
```

| Pack | Workflow | Ce que ça montre |
|---|---|---|
| `katana/` | **D** — multi-parties | katana 0,97 m généré partie par partie en parallèle (5 specs vectorielles), GLB groupé texturé, STL union étanche, pack game_ready Dual-1024² Blade+Hilt |
| `epee_rouillee/` | **C** — multi-vues | « épée médiévale rouillée avec pommeau en or » : PBR texturé, IoU moyen 0.9152, `critique_log.json` (trace de la boucle notée 5.0 → 8.6) |
| `motocross/` | **B** — image → 3D | moto recalée sur photo : `score.json` IoU 0.55 → 0.74, STL étanche |
| `sci_fi_crate/` | **A** + game_ready | caisse articulée 44 pièces greebles, `ortho_guides/` peinture Z-buffer, pack Roblox/UE5 |
| `dragon_buste/` | GPU sculpt | buste organique 3 vues → SDF → STL étanche + pack jeu |

Pour reproduire : voir le [README principal](../README.md) — chaque exemple est
reconstructible avec les commandes des workflows A/B/C/D.
