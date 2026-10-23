---
name: 3d-forge
description: >-
  Use when the user asks for a 3D model, character bust, mascot, figurine, creature,
  game asset, prop, weapon, vehicle, printable STL, or an export for Roblox Studio /
  Unreal Engine 5 (or Unity/Godot/AR). Pure-CPU & Hybrid Exact CAD + Smooth SDF Clay
  Organic Sculpting toolkit (v5.8): generates clean, well-proportioned, color-accurate
  3D assets engineered for **Roblox Studio** (`PNG`-embedded `.glb`, exact `Studs`
  scaling `1 Stud = 0.28 m`, budget `< 9 800 tris`/`MeshPart`, `SurfaceAppearance`
  `1024²` avec AO baked, `Neon_*` auto-split, `setup_<Name>.lua`), **Unreal Engine 5**
  (`SM_<Name>.glb` + `UCX_*` + `ORM` + DirectX `-Y`), and 3D printing (`100 % watertight`
  `.stl`), automatically bundled into a ready-to-download **`<name>.zip`** archive — works
  100 % offline on pure CPU in **Claude.ai**, CLI, or Arena without `preview.html`.
---

# 3d-forge v6.1 — Photo-Faithful 3D Engine + Organic SDF + Exact CAD (**`.zip` Bundle Ready**)

> ## 🚨 RÈGLE N°0 ABSOLUE : QUAND L'UTILISATEUR ENVOIE UNE PHOTO (« génère-moi ça ») !
> - **INTERDICTION TOTALE** de prendre une recette générique du catalogue (`dragon_creature`, `car`, `hero_bust`, etc.) ou d'improviser des formes « patate / ballon » quand une photo de référence est fournie !
> - **PROTOCOLE OBLIGATOIRE PHOTO → 3D EN 4 ÉTAPES (`scripts/photo_to_3d.py v2`, ZÉRO DÉTAIL OUBLIÉ)** :
>   1. **Mesurer la photo + Loupes 300 % (`< 0.5 s`)** :
>      `python3 scripts/photo_to_3d.py inspect <photo.png> -o exports/ref --height 0.44`
>      Lis **obligatoirement** `exports/ref/blueprint_grid.png` **ET** `exports/ref/zoom_details.png` avec `read_file` ainsi que `slice_spans` dans `exports/ref/photo_blueprint.json` pour relever chaque détail (yeux, pupilles, crocs, narines, cornes, écailles, griffes, nervures).
>   2. **Sculpter `custom_<nom>.py` en multi-groupes aux coordonnées `UZ(x, u, z)` exactes** *(référence : `examples/crimson_dragon/build_crimson_dragon.py`)* :
>      - Utilise `b.def_joint("head", ...)` / `b.def_joint("wings", ...)` + `joint_tex_size=1024` pour offrir un atlas `1024²` et un budget de triangles dédié à la tête (orbites creusées, globes oculaires + pupilles fendues, 32 crocs d'ivoire `#f4eee4`, narines, cornes) et aux ailes (`org.bat_wing(..., membrane_thickness=0.015)` sans déchirure QEM), + `org.displace_scales`, `org.armored_scutes`, `org.ridge_spines`.
>   3. **Projeter la vraie texture PBR + micro-normales de la photo (`360°`, `0 %` halo blanc)** :
>      `python3 scripts/photo_to_3d.py project <photo.png> exports/<nom> -n <nom> --azimuth 86 --elevation 3.5 --fov 38`
>   4. **Cuire le 4K (`render_4k/`), vérifier au Microscope 300 % (`photo_match.png` + `photo_details_zoom.png`), valider `gates.py --target showcase` (`26/26`) et livrer `<nom>.zip`** :
>      ```bash
>      python3 scripts/photo_to_3d.py verify <photo.png> exports/<nom>/<nom>_game.glb -o exports/<nom>/photo_match.png --zoom exports/<nom>/photo_details_zoom.png --azimuth 86 --elevation 3.5 --fov 38
>      # 4K : 3 atlas x 7 cartes 4096² reconstruites (jamais un upscale du 1024²)
>      python3 -c "import sys;sys.path.insert(0,'scripts');import texture_4k as t;t.synthesize_4k_maps('exports/<nom>','<nom>',photo_path='<photo.png>')"
>      python3 scripts/gates.py exports/<nom> --target showcase
>      python3 scripts/packager.py exports/<nom> -n <nom>
>      ```
>      Inspecte **obligatoirement** `photo_match.png` **ET** `photo_details_zoom.png` avec `read_file`, puis **présente / livre `exports/<nom>/<nom>.zip`** (aucun `preview.html` n'est généré !).

> ## 🚨 RÈGLE D'OR ABSOLUE (CLAUDE.AI / CLI / ARENA) — ZÉRO DESSIN 2D `PIL` !
> - **INTERDICTION FORMELLE** de dessiner des images 2D synthétiques (`PIL.ImageDraw`, `matplotlib`, bruit RGB) pour les passer à `--front` / `--side` (`gpu_sculpt.py`) ! Une ellipse 2D extrudée donne une patate fondue aux couleurs sales.
> - **Personnage, buste (Mario, héros, mascotte), figurine, animal ou créature sans vraies photos/rendus IA photoréalistes** : modélise **directement en vraie 3D propre** dans un script `custom_<nom>.py` avec **`meshkit.py` + `organic.py`** (`mk.Sculpt` argile SDF `C¹` lisse + `mk.curved_visor` + `mk.tapered_curve` + `mk.add_stylized_eyes` + matériaux séparés nets `mk.mat.skin` / `enamel` / `denim` / `clay`), en t'inspirant directement de **`scripts/recipes/characters.py`** (`hero_bust`, `stylized_character`, `dragon_creature`) !
> - N'utilise `turbo_forge.py --front f.png --side s.png` **QUE** si l'utilisateur fournit de vraies vues orthographiques haute définition ou si tu appelles un vrai modèle de diffusion `generate_image` photoréaliste (`offer_options=False`, fond neutre uni `#e6e6e6`, zéro ombre au sol).

> ## ⚡ CONTRAT DE VITESSE & PROFILS D'EXÉCUTION
> Le chemin par défaut est **`turbo`** : **UNE** commande (`scripts/turbo_forge.py`,
> 11–18 s CPU), **UNE** planche lue (`qa_game_sheet.png`), **25+ gates mesurées** (`gates.json`),
> **1 passe + 1 retouche ciblée max** si un détail visuel ou une gate cloche :
>
> | profil | recherche web | vues lues | boucle notée | usage |
> |---|---|---|---|---|
> | `turbo` (défaut) | jamais (`research.py fetch` interdit) | `qa_game_sheet.png` seule | `critique.py --fast` (1 retouche max) | toute demande agent standard |
> | `standard` | requêtes web, pas de download | 3 vues + planche | seuil/budget = `critique.py policy` | objet complexe sensible aux proportions |
> | `showcase` | Stage 0 complet (`research.py fetch`) | `--faces all` (14 images) | boucle complète | livraison vitrine / README |
>
> **Seuil & budget d'itérations : source de vérité = `python3 scripts/critique.py policy`**.

## 1. Choisir le workflow (arbre de décision)

```
demande utilisateur
 ├─ une recette existe (`generate.py --list` / references/recipes.md, 23 recettes dont
 │  `hero_bust`, `stylized_character`, `dragon_creature`, `katana`, `sci_fi_crate`, `car`...) ?
 │    ├─ oui (ou variante couleur/taille via `--set`) → `turbo_forge.py <recette> --set ...`
 │    └─ livrable print/vitrine multi-formats         → `generate.py <recette> ...`
 ├─ personnage, buste, mascotte, jouet ou créature inédit (Claude.ai / CPU ou design net) ?
 │    → écrire `custom_<nom>.py` avec **`meshkit` + `organic`** (voir §3B & `scripts/recipes/characters.py`)
 │      puis `python3 scripts/turbo_forge.py custom_<nom>.py -o out/<nom>`
 ├─ objet hard-surface inédit (arme, véhicule, meuble, outil, coffre, architecture) ?
 │    → écrire `custom_<nom>.py` avec **`meshkit` + `greebles`** (voir §3A)
 │      puis `python3 scripts/turbo_forge.py custom_<nom>.py -o out/<nom>`
 └─ créature ultra-détaillée AVEC outil `generate_image` photoréaliste disponible ?
      → `generate_image` orthographique `front` + `side` (+ `back`) EN PARALLÈLE (`offer_options=False`)
        puis `python3 scripts/turbo_forge.py --front f.png --side s.png --name <nom> -o out/<nom>`
```

Règles dures :
1. **Jamais `meshgen.py` sur du mécanique** — `meshkit.py` + `greebles.py` uniquement.
2. **Jamais de PNG dessiné au code Python (`PIL` / `matplotlib`)** en entrée de `--front/--side`.
3. **Sépare toujours chaque couleur franche en sa propre pièce `b.add(mesh, mat, name=...)`** : le bake booléen surfacique de `game_ready.py` découpe des frontières de matériaux nettes au pixel, zéro bavage et zéro fausse ombre interne !

## 2. Le protocole 1 commande (`turbo_forge.py`)

```bash
# Recette du catalogue (23 recettes, ~11-16 s CPU, tous livrables + gates)
python3 scripts/turbo_forge.py hero_bust --set cap_color="#16a34a" shirt_color="#16a34a" -o out/luigi_bust
python3 scripts/turbo_forge.py katana --lod0-tris 8200 -o out/katana

# Script 3D sur mesure (personnage organique OU hard-surface mécanique) :
python3 scripts/turbo_forge.py custom_asset.py --lod0-tris 4200 -o out/custom_asset

# Sculpture multi-vues UNIQUEMENT depuis vraies images IA photoréalistes :
python3 scripts/turbo_forge.py --front f.png --side s.png --name creature -o exports/creature

# Options : --target hero|ugc|print | --split-bed (plateau 256 mm) | --gif | --json
```

Chaque run écrit dans `exports/<nom>/` et empaquette automatiquement tout dans **`exports/<nom>/<nom>.zip`** : `<nom>_game.glb` (échelle métrique vraie `1.0x`, WebP léger, verre/clearcoat/néon) + LOD1/LOD2, `roblox/` (`<name>_roblox.glb` PNG pur en `Studs` + 4 maps + `setup_<name>.lua`), `unreal/` (`SM_<name>.glb` + `UCX_*` + BC/ORM/N DirectX `-Y`), `<nom>.stl` 100 % étanche, `qa_game_sheet.png`, `gates.json`, `qa_summary.md` et `game_manifest.json` (**sans aucun `preview.html`**).

**Contrôle visuel & livraison `.zip` obligatoires** : ouvre **toujours** `qa_game_sheet.png` (et `photo_match.png` si généré depuis une photo) avec `read_file`, vérifie face, profil, 3/4 LOD0 et ORM, puis **livre `exports/<nom>/<nom>.zip` directement à l'utilisateur** (`present_file` sur `<nom>.zip`).

## 3. Cheatsheet API exact (`custom_<name>.py` — prêt à copier sans lire le code)

### 3A. Hard-Surface, Architecture & Mécanique (`meshkit` + `greebles`)

```python
import sys; sys.path.insert(0, "scripts")
import meshkit as mk, greebles as grb

def build() -> mk.Builder:
    b = mk.Builder("my_prop")  # Mètres: X=droite(+), Y=AVANT(-)/DOS(+), Z=HAUT(+), sol à z=0 !
    # Matériaux propres par défaut (ZÉRO boue ni rivets parasites hors pièces nommées `armor`/`crate`/`hull`) :
    #   mk.mat.enamel("#e11d48"), mk.mat.ceramic("#f2efe9"), mk.mat.paint("#2563eb"),
    #   mk.mat.car_clearcoat("#dc2626"), mk.mat.metal("#d4af37", roughness=0.22, metallic=0.9),
    #   mk.mat.brushed_stainless(), mk.mat.wood("#7c4a24"), mk.mat.leather("#5c3a21"),
    #   mk.mat.knobby_rubber("#1f2023"), mk.mat.glass("#bae6fd", opacity=0.28),
    #   mk.mat.emissive("#00e5ff", strength=2.4)  # -> auto-extrait en `Neon_*` dans Roblox !
    # Primitives CAO 100 % étanches :
    #   mk.box(w,d,h), mk.chamfer_box(w,d,h,c=None), mk.rounded_box(w,d,h,r=None),
    #   mk.cylinder(r,h,sections=36), mk.tube(r_out,r_in,h), mk.cone(r,h), mk.frustum(r1,r2,h),
    #   mk.sphere(r), mk.capsule(r,h_cyl), mk.torus(R,r), mk.extrude(pts2d,height),
    #   mk.lathe(profile_rz,sections=48), mk.loft(sections), mk.tube_sweep(path_xyz,r),
    #   mk.union([...]), mk.difference(base,[...]), mk.place(m,x,y,z), mk.rot_x/y/z(m,deg)
    # Greebles mécaniques étanches : grb.picatinny_rail(), grb.louver_vent(), grb.hex_bolt(),
    #   grb.bolt_array(pts,nrms), grb.ribbed_conduit(path), grb.corner_armor_cap(), grb.toggle_latch()
    # Assemblage : b.add(mesh, mat, name, at=(x,y,z), rot=(rx,ry,rz), group=None)
    #              b.def_joint(group, pivot, axis) ; b.def_socket("SOCKET_grip", (x,y,z))
    return b
```

### 3B. Organique, Masques Sculptés, Personnages, Bustes & Créatures (`meshkit` + `organic`)

```python
import sys; sys.path.insert(0, "scripts")
import meshkit as mk, organic as org

def build() -> mk.Builder:
    b = mk.Builder("my_character")  # Face regardant TOUJOURS vers -Y ! Sol posé à z = 0 !
    m_skin = mk.mat.skin("#f2a97e")          # peau chaude vivante (jamais blanc craie #ffffff !)
    m_red  = mk.mat.lacquer("#a61c1c")       # laque japonaise urushi profonde (masques Tengu/Noh, armures)
    m_hat  = mk.mat.enamel("#dc2626")        # émail brillant pur, zéro métal
    m_hair = mk.mat.clay("#4a2512")          # brun mat sculpté

    # 1. Sculpture argile SDF continue C¹ (`ellipsoid` + `capsule` + `sweep` en relief OU en creux !)
    s = org.Sculpt(bounds=((-0.10, -0.18, 0.0), (0.10, 0.05, 0.26)), res=78)
    s.ellipsoid((0, 0, 0.16), (0.075, 0.055, 0.088), k=0.012)                              # crâne / front
    s.sweep([(0.025,-0.043,0.128),(0.056,-0.033,0.136),(0.075,-0.007,0.150)],              # pommettes C¹
            [0.014, 0.018, 0.012], k=0.013, mirror_x=True)
    s.sweep([(0,-0.038,0.148),(0,-0.110,0.142),(0,-0.170,0.127)],                          # long nez / museau C¹
            [0.021, 0.018, 0.014], k=0.012)
    s.sweep([(0.019,-0.052,0.141),(0.055,-0.036,0.156)], [0.010, 0.009],                   # orbites creusées !
            mode="sub", k=0.0045, mirror_x=True)
    b.add(s.to_mesh(smooth_iter=4, target_tris=5600), m_red, name="sculpted_shell")

    # 2. Yeux anatomiques sculptés sans protubérance (`org.add_sculpted_eyes` pour masques/créatures/bustes
    #    ou `org.add_stylized_eyes` pour mascottes), crocs/sourcils C² (`org.tapered_curve`), visières (`org.curved_visor`)
    #    ⚠️ RÈGLE CRITIQUE CYLINDRE/ROTATION : `mk.cylinder(r, h)` va de `z=0` à `z=+h` ; `mk.rot_x(cyl, +90°)`
    #    envoie `+Z -> -Y` VERS L'AVANT ! Toujours utiliser `org.add_sculpted_eyes(...)` (pupille concave taillée par
    #    `mk.intersection` en retrait dans le globe) et toujours tourner un ellipsoïde centré à `(0,0,0)` AVANT `mk.place` !
    org.add_sculpted_eyes(b, center_y=-0.052, center_z=0.181, spacing_x=0.028)

    # 3. OBLIGATOIRE sur tout MASQUE, CASQUE ou COQUE CREUSE (`tengu_mask` dans `recipes/characters.py`) :
    #    évide d'un seul coup TOUTES les pièces internes pour que RIEN ne dépasse jamais à l'arrière !
    # b.trim_inside(inner_cavity_mesh, exclude=("cord", "eyelet"))
    return b
```

## 4. Règles de Design, Couleurs & Proportions (obligatoires)

- **Hiérarchie des formes** : volumes primaires lisses (`Sculpt` / `superellipsoid` / `lathe`) + silhouettes secondaires franches (casquette, visière, cornes, épaulières, anses) + détails tertiaires nets en léger relief franc (`>= 2.5 mm` devant la surface d'appui pour ne jamais être enterrés par le maillage `LOD0` !).
- **Palette & albédos PBR** :
  - Blancs propres = `#f2f2f5` (jamais `#ffffff` saturé) ; noirs profonds = `#181a20` (jamais `#000000` mort) ; peau = `#f2a97e` / `#e09468` (chaleureuse et saturée).
  - N'utilise `metallic > 0.5` **que** sur de vrais métaux (or, laiton, acier, lame). Peau, tissu, céramique, casquette, émail, bois et cuir doivent toujours rester à **`metallic = 0.0`**.
  - Évite de nommer une pièce non industrielle `armor` / `crate` / `hull` / `panel` (ces mots-clés activent volontairement les rivets et rainures sci-fi).
- **Conventions spatiales** : mètres (`height=0.28` = 28 cm), **`Z` vers le haut (`z = 0` posé au sol)**, **face avant vers `-Y`**.

## 5. Quick start hors jeu vidéo (print / web / AR)

```bash
python3 scripts/generate.py --list                 # catalogue (+ --markdown)
python3 scripts/generate.py vase --out ./out       # GLB + STL + 3 PNG + report.json
python3 scripts/generate.py vase --set shape=amphora height=0.35 color="#7a2e1d" \
    --formats glb obj stl usdz --views front three_quarter top --size 1024
python3 scripts/validate.py out/vase/vase.stl      # exit 1 si non print-safe
python3 scripts/detect_env.py --fix                # capacités + commande pip manquante
```

## 6. QA mesurable — gates puis autocritique notée

```bash
python3 scripts/gates.py out/<nom> --target hero   # exit 0/1 + gates.json + qa_summary.md
python3 scripts/critique.py policy                 # seuil & budget actifs (source de vérité)
python3 scripts/critique.py brief  --dir out/<nom> --iter 1
python3 scripts/critique.py verdict --dir out/<nom> --iter 1 --note 8.9 \
    --justification "..." --issue "S|...|..." --deliver
python3 scripts/critique.py status --dir out/<nom>
```

**25+ gates automatiques** (`--target hero|ugc|print`) couvrent : budget triangles Roblox (`<= 9 800` hero / `<= 4 000` ugc), PNG pur sans `EXT_texture_webp` côté Roblox, échelle Studs, chaîne LOD décroissante, étanchéité binaire `.stl` rechargée sur disque (`stl_watertight`), `UCX_*` + `BC/ORM/N` DirectX `-Y` côté Unreal, cohérence des normales `G_Unreal == 255 - G_Roblox`, fidélité de silhouette `LOD0↔LOD1↔LOD2`, remplissage et zéro recouvrement UV, syntaxe Luau, réserve d'albédo, modelé lumineux et **cohérence physique ORM (`pbr_coherence` : AO non brûlé + anti-métal parasite)**.

## 7. Références & non-régression

- **Recettes (23)** : `references/recipes.md` (`python3 scripts/generate.py --list --markdown`).
- **Méthode détaillée Hard-Surface & Organique** : `references/cookbook.md` & `scripts/recipes/characters.py`.
- **Matériaux PBR & profils moteurs** : `references/materials.md`, `references/engine_profiles.md`, `references/workflows.md`.
- **CI locale complète** : `pytest -v && python3 scripts/visual_regression.py && python3 evals/run.py`.
