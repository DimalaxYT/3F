# Cookbook — construire n'importe quel objet avec meshkit

> À lire quand la demande ne correspond à aucune recette du catalogue.
> C'est le cœur du skill : **vous** êtes le générateur, meshkit est la main.

## Table des matières
1. [La méthode en 6 étapes](#méthode)
2. [API cheatsheet](#api)
3. [Patterns éprouvés](#patterns)
4. [Exemple travaillé : table basse en bois](#exemple)
5. [Erreurs classiques](#erreurs)

## <a name="méthode"></a>1. La méthode en 6 étapes

**Étape 1 — Décomposer.** Quelques questions suffisent :
- Quelles **parties** compose l'objet ? (une chaise : 4 pieds, assise, dossier)
- Chaque partie est-elle une **primitive** (box/cylinder/sphere/torus), un
  **solide de révolution** (tout ce qui est tourné : verre, bol, pied de lampe),
  une **extrusion** (profil constant : lame, rail, toit) ou un **CSG**
  (trous, creux, assemblages) ?
- Y a-t-il des **répétitions symétriques** ? (pieds de table → boucle)

**Étape 2 — Coter en mètres.** Chercher les dimensions réelles de l'objet
(une table basse : 1,0 × 0,6 × hauteur 0,42). Si l'utilisateur donne une
taille, la respecter ; sinon choisir une valeur plausible et le dire.

**Étape 3 — Choisir les matériaux.** Voir `materials.md`. Un objet réaliste
mélange 2 à 4 matériaux max (bois + métal, céramique + liège…).

**Étape 4 — Écrire le builder.** Créer un `mk.Builder("nom")`, ajouter les
pièces (transformations : `rot` puis `at`), nommer chaque pièce (le rapport
de débogage s'en sert). Encapsuler dans une fonction paramétrée — si la
demande est générique, l'enregistrer comme recette.

**Étape 5 — Exporter + regarder.** Utiliser `generate.py` si une recette
existe, sinon un mini-script (voir exemple) : exports + rendus, puis **lire
les PNG**. Corriger les proportions avant de livrer — c'est le même réflexe
qu'un dessinateur : coup d'œil, ajustement, coup d'œil.

**Étape 6 — Valider.** `validate.py` sur le STL si impression 3D : étanchéité
et volume sont bloquants.

## <a name="api"></a>2. API cheatsheet

```python
import sys; sys.path.insert(0, "<chemin_du_skill>/scripts")
import meshkit as mk

# ---- primitives (base z=0, centrées XY, mètres) ----
mk.box(w, d, h)                        # pavé
mk.cylinder(r, h, sections=32)
mk.frustum(r_bas, r_haut, h)           # tronc de cône
mk.cone(r, h)                          # apex propre, jamais de faces dégénérées
mk.sphere(r, center=(0,0,0), subdivisions=3)
mk.torus(R, r, center=None)            # posé à plat ; center défaut (0,0,r)
mk.tube(r_ext, r_int, h)               # bague étanche
mk.capsule(r, h_cyl)                   # pilule verticale, hauteur h_cyl+2r

# ---- révolution & extrusion ----
mk.lathe([(r, z), ...], sections=48, smooth=True, close=True)
   # profil (rayon, hauteur) du bas vers le haut ; close=True referme sur
   # l'axe → étanche. Pour un creux (mug, bol) : monter le mur extérieur,
   # traverser le bord, redescendre à l'intérieur, finir sur l'axe.
mk.extrude([(x, y), ...], hauteur)     # polygone XY extrudé en +Z

# ---- CSG (résultats garantis étanches) ----
mk.union([m1, m2, ...])
mk.difference(base, [outil1, outil2])
mk.intersection(a, b)

# ---- transformations (in-place, chaînables) ----
mk.place(m, x=0, y=0, z=0)
mk.rot_x(m, deg); mk.rot_y(m, deg); mk.rot_z(m, deg)
mk.scale(m, s)                         # scalaire ou triplet
mk.ground(m)                           # repose sur le sol

# ---- matériaux ----
mk.mat.wood("#8a5a2b", 0.55)     # (couleur, rugosité)
mk.mat.ceramic("#e8e4dc", 0.15)
mk.mat.plastic("#c8c8c8", 0.35); mk.mat.paint("#c0392b", 0.45)
mk.mat.glass("#cfe8ef", opacity=0.35, roughness=0.05)
mk.mat.fabric(...); mk.mat.rubber(...)
mk.mat.metal("#9aa0a6", 0.3)           # métallique générique
mk.mat.named_metal("steel"|"brass"|"gold"|"copper"|"bronze"|"silver"|"aluminum"|"chrome")
mk.mat.emissive("#fff2cc", strength=1.2)   # ampoule, écran

# ---- assemblage ----
b = mk.Builder("nom_objet")
b.add(mesh, material, name="pièce", at=(x,y,z), rot=(rx,ry,rz))
   # rot (deg, autour de l'origine du mesh) appliqué AVANT la translation
b.stats()          # pièces, triangles, dimensions bbox
b.scene()          # trimesh.Scene avec PBR → export GLB / rendus
b.union_solid()    # solide unique étanche → export STL
mk.export_obj_with_mtl(scene, "fichier.obj")

# ---- export USDZ ----
import usdz_export; usdz_export.export_usdz(scene, "fichier.usdz")

# ---- rendus (PNG) ----
import renderer
renderer.render_views(scene, outdir, "stem", views=["front", "three_quarter", "top"], size=1024)
```

## <a name="patterns"></a>3. Patterns éprouvés

**Symétries** — construire une pièce, la transformer dans la boucle :
```python
for i in range(4):
    ang = np.deg2rad(90 * i)
    leg = mk.frustum(0.03, 0.02, 0.72)
    mk.rot_z(leg, np.rad2deg(ang))
    b.add(leg, wood, name=f"leg{i}", at=(np.cos(ang)*0.35, np.sin(ang)*0.35, 0))
```

**Creux (mug, bol, cache-pot)** — profil lathe aller-retour :
```python
wall = 0.005
mk.lathe([(0,0), (r,0), (r,h), (r-wall,h), (r-wall,wall), (0,wall)])
```

**Trous traversants** — CSG différence avec un outil qui *dépasse* des deux
côtés (jamais de coplanarité : les faces alignées créent des artefacts) :
```python
tool = mk.cylinder(r, h + 0.02)      # dépasse de 1 cm de chaque côté
mk.place(tool, 0, 0, -0.01)
hole = mk.difference(base, [tool])
```

**Profils organiques** — points de contrôle + PCHIP (jamais d'overshoot) :
```python
from scipy.interpolate import PchipInterpolator
zt = [0, 0.06, 0.30, 0.62, 0.88, 1.0]        # hauteurs normalisées
rt = [0.55, 0.80, 1.0, 0.72, 0.40, 0.45]     # rayons relatifs
z = np.linspace(0, 1, 40); r = PchipInterpolator(zt, rt)(z)
profile = [(ri * r_max, zi * h_tot) for ri, zi in zip(r, z)]
```

**Pièces inclinées** — construire le long de Z, tourner, placer : la rotation
tourne autour de l'origine du mesh, donc pour un pied incliné dont la base
reste au sol : `rot_x` d'abord, puis `at` positionne la base.

**Extrusions orientées** — un profil extrudé vit dans le plan XY et pousse en
+Z. Pour un pan vertical dans un autre plan : `rot_x(±90)` puis recentrer
(l'extrusion part de 0, pas de -longueur/2). C'est la source d'erreur n°1 —
vérifier avec `mesh.bounds` après rotation.

## <a name="exemple"></a>4. Exemple travaillé : table basse en bois

Demande : « une table basse ronde en noyer, 80 cm de diamètre, 40 cm de haut,
avec un entretoise ».

```python
import numpy as np, meshkit as mk

R, H = 0.40, 0.40                      # rayon plateau, hauteur totale
noyer = mk.mat.wood("#5d4037", 0.5)

b = mk.Builder("coffee_table")
# plateau : disque de 3 cm d'épaisseur au sommet
b.add(mk.cylinder(R, 0.03, sections=48), noyer, name="top", at=(0, 0, H - 0.03))
# ceinture sous le plateau (détail qui vend le réalisme)
b.add(mk.tube(R - 0.02, R - 0.07, 0.05, sections=48), noyer,
      name="apron", at=(0, 0, H - 0.08))
# 4 pieds fuselés, légèrement inclinés vers l'extérieur
for i in range(4):
    ang = np.deg2rad(45 + 90 * i)
    foot = mk.frustum(0.024, 0.015, H - 0.06)
    mk.rot_x(foot, 5.0)                       # incline autour de la base
    mk.rot_z(foot, -np.rad2deg(ang))
    b.add(foot, noyer, name=f"leg{i}",
          at=(np.cos(ang) * (R - 0.08), np.sin(ang) * (R - 0.08), 0))
# entretoise annulaire à mi-hauteur des pieds
b.add(mk.torus(R - 0.13, 0.012, major=40, minor=10, center=(0, 0, 0.14)),
      noyer, name="stretcher")

scene = b.scene()
scene.export("coffee_table.glb")
b.union_solid().export("coffee_table.stl")
import renderer
renderer.render_views(scene, ".", "coffee_table", size=1024)
```

Puis : lire les PNG, vérifier l'inclinaison des pieds et l'entretoise,
ajuster. Temps total : 2 minutes, zéro API.

## <a name="erreurs"></a>5. Erreurs classiques

| Symptôme | Cause | Remède |
|---|---|---|
| `CSG: ... doit être étanche` | primitive bricolée à la main ou mesh importé | n'alimenter le CSG qu'avec des primitives/CSG meshkit |
| Objet à moitié enterré | rotation d'extrusion vers -Z | `rot_x(+90)` pas -90, puis recentrer (voir patterns) |
| Panneau « debout » au lieu de couché | rotation autour du mauvais axe (Y ne relève pas Y) | composer `rot_x(90)` + `rot_z(90)` |
| Faces noires sur le métal | normal : le renderer a un env hémisphérique, mais un mesh à faces inversées reste noir | vérifier le winding (fix_normals est automatique sur les primitives) |
| STL « non étanche » | pièces simplement juxtaposées sans recouvrement | faire se chevaucher les pièces (>1 mm) avant `union_solid` |
| Rendu tout blanc / tout noir | matériau émissif trop fort / lumière | `strength` émissif ≤ 2, vérifier les couleurs hex |
| Proportions grotesques | unités en cm au lieu de m | 30 cm = 0.3 |

## <a name="references"></a>6. Stage 0 & livraison complète (recherche web, toutes les faces)

Toute génération sérieuse suit désormais ce protocole (détails dans SKILL.md) :

1. **Recherche web** avec tes outils de recherche : 1 requête « objet entier »
   (photos musée/catalogue), 1 par détail notable, 1 pour la texture/matière.
2. **Téléchargement** de 3–6 images de référence :
   `python3 scripts/research.py fetch --urls ... --dir refs_raw/`
3. **Planche des détails à respecter** :
   `python3 scripts/research.py build --dir refs_raw/ --title "..." --out .../references
   --queries ... --notes "détail 1" "détail 2" ...`
   → `reference_sheet.png` (l'image des détails), `palette_hints.json`
   (couleurs mesurées + metallic/roughness déduits), `references.json`.
4. **Génération** avec la palette mesurée, puis livraison :
   - recette : `generate.py <recette> --set color=<hex mesuré> --faces all`
   - Meshy-mode : `meshgen.py spec.json --faces all --references .../references`
5. **QA finale** : les 6 photos de faces (`*_all_faces.png`) + le turntable
   (`*_turntable.png`) doivent montrer CHAQUE détail de `--notes`.
   Cohérence face/dos/gauche : même objet, mêmes matériaux, textures stables.

Pourquoi : Meshy génère ses vues préviews depuis le même objet 3D — les
planches `--faces all` sont l'équivalent déterministe, et la planche de
références remplace les données d'entraînement du modèle de diffusion.
