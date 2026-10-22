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
mk.box(w, d, h)                        # pavé droit vif
mk.rounded_box(w, d, h, r=0.015)       # pavé congé arrondi continu (étanche)
mk.chamfer_box(w, d, h, c=0.008)       # bloc usiné CNC à chanfrein 45° franc
mk.tube_sweep(path, r=0.02, r_inner=0) # tube cintré lissé PCHIP (échappements, guidons, cadres)
mk.helix_spring(0.03, 0.006, 0.02, 7)  # vrai ressort hélicoïdal 3D (amortisseurs)
mk.cable(points, r=0.004, sag=0.02)    # durite hydraulique / câble souple
mk.cylinder(r, h, sections=32)
mk.frustum(r_bas, r_haut, h)           # tronc de cône
mk.cone(r, h)                          # apex propre, jamais de faces dégénérées
mk.sphere(r, center=(0,0,0), subdivisions=3)
mk.torus(R, r, center=None)            # posé à plat ; center défaut (0,0,r)
mk.tube(r_ext, r_int, h)               # bague fermée garantie étanche
mk.capsule(r, h_cyl)                   # pilule verticale, hauteur h_cyl+2r

# ---- révolution, extrusion, loft & sweep ----
mk.lathe([(r, z), ...], sections=48, smooth=True, close=True)
   # profil (rayon, hauteur) du bas vers le haut ; close=True referme sur
   # l'axe → étanche. Pour un creux (mug, bol, verre) : monter le mur extérieur,
   # traverser le bord, redescendre à l'intérieur, finir sur l'axe.
mk.extrude([(x, y), ...], hauteur)     # polygone XY extrudé en +Z
mk.loft([(sec0, z0), (sec1, z1), ...]) # relie N sections 2D/3D (carrosseries, manches)
mk.sweep(profile_2d, path_3d, scale=lambda t: (sx, sy))
   # balaye un profil 2D le long d'une courbe 3D arbitraire (repère de Bishop sans torsion :
   # lames courbées sori, cornes, poignées, tubulures)

# ---- bake PBR hybride sur géométrie paramétrique ----
# Combine précision CAO + atlas UV xatlas + 3 textures PBR (albedo, metallicRoughness, normal) !
b.bake_pbr(
    overlays=[
        {"type": "wrap", "on": "grip", "diamond": True, "under_color": "#dfd8c5", "count": 9.5},
        {"type": "hamon", "on": "blade", "axis": "x", "positive_edge": True},
        {"type": "rust", "on": "blade", "coverage": 0.35, "scale": 14.0},
        {"type": "wood_grain", "on": "top", "axis": "x", "rings": 14.0},
        {"type": "brushed_metal", "on": "blade", "axis": "z", "scale": 160.0},
        {"type": "edge_wear", "on": ["blade", "guard"], "amount": 0.55},
    ],
    texture_size=1024,
    normal_strength=2.0,
)

# ---- articulations hiérarchiques glTF (`v4`) + découpe impression 3D (`split_stl.py`) ----
b.def_joint("front_axle", pivot=(0.34, 0.0, 0.084), axis=(0, 1, 0))
b.add(wheel_mesh, alloy_m, name="wheel_fl", group="front_axle")
mk.export_glb_pbr(b.scene(), "out/car.glb")  # injecte KHR_materials_transmission/ior/clearcoat + joints !
# CLI découpe plateau imprimante 3D avec tenons/mortaises chanfreinés (jeu 0.20 mm) :
#   python3 scripts/split_stl.py out/katana.stl -o out/print_parts --bed 0.256 0.256 0.256
# CLI sculpture organique multi-vues GPU Datacenter -> .glb/.stl/.usdz étanche :
#   python3 scripts/gpu_sculpt.py --front front.png --side side.png --back back.png -o out/statue

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

## <a name="organique"></a>4B. Sculpture Organique, Personnages, Bustes & Créatures (`organic.py`)

> **Règle absolue** : pour un personnage, un buste (Mario, héros, mascotte), un animal ou une créature sans vraies photos multi-vues, **n'invente jamais d'images 2D avec `PIL`/`matplotlib`**. Utilise `organic.py` + `meshkit.py` et passe le script à `scripts/turbo_forge.py` ! Voir les 3 architectures complètes de référence dans **`scripts/recipes/characters.py`** (`hero_bust`, `stylized_character`, `dragon_creature`).

```python
import sys; sys.path.insert(0, "scripts")
import meshkit as mk, organic as org

def build() -> mk.Builder:
    b = mk.Builder("my_character")
    # 1. Sculpture argile SDF continue C¹ (crâne, joues, museau, torse, orbites douces) :
    s = org.Sculpt(bounds=((-0.09, -0.10, 0.08), (0.09, 0.09, 0.27)), res=72)
    s.capsule((0, 0, 0.09), (0, 0, 0.15), 0.032, 0.035, k=0.012)
    s.ellipsoid((0, 0, 0.18), (0.061, 0.065, 0.066), k=0.016)
    s.ellipsoid((0.034, -0.034, 0.156), (0.030, 0.028, 0.025), k=0.018, mirror_x=True)
    s.ellipsoid((0.023, -0.056, 0.182), (0.016, 0.010, 0.019), mode="sub", k=0.007, mirror_x=True)
    s.ellipsoid((0, -0.067, 0.165), (0.019, 0.023, 0.016), k=0.006)
    b.add(s.to_mesh(smooth_iter=4, target_tris=4600), mk.mat.skin("#f2a97e"), name="head")

    # 2. Yeux 4 couches (sclère + iris + pupille + reflet spéculaire) :
    org.add_stylized_eyes(b, center_y=-0.052, center_z=0.181, spacing_x=0.023,
                          radius=0.0148, iris_color="#2563eb")

    # 3. Courbes effilées étanches (sourcils, moustache, cornes, queue, mèches) :
    b.add(org.tapered_curve([(0.009,-0.057,0.200),(0.023,-0.058,0.206),(0.037,-0.051,0.200)],
                            [0.0046, 0.0056, 0.0040]),
          mk.mat.clay("#4a2512"), name="brow_r")

    # 4. Visière / épaulière courbée 3D + socle de galerie 100 % étanche :
    b.add(org.curved_visor(width=0.114, length=0.052, arch=0.018),
          mk.mat.enamel("#dc2626"), name="visor", at=(0, -0.045, 0.205))
    p_base, p_ring = org.museum_plinth(0.15, 0.15, 0.036, round_profile=True)
    b.add(p_base, mk.mat.stone("#262930"), name="plinth")
    b.add(p_ring, mk.mat.metal("#f2c94c", roughness=0.22), name="plinth_ring")
    return b
```

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
