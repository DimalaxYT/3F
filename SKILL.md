---
name: 3d-forge
description: >-
  Use when the user asks for a 3D model, game asset, prop, weapon, vehicle,
  creature bust, printable STL, or an export for Roblox Studio / Unreal Engine 5
  (or Unity/Godot/AR). Roblox Studio (Primary) + Unreal Engine 5 (Secondary)
  Realistic 3D Asset Engine + Hybrid Exact CAD + Organic GPU Sculpture toolkit
  (v5.8): generates plug-and-play
  realistic 3D assets engineered for **Roblox Studio** (`PNG`-embedded `.glb`, exact
  `Studs` scaling `1 Stud = 0.28 m`, budget `< 9 800 tris`/`MeshPart` (plafond moteur
  20 000), `SurfaceAppearance` `1024²` avec AO baked, `Neon_*` auto-split,
  `setup_<Name>.lua`) and **Unreal Engine 5** (`SM_<Name>.glb` + `UCX_*` + `ORM` +
  DirectX `-Y`), with measurable quality gates (`gates.py`) — zero GPU required.
---

# 3d-forge v5.2 — Fast Engine, Measurable QA (**Roblox Studio** primary, **UE5** secondary)

> ## ⚡ CONTRAT DE VITESSE & PROFILS D'EXÉCUTION
> Le chemin par défaut est **`turbo`** : **UNE** commande (`scripts/turbo_forge.py`,
> 9–15 s CPU), **UNE** image lue (`qa_game_sheet.png`), gates mesurées (`gates.json`),
> **max 1 retouche**. Trois profils, définis ici une seule fois :
>
> | profil | recherche web | vues lues | boucle notée | usage |
> |---|---|---|---|---|
> | `turbo` (défaut) | jamais (`research.py fetch` interdit) | `qa_game_sheet.png` seule | `critique.py --fast` (1 retouche max) | toute demande agent standard |
> | `standard` | requêtes web, pas de download | 3 vues + planche | seuil/budget = `critique.py policy` | objet inédit sensible aux proportions |
> | `showcase` | Stage 0 complet (`research.py fetch`) | `--faces all` (14 images) | boucle complète | livraison vitrine / README |
>
> **Seuil & budget d'itérations : source de vérité = `python3 scripts/critique.py policy`**
> (jamais recopiés dans un doc). Ne lance JAMAIS 4–5 reconstructions : le budget est
> borné par le code (`MAX_ITERS`), et `FORCE_DELIVER` avec issues documentées est un
> dénouement normal, pas un échec.

## 1. Choisir le workflow (arbre de décision)

```
demande utilisateur
 ├─ une recette existe (`generate.py --list` / references/recipes.md) ?
 │    ├─ oui, livrable jeu  → turbo_forge.py <recette>            (profil turbo)
 │    └─ oui, livrable print/vitrine → generate.py + --faces all (profil standard/showcase)
 ├─ objet hard-surface inédit (arme, véhicule, coffre, bâtiment) ?
 │    → écrire `custom_<nom>.py` (`def build() -> mk.Builder`) + turbo_forge.py
 ├─ créature / buste / organique ?
 │    → generate_image front/side(/back) EN PARALLÈLE (offer_options=False)
 │      puis turbo_forge.py --front ... --side ...
 ├─ une photo de référence existe ?  → Workflow B (references/workflows.md)
 └─ organique sans photo ?           → Workflow C meshgen (references/workflows.md)
      objet composite multi-pièces ? → Workflow D assemble (references/workflows.md)
```

Règle dure : **jamais `meshgen.py` sur du mécanique** (tubes, roues, lames, pieds de
meubles) — `meshkit.py` (CAO exacte) ou `greebles.py` (kitbash étanche) uniquement.

## 2. Le protocole 1 commande (`turbo_forge.py`)

```bash
# recette du catalogue (~11-14 s, tous livrables + gates)
python3 scripts/turbo_forge.py katana --lod0-tris 8200 -o out/katana

# hard-surface inédit : d'abord write_file custom_<nom>.py (cheatsheet §3), puis :
python3 scripts/turbo_forge.py custom_asset.py --lod0-tris 4200 -o out/custom_asset

# organique : vues GPU générées EN PARALLÈLE dans le même tour, puis :
python3 scripts/turbo_forge.py --front f.png --side s.png --name creature -o out/creature

# options utiles : --target hero|ugc|print (gates) | --split-bed (plateau 256 mm)
#                  --json (manifest complet) | --no-gates | --engine roblox_unreal|...
#                  --dry-run (plan sans exécuter) | --resume (réutilise si hash identique)
#                  --gif (turntable GIF 10 vues)

# live preview navigateur (sandbox Arena / serveur local) :
python3 scripts/serve_preview.py out/<nom> --port 8000   # http://0.0.0.0:8000/preview.html
```

Chaque run écrit dans `out/<nom>/` : `<nom>_game.glb` + LOD1/LOD2, `roblox/`
(`_<name>_roblox.glb` PNG pur + 4 maps + `setup_<name>.lua`), `unreal/`
(`SM_<name>.glb` + `UCX_*` + BC/ORM/N), `<nom>.stl` étanche, `preview.html`,
`qa_game_sheet.png` (10 panneaux : LODs, colliders, **face/profil avec barre
d'échelle cm+Studs**, ColorMap Roblox, normal, ORM, carte QA), **`gates.json`**,
**`qa_summary.md`**, `report.json` (schéma QA unifié) et `game_manifest.json`.

**Tour de contrôle** : lire `qa_game_sheet.png` (et seulement elle) → si les gates
sont OK et la planche propre : livrer (`present_file`). Sinon **une** retouche
chirurgicale, pas deux.

## 3. Cheatsheet API exact (`custom_<name>.py` — zéro lecture de fichier requise)

```python
import sys; sys.path.insert(0, "scripts")
import meshkit as mk, greebles as grb

def build() -> mk.Builder:
    b = mk.Builder("my_asset")  # Mètres: X=right, Y=front(-)/back(+), Z=up(+)
    # Materials (`rubber`/`grip`/`poly` -> strict metallic=0; `emissive="#..."` -> Roblox `Neon_*`):
    #   mk.Material(name, hex_color, metallic=0.0, roughness=0.5, opacity=1.0, emissive=None)
    # Watertight CAD primitives (`scripts/meshkit.py`):
    #   mk.box(w,d,h), mk.chamfer_box(w,d,h,c=None), mk.rounded_box(w,d,h,r=None),
    #   mk.cylinder(r,h,sections=32), mk.tube(r_out,r_in,h), mk.cone(r,h), mk.frustum(r1,r2,h),
    #   mk.sphere(r), mk.capsule(r,h_cyl), mk.torus(R,r), mk.extrude(pts2d,height),
    #   mk.lathe(profile_rz,sections=48), mk.loft(sections,zs=None), mk.tube_sweep(path_xyz,r),
    #   mk.helix_spring(r_coil,r_wire,pitch,turns=6), mk.union([...]), mk.difference(base,[...]),
    #   mk.place(m,x,y,z), mk.rot_x(m,deg), mk.rot_y(m,deg), mk.rot_z(m,deg), mk.scale(m,s), mk.ground(m)
    # Watertight Hard-Surface Greebles (`scripts/greebles.py`):
    #   grb.picatinny_rail(length,width,height,teeth), grb.louver_vent(width,height,slats,depth),
    #   grb.hex_bolt(r,h), grb.bolt_array(points,normals,r,h), grb.ribbed_conduit(path_xyz,r,rings),
    #   grb.corner_armor_cap(size,height), grb.toggle_latch(w,h,d) -> [(m,role)], grb.ergonomic_handle(span,reach,r) -> [(m,role)]
    # Assembly: b.add(mesh, mat, name, group=None); b.def_joint(group, pivot, axis); b.def_socket(name, pos)
    return b
```

Enrichis systématiquement le hard-surface avec `greebles` + hulls `mk.loft`
octogonaux/biseautés : jamais de boîte nue.

## 4. Conventions (à mémoriser)

- **Unités** : mètres (mug = 0,095 ; porte = 2,0). « 30 cm » → `height=0.3`.
- **Up** : Z, base posée à z=0. **Face** : vers **-Y**.
- **Étanchéité** : garantie par construction (CSG manifold, lathe refermé). Un mesh
  non watertight est un bug amont : on corrige la géométrie, on ne livre pas.
- **Vues** : `front` (az 0), `three_quarter` (az 42), `side` (az 90), `top` (el 70), `back` (az 180).

## 5. Quick start hors jeu vidéo (print / web / AR)

```bash
python3 scripts/generate.py --list                 # catalogue (+ --markdown)
python3 scripts/generate.py vase --out ./out       # GLB + STL + 3 PNG + report.json
python3 scripts/generate.py vase --set shape=amphora height=0.35 color="#7a2e1d" \
    --formats glb obj stl usdz --views front three_quarter top --size 1024
python3 scripts/validate.py out/vase/vase.stl      # exit 1 si non print-safe
python3 scripts/detect_env.py --fix                # capacités + commande pip manquante
```

`report.json` est le journal QA de `generate.py`/`meshgen.py` ; `turbo_forge.py`
écrit le même schéma (+ `game_manifest.json`). Les deux alimentent `critique.py`.

## 6. QA mesurable — gates puis autocritique notée

```bash
python3 scripts/gates.py out/<nom> --target hero   # exit 0/1 + gates.json + qa_summary.md
python3 scripts/critique.py policy                 # seuil & budget actifs (source de vérité)
python3 scripts/critique.py brief  --dir out/<nom> --iter 1   # fiche (métriques + photos à lire)
python3 scripts/critique.py verdict --dir out/<nom> --iter 1 --note 8.9 \
    --justification "..." --issue "S|...|..." --deliver
python3 scripts/critique.py status --dir out/<nom>
```

**25 gates** (`--target hero|ugc|print`) — budget : tris/MeshPart ≤ 9 800 (hero) /
4 000 (ugc) et ≤ plafond moteur 20 000 ; contenu : `roblox/*.glb` = PNG pur sans
`EXT_texture_webp`, textures ≤ 1024², Studs ∈ [0.1, 2048], LOD0 > LOD1 > LOD2,
STL watertight + volume > 0, `UCX_*` + BC/ORM/N côté Unreal, planche QA ;
comportement : animations (`Idle_Action` si joints), normales `G_unreal = 255 −
G_roblox`, silhouette LOD0↔LOD2 et LOD0↔LOD1, couverture UV, chevauchement d'îlots,
structure Luau, budget UCX,
cartes PBR non plates, néon émissif, **design de l'albédo**
(saturation / contraste / budget de blancs). Chaque gate a un test « mutant » qui prouve
qu'elle échoue quand on casse le package (`tests/test_gates_mutants.py`).
Anti-complaisance codée : note ≥ seuil avec issues ouvertes = refusé ; note < seuil
sans diagnostic = refusé ; IoU de formatage < 0.5 interdit une note ≥ seuil.

## 7. Catalogue, géométrie custom, matériaux, moteurs

- **Recettes (20)** : table générée depuis le registre → `references/recipes.md`
  (`python3 scripts/generate.py --list --markdown`, vérifié en CI).
- **Objet inédit** : méthode complète (décomposition, profils, CSG, exemple travaillé)
  → `references/cookbook.md`. Étendre le catalogue = nouvelle recette `@register`
  dans `scripts/recipes/` (voir PLAN.md §5).
- **Matériaux PBR** : presets `mk.mat.*` + métaux physiques → `references/materials.md`.
- **Roblox/UE5/Unity/Godot, piliers techniques, formats** → `references/engine_profiles.md`.
- **Workflows B/C/D + Stage 0 + boucle notée détaillée** → `references/workflows.md`.

## 8. Quality gates avant livraison (checklist)

1. `gates.py` sort 0 (`gates.json` tout vert) pour la cible demandée.
2. `qa_game_sheet.png` lue : silhouette face/profil cohérente avec la demande,
   barre d'échelle crédible (un « cup » ne fait pas 2 m), matériaux lisibles.
3. `report.json`/manifest : `watertight: true` ; tris dans le budget de la cible.
4. Boucle notée close (`critique.py status` : DELIVER ou FORCE_DELIVER documenté).
5. Profils `standard`/`showcase` seulement : chaque détail Stage 0 visible sur une photo.

Non-régression (CI + local) : `python3 scripts/visual_regression.py` compare
l'IoU de silhouette des recettes au baseline commité
(`docs/visreg_baseline.json`) — une proportion cassée qui passe tous les tests
unitaires échoue ici. Exemples lourds hors arbre :
`python3 scripts/fetch_examples.py`.

## 9. Neural fallback (optionnel, off par défaut)

Si `detect_env.py` rapporte un GPU ≥ 6 Go : TripoSR / Hunyuan3D / TRELLIS peuvent
compléter le catalogue pour l'organique (`neural/README.md`). Le procédural reste
maître : le neuronal produit la forme, meshkit la fiabilise — jamais l'inverse.

## 10. Troubleshooting

- `manifold3d` manquant → CSG désactivé : `pip install manifold3d` (ou `detect_env.py --fix`).
- Rendus KO mais exports OK → livrer les fichiers, le signaler, re-rendre en `--size 512`.
- `usd-core` manquant → usdz bascule sur le fallback usda (signalé `experimental`).
- Couleurs étranges dans un viewer externe : modèles Z-up ; Blender/three.js importent
  Y-up → pivot -90° X (le `preview.html` le fait déjà).
- `preview.html` trop lourd à partager : il embarque le GLB webp (≈ 1 Mo) ; les photos
  y sont en vignettes JPEG.
