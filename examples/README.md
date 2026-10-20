# Exemples générés par 3d-forge

Tous ces modèles ont été produits par le pipeline lui-même, de bout en bout
(recherche web → génération → photos des 6 faces → autocritique notée). Les
formats : GLB (web/moteurs), STL (impression 3D, étanche), USDZ (AR Apple).

| Dossier | Workflow | Ce que ça montre |
|---|---|---|
| [`epee_rouillee/`](epee_rouillee/) | **C** — génération multi-vues | « épée médiévale rouillée avec pommeau en or » : GLB **texturé PBR** (albedo + metallicRoughness + normal, rouille fBm, usure d'arêtes), planche des 6 faces, turntable, planche des références Stage 0, et `critique_log.json` — la trace complète de la boucle d'autocritique (notes 5.0 → 8.6, issues corrigées itération par itération) |
| [`motocross/`](motocross/) | **B** — image → 3D | moto recalée sur une photo KTM 450 : `reference.jpg`, `silhouette_overlay.png` (rouge/vert/jaune), `score.json` (IoU 0.55 → 0.74), STL étanche prêt impression |
| [`chaise_scandinave/`](chaise_scandinave/) | **A** — recette | chaise paramétrique (style, bois, couleur d'assise), STL étanche 12,7 L |
| [`vase/`](vase/) | **A** — recette | amphore 35 cm, profil spline |
| [`rocket/`](rocket/) | **A** — recette | fusée à ailerons |

Pour reproduire : voir le [README principal](../README.md) — chaque exemple est
reconstructible avec les commandes des workflows A/B/C (la spec finale de
l'épée est dans [`epee_rouillee/spec_iter6.json`](epee_rouillee/spec_iter6.json)).
