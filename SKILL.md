---
name: 3d-forge
description: >-
  Roblox Studio (Primary) + Unreal Engine 5 (Secondary) Realistic 3D Asset Engine
  + Hybrid Exact CAD + Organic GPU Sculpture toolkit (v5): generates plug-and-play
  realistic 3D assets specifically engineered for **Roblox Studio** (`< 10,000 tris`
  per `MeshPart`, exact `Studs` scaling `1 Stud = 0.28 m`, `PNG`-embedded `.glb` +
  4 `SurfaceAppearance` `1024²` maps with baked Ambient Occlusion, auto-split `Neon_*`
  emissive parts, and ready-to-paste `setup_<Name>.lua` Command Bar rig/Tool scripts)
  AND **Unreal Engine 5** (`SM_<Name>.glb` with `UCX_*` convex hulls, pure SH De-Lit
  `BaseColor`, packed `ORM`, and DirectX `-Y` Mikk `TANGENT VEC4` normal maps) — zero
  GPU required on the user's machine.
---

# 3d-forge v5.1 Turbo — Ultra Design, Texture & `< 90s` Fast Engine (**Roblox Studio** Primary & **UE5** Secondary)

> ## ⚡ CRITICAL SPEED RULE FOR ALL AI AGENTS (`TARGET: < 90 SECONDS TOTAL`, NEVER EXCEED 3 MINUTES!)
> Previously, AI agents took **30+ minutes** per model by running blocking URL scrapes, chaining 10 separate CLI scripts, rendering 14 views per pass, and looping 5 times (`iter_0..iter_4`) chasing an unreachable `9.5/10`. **FOLLOW THIS FAST 1-COMMAND PROTOCOL EVERY TIME:**
> 1. **ONE SINGLE PYTHON COMMAND (`scripts/turbo_forge.py` — `12 to 20s` CPU end-to-end!)**:
>    - **Catalog recipe (`~12s`)**: `python3 scripts/turbo_forge.py katana --lod0-tris 8200 -o out/katana`
>    - **Brand-new hard-surface / mechanical / weapon asset (`~14s`)**: Write ONE clean Python module `custom_asset.py` exposing `def build() -> mk.Builder:` using `meshkit.py` + `greebles.py`, then run **ONE command**:
>      `python3 scripts/turbo_forge.py custom_asset.py --lod0-tris 4200 -o out/custom_asset`
>    - **Brand-new organic creature / character / bust (`~18s` CPU)**: Generate `front.png` + `side.png` [optional `back.png`] **IN PARALLEL IN ONE SINGLE TURN** via `generate_image(..., offer_options=False)` on uniform neutral background, then run **ONE command**:
>      `python3 scripts/turbo_forge.py --front front.png --side side.png --name creature -o out/creature`
> 2. **ZERO BLOCKING WEB SCRAPING BY DEFAULT**: **DO NOT run `research.py fetch`** (HTTP image scraping timeouts waste 3–5 min) unless the user explicitly gives URLs or asks for web references.
> 3. **INSPECT ONLY `qa_game_sheet.png` (1 IMAGE, NOT 14!) & DELIVER IN 1 PASS (`MAX 1 FIX`)**:
>    - `turbo_forge.py` automatically outputs **ALL deliverables in 1 command (`~12–18s`)**: `<name>_game.glb`, `roblox/<name>_roblox.glb` + `setup_<name>.lua`, `unreal/SM_<name>.glb`, watertight `<name>.stl` (+ `--split-bed` if `> 256×256×256 mm`), interactive `preview.html`, and 4-view studio `qa_game_sheet.png`!
>    - Read **only `qa_game_sheet.png`** (do NOT read `meshkit.py` / `game_ready.py` — exact signatures are right below!). If clean (`>= 8.8/10`), **DELIVER IMMEDIATELY IN 1 PASS (`present_file` on `qa_game_sheet.png` or `preview.html`)**.

### Exact Python API Cheatsheet (`custom_<name>.py` -> zero extra file reads needed!)
```python
import sys; sys.path.insert(0, "scripts")
import meshkit as mk, greebles as grb

def build() -> mk.Builder:
    b = mk.Builder("my_asset")  # Meters: X=right, Y=front(-)/back(+), Z=up(+)
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

> **New in `v5.1` (`Ultra Design, Texture & Turbo Engine`)**:
> - **Hard-Surface Mechanical Kitbash Library (`scripts/greebles.py`)**: Always enrich hard-surface props, crates, vehicles, weapons, and sci-fi doors with 100%-watertight `greebles` (`hex_bolt`, `bolt_array`, `toggle_latch`, `louver_vent`, `picatinny_rail`, `ribbed_conduit`, `ergonomic_handle`, `corner_armor_cap`) + octagonal/tapered `mk.loft` hulls instead of plain boxes!
> - **Datacenter-GPU Z-Buffer Multi-View Texture Paint (`gpu_bridge.render_orthographic_paint_guides` + `--ai-front/--ai-side/--ai-top`)**: Render sub-millimeter orthographic guides (`ortho_meta.json`), paint studio albedo stencils/panels via `generate_image(..., images=[guide])`, and project them cleanly with per-camera Z-buffer occlusion testing across both static hulls AND articulated sub-parts (`lid`, `door`).
> - **8-Archetype Semantic PBR Engine & Dual-`1024²` Roblox Weapon Split**: Strictly enforces `metallic = 0.0` on `MAT_RUBBER_POLY` bumpers/tires, sharpens `MAT_TSUKA_WRAP` braided silk + `MAT_TAMAHAGANE` *hamon* at full `1024²` pixel resolution, straightens UV islands via PCA in `pbr.unwrap()`, and auto-splits elongated weapons (`katana`, `sword`) into `<Name>_Blade` (`1024²`) + `<Name>_Hilt` (`1024²`) inside `<Name>_roblox.glb`!

## Target Engine Priority (ALWAYS FOLLOW BY DEFAULT!)

The primary production target of this skill is **Roblox Studio** (realistic `Future` / `ShadowMap` PBR games), with **Unreal Engine 5** as secondary target (`--engine roblox_unreal` is now the **default** in both `generate.py` and `game_ready.py`!):

1. **ROBLOX STUDIO RULES (`roblox/` — Primary Target, ALWAYS generated by default)**:
   - **NEVER put `EXT_texture_webp` inside `<Name>_roblox.glb`!** Roblox Studio's 3D Importer ignores `EXT_texture_webp` and imports untextured grey meshes. `<Name>_roblox.glb` ALWAYS embeds lossless `image/png` textures so **dragging `<Name>_roblox.glb` into Roblox Studio -> Import 3D automatically builds the `MeshPart` + complete `SurfaceAppearance` (`ColorMap`, `NormalMap`, `MetalnessMap`, `RoughnessMap`) on the very first click!**
   - **Hard `10,000` Triangle Limit per `MeshPart`**: Every `MeshPart` is strictly capped `< 9,800 tris` (`LOD0` target `2,500–4,200 tris` for 60 FPS Mobile + Console + PC with `StreamingEnabled`).
   - **Native `Studs` Scaling (`1 m = 3.5714 Studs`, `1 Stud = 0.28 m`)**: Assets import at **exact R15 / Rthro avatar scale on first drop with zero manual resizing** (e.g., `katana` = `3.50 Studs`, `sci_fi_crate` = `3.31 × 2.13 × 1.82 Studs`).
   - **AO-Baked `ColorMap` (`<= 1024×1024` PNG)**: Because Roblox `SurfaceAppearance` has **NO Ambient Occlusion slot**, multi-scale geometric AO (`lerp(1.0, ao, 0.72)`) is baked directly into `roblox/T_<Name>_ColorMap.png` so crevices, rivets, bevels, and sword guards pop deeply under Roblox `Future` lighting!
   - **Automatic `Neon_*` `MeshPart` Splitting + Ready-to-Paste `setup_<Name>.lua`**: Because `SurfaceAppearance` has **NO Emissive texture slot**, glowing parts (`emissive > 0.05`) are automatically separated into child `Neon_*` `MeshPart`s, and `roblox/setup_<Name>.lua` configures `Enum.Material.Neon`, `Attachment`s, `HingeConstraint + ProximityPrompt [E]` (for hinged lids/doors), and 1-click `ConvertToTool()` (for weapons).
2. **UNREAL ENGINE 5 RULES (`unreal/` — Secondary Target, ALWAYS generated alongside `roblox/` in `roblox_unreal`)**:
   - Metric scale (`1 unit = 1 m` / FBX/glTF UE5 auto-scale), embedded **`UCX_SM_<Name>_00..N`** convex collision hulls, **`SOCKET_*`** Xform nodes, **`T_<Name>_BC.png`** (**pure SH De-Lit BaseColor WITHOUT baked AO** so Lumen / GTAO never double-darkens cavities!), **`T_<Name>_ORM.png`** (`R=AO, G=Roughness, B=Metallic`), and **`T_<Name>_N.png` DirectX `-Y`** normal map in exact Mikk `TANGENT (VEC4)` space!

### The 5 Technical Pillars (`scripts/game_ready.py` & `scripts/delight.py`)
1. **High-Poly -> Low-Poly Mikk Tangent-Space Baker & `LOD0 / LOD1 / LOD2` (`scripts/game_ready.py`)**:
   - Welds split UV seams (`merge_vertices(merge_tex=True, merge_norm=True)`) into a watertight manifold before C++ QEM decimation (`fast_simplification`) so **zero seam cracks or gaps ever open even down to `420–630 tris`**.
   - Projects high-poly surface normals, geometric AO, and curvature onto each LOD in **its own exact Mikk Tangent Space** (`LOD0 @ 1024²`, `LOD1 @ 40% tris / 512²`, `LOD2 @ 15% tris / 256²`) and merges static opaque parts into **1 Draw Call**.
2. **Physical Spherical Harmonics IRLS Albedo De-Lighting (`scripts/delight.py`)**:
   - Fits order-2 Spherical Harmonics (`Y_0..Y_8`) via Huber IRLS in log-luminance space to strip baked directional studio lighting and hot specular highlights from AI-generated textures while preserving intrinsic material colors (`-66%` to `-70%` directional variance reduction; auto-enabled in `gpu_sculpt.py` and `game_ready.py`).
3. **Datacenter-GPU Material Scans + 4-Layer Game Weathering + Normal Stamp Decals**:
   - Eliminates untextured "plastic CAD" surfaces with triplanar Datacenter-GPU material grain (`assets/ai_materials/`), **Curvature Edge Wear** (chipped paint exposing bare steel on sharp corners), **AO Cavity Dirt**, **World-Z Ground Grime**, and procedural **Normal Stamp Decals** (recessed panel seams + steel rivets baked straight into Normal + AO + Metallic with zero polygon cost).
4. **Multi-Engine Native Export Profiles (`--engine unreal | unity | godot | gltf | all`) + Compact `EXT_texture_webp`**:
   - **Explicit `NORMAL (VEC3)` + `TANGENT (VEC4)`** written into every textured glTF primitive + garbage-collected binary repacking (`EXT_texture_webp` reduces `.glb` sizes `×6` to `×42`, e.g., `94 KB` for `katana_LOD2.glb`).
   - **`unreal/`**: `SM_<Name>.glb` (with `UCX_SM_<Name>_00..N` convex hulls) + `T_<Name>_BC.png` + `T_<Name>_ORM.png` (`R=AO, G=Roughness, B=Metallic`) + **`T_<Name>_N.png` DirectX (`-Y` inverted green channel)**.
   - **`unity/`**: prefab `.glb` + `T_<Name>_BaseMap.png` + **`T_<Name>_MaskMap.png` RGBA (`R=Metallic, G=AO, B=Detail, A=Smoothness=1-Roughness`)** + `T_<Name>_NormalGL.png` (`+Y`).
   - **`godot/`**: `<Name>_godot.glb` embedding `-colonly` collision hulls, `SOCKET_*` nodes, and `gltf.animations`.
5. **Convex Physics Colliders (`UCX_*` / `-colonly`), Gameplay `SOCKET_*` Nodes & Standard `gltf.animations`**:
   - `Builder.def_socket("SOCKET_grip", pos=..., rot_deg=...)` + automatic socket inference (`SOCKET_grip`, `SOCKET_tip`, `SOCKET_muzzle`, `SOCKET_origin_ground`, `SOCKET_top`).
   - `Builder.def_joint(...)` automatically exports real glTF 2.0 quaternion keyframe tracks (`animations: [{"name": "Idle_Action", ...}]`) that play out of the box in Unreal, Unity, Godot, Blender, and Three.js.

```bash
# Generate any recipe with full AAA multi-engine game package in one command:
python3 scripts/generate.py sci_fi_crate -f glb stl -q high --game-ready --engine all --lod0-tris 2800 -o out

# Convert ANY high-poly .glb sculpture (from gpu_sculpt.py) or recipe into an optimized game pack:
python3 scripts/game_ready.py examples/dragon_buste/dragon_buste.glb --engine unreal --lod0-tris 4200 -o out/dragon_ue5

# Standalone Albedo De-Lighting for AI multi-view / tile textures:
python3 scripts/delight.py raw_ai_albedo.png -o clean_albedo.png --strength 0.85
```

### Core Hybrid CAD / Sculpture / Print Foundations (`v4` — 20 Watertight Recipes)

In an agent sandbox, Python executes on an isolated CPU container (`cuda_available: false`), while **your native diffusion tool (`generate_image`) executes directly on the model host's Datacenter GPU cluster** (zero local GPU required from the user). `3d-forge v4` combines five pillars across both processors:

1. **Pillar 1 — Organic Multi-View GPU -> 3D Sculpture Pipeline (`scripts/gpu_sculpt.py`)**:
   - Generates calibrated orthographic views (`front`, `side`, `back`) on the Datacenter GPU via `generate_image(..., images=[front])`, reconstructs a smooth multi-branch elliptical 3D Euclidean SDF (`(1 - d_front)² + (1 - d_side)² <= 1` separating horns, ears, jaws, and spikes without box artifacts), applies Taubin smoothing + `manifold3d` boolean fusion onto a chamfered museum plinth (**100% `is_watertight == True` `.stl`**), and bakes full-HD `1024×1024` normal-weighted multi-view PBR + scales normal maps + AO into `.glb` / `.usdz` / `preview.html`.
2. **Pillar 2 — Exact CAD Geometry & 19/19 Watertight Catalog (`meshkit.py` + `scripts/recipes/`)**:
   - Deterministic metric CAD primitives (`box`, `rounded_box`, `chamfer_box`, `cylinder`, `frustum`, `cone`, `sphere`, `torus`, `tube`, `capsule`, `lathe`, `extrude`, `loft`, `sweep`, `tube_sweep`, `helix_spring`, `cable`) + guaranteed-watertight `manifold3d` CSG booleans across all 19 catalog recipes (`car` fastback coupé with 5-spoke wheels & brake rotors, `house` with hollow CSG windows/door & stone steps, `tree` with swept roots/branches, `motocross` with wave rotors & cooling fins, `katana`, `sword`, etc.).
   - **STRICT BAN ON `meshgen.py` FOR MECHANICAL PARTS**: NEVER use voxel/marching-cubes `meshgen.py` on mechanical parts (exhaust headers, tubes, forks, frames, wheels, blades, furniture legs). Use exact `meshkit` primitives for mechanics, and `gpu_sculpt.py` for organic statues/busts/creatures.
3. **Pillar 3 — `×80` Vectorized NumPy UV Rasterizer & PNG Compression (`pbr.py`, `gpu_bridge.py`)**:
   - Bucketed vectorized barycentric UV rasterization (`pbr.rasterize_uv_triangles`, `< 0.35 s` at `1024²`), instant `box_project_uv` triplanar mapping, and lossless `compress_png` keeping full showcase packages lean.
4. **Pillar 4 — Refractive Crystal Glass, Automotive Clearcoat & Sketchfab-Grade `preview.html` v2**:
   - Official glTF 2.0 extensions (`KHR_materials_transmission`, `KHR_materials_ior`, `KHR_materials_clearcoat`) injected into `.glb` via `mk.export_glb_pbr`.
   - Linear-radiance optical crystal shader in `renderer.py` (Fresnel reflection, screen-space refraction offset, Beer-Lambert absorption, Total Internal Reflection edge contours, unattenuated GGX glints) + Clearcoat GGX lobe.
   - Upgraded standalone offline WebGL viewer (`preview.py`) with soft ground contact shadow, 4 live HDRI lighting rigs, and 7 Sketchfab-style technical channels (`PBR`, `Albédo`, `Roughness`, `Metallic`, `Normales`, `AO`, `Filaire`).
5. **Pillar 5 — Articulated `.glb` Joints & Real 3D-Printer Bed Splitter (`Builder.def_joint` + `split_stl.py`)**:
   - Named hierarchical sub-assemblies with exact rotation pivots/axes (`node.extras.joint`) + live browser animation button in `preview.html`.
   - `python3 scripts/split_stl.py model.stl -o print_parts --bed 0.256 0.256 0.256`: slices oversized models cleanly onto Bambu/Prusa build volumes with auto-calibrated chamfered male tenons & `0.20 mm`-clearance female mortises + `exploded_preview.png`.

## Quick start

All scripts live in `scripts/`. Run from anywhere (paths are resolved
relative to the script dir):

```bash
# list the recipe catalog with parameters and defaults
python3 scripts/generate.py --list

# generate with defaults → GLB + STL + 3 PNG views + report.json
python3 scripts/generate.py vase --out ./out

# custom parameters (in meters! real-world scale by default)
python3 scripts/generate.py vase --set shape=amphora height=0.35 color="#7a2e1d" \
    --formats glb obj stl usdz --views front three_quarter top --size 1024

# validate an existing mesh (exit code 1 if not print-safe)
python3 scripts/validate.py out/vase/vase.stl

# environment capabilities (GPU? usd-core? CSG backend?)
python3 scripts/detect_env.py
```

Each generation writes an `out/<recipe>/` folder: model files, `*_front.png`,
`*_three_quarter.png`, `*_top.png`, and a `report.json` (params, triangle
count, watertight status, volumes, file sizes). Read `report.json` — it is
your QA record. It also writes an interactive **`preview.html`** (GLB
embedded, opens in any browser — share it or double-click it; disable with
`--no-preview`).

## Conventions (memorize these)

- **Units**: meters. A mug is 0.095 tall, a door is 2.0. If the user says
  "30 cm vase", that's `height=0.3`.
- **Up axis**: Z. Objects stand on the ground plane (base at z=0).
- **Front**: an object's front faces **-Y** (the default camera looks from
  there).
- **Watertight**: every CSG output and every lathe/extrude solid is
  guaranteed watertight. If `validate.py` ever reports a non-watertight mesh,
  the bug is upstream — fix the geometry, don't ship it.
- **Views**: `front` (az 0), `three_quarter` (az 42), `side` (az 90),
  `top` (el 70), `back` (az 180).

## Workflow for a generation request

0. **Ground the request (Stage 0, see below).** Web research → reference
   images → `reference_sheet.png` + `palette_hints.json`. Recipes pin the
   geometry, but your colors/materials should come from the measured palette,
   not from imagination.
1. **Resolve the request.** Check `--list` against the user's object. If a
   recipe matches (exactly or with parameters), use it — recipes encode good
   proportions and print-safe geometry.
2. **Map adjectives to parameters.** "tall terracotta amphora" →
   `vase --set shape=amphora height=0.4 color="#8b3a2a"`. Colors accept hex.
   Dimensions in meters. When the user gives no size, pick a plausible
   real-world one.
3. **Generate**: `generate.py <recipe> --set ... --formats ... --out ...`.
   Default formats are GLB + STL; add `obj`/`usdz` on request (usdz needs the
   `usd-core` package — `detect_env.py` tells you). For a full delivery add
   `--faces all` (photos of the 6 faces + 8-angle turntable + contact
   sheets, listed in `report.json` → `photos`).
4. **Look at the renders** (Read the PNGs). Check silhouette, proportions,
   materials. If something looks wrong, adjust parameters or drop to the
   custom-geometry path and regenerate. One iteration is normal; shipping a
   broken preview is not.
5. **Rate yourself (Stage 3 — MANDATORY for full deliveries).** Run the
   scored self-critique loop (`critique.py`, see below): note /10, threshold
   9.5 — below it you refine, at or above it you deliver. For Workflow D,
   critique the assembly AND the weakest part (`parts/<id>/`).
6. **Validate** (automatic in generate.py, but run `validate.py` standalone
   for printing workflows) and **deliver**: report the output folder, file
   paths, triangle count, dimensions, watertight status, and the final
   critique note with the residual issues (if any) from `critique_log.json`.

## Stage 0 — Web research & reference sheet (`research.py`, MANDATORY)

Before generating an object you have not already validated, ground yourself in
reality — the deterministic equivalent of a diffusion model's training data.
Three obligations, every time:

1. **Web research.** Use your web search tool on the requested object:
   - one query for the whole object (museum / catalog photos → global shape,
     real proportions),
   - one query per notable detail from the request ("gold pommel close-up",
     "sword fuller") → the details to respect,
   - one query for the surface/material look ("rusty metal texture").
   Keep the exact queries — they are recorded in the deliverable.
2. **Reference images.** Download 3–6 public images: global views + close-ups
   of the details. Dead URLs are skipped, not fatal:
   ```bash
   python3 scripts/research.py fetch --urls URL1 URL2 URL3 --dir refs_raw/
   ```
3. **Reference sheet + palette hints.** Write the details you extracted as
   `--notes` (one per flag) — this becomes the QA contract:
   ```bash
   python3 scripts/research.py build --dir refs_raw/ \
       --title "épée médiévale rouillée avec pommeau en or" \
       --out out/epee/references \
       --queries "medieval arming sword museum photo" "gold pommel close up" \
       --notes "pommeau disque doré" "gouttière centrale sur la lame" \
               "rouille orangée par plaques" "fourreau cuir marron"
   ```
   → `reference_sheet.png` — **the image that represents the details to
   respect** (thumbnails + per-image palettes + your details + query log),
   `palette_hints.json` — dominant colors with metallic/roughness guesses
   (paste these into your spec/recipe palette instead of inventing hexes),
   `references.json` — full analysis for traceability.

Rules:
- Every `--notes` detail must be **visible on the final renders** before you
  deliver — meshgen records them as a checklist in `report.json`.
- No web access in the environment? Say so explicitly and fall back to your
  internal knowledge; do not silently skip the reference step.
- If the user supplied a photo, Workflow B (`img2mesh analyze`) runs on top of
  Stage 0 for measurements.

Troubleshooting downloads:
- `research.py fetch` retries with spaced attempts and a curl fallback; a URL
  that still fails is reported and skipped (never fatal).
- Wikimedia Commons rate-limits `Special:FilePath` (HTTP 429) quickly. Get
  direct thumb URLs through the API instead — different rate bucket:
  `https://commons.wikimedia.org/w/api.php?action=query&titles=File:X.jpg&prop=imageinfo&iiprop=url&iiurlwidth=900&format=json`
  → download the returned `thumburl` (thumb.wikimedia.org). Space requests
  ~15 s apart.

## Workflow B — Image → 3D (`img2mesh.py` + `compare.py`)

When the user provides a reference photo (or asks to match one), measure
before you build. The tooling is deterministic; you supply the judgment.

```bash
# 1. MEASURE — segmentation, contour, width profile W(z), dominant colors
python3 scripts/img2mesh.py analyze photo.png --out out/analyze
#    → analysis.json + silhouette.png + contour.png + profile.png
#    → suggested_mode, material_hint, bbox_aspect, symmetry_dev

# 2a. AUTO-BUILD (revolve / extrude / loft from the measured silhouette)
python3 scripts/img2mesh.py build out/analyze/analysis.json --mode revolve \
    --height 0.35 --material ceramic --color "#8b3a2a" --out out/obj

# 2b. GUIDED-BUILD (preferred for complex objects): write/adjust a recipe
#     using the measured profile, then generate.py as usual

# 3. SCORE — silhouette IoU of your mesh vs the reference photo
python3 scripts/compare.py --mesh out/obj/obj.glb --ref photo.png \
    --axes xz --out out/cmp      # axes: xz=profile, yz=front, xy=top
#    → score.json {iou, iou_zones haut/milieu/bas, ref_aspect, mesh_aspect}
#    → overlay.png: RED = photo only, GREEN = mesh only, YELLOW = match
```

Iteration protocol (this is the whole point):
1. Read `score.json` — global IoU and per-third IoU tell you WHERE it is off.
2. Read `overlay.png` — red blobs = missing mass, green blobs = excess mass.
3. Adjust recipe constants (or `--mode` / `--depth` / `--roundness`) and
   regenerate. Two to three iterations typically take IoU from ~0.55 to 0.75+.
4. IoU ≥ 0.70 with a clean overlay is a good delivery; ~0.85+ is excellent.

Mode guide (`suggested_mode` in analysis.json):
- `revolve` — rotationally symmetric objects (vases, bottles, pawns): exact
  profile W(z) → watertight lathe. Roundtrip IoU ≈ 0.99.
- `extrude` — flat objects (logos, blades, plates): exact contour → prism.
- `loft` — puffy objects: super-ellipse cross-sections driven by W(z)
  (`--depth`, `--roundness`, `--square`; 2 = ellipse, 4 = boxy).

Notes: photos need a clean solid or transparent background (flat studio shots
are ideal). `compare.py` fills holes on both masks — it scores the outer
envelope/proportions, not internal detail. Shadow under the object inflates
the reference mask slightly; ignore small red bands at ground level.

## Workflow C — Multi-view generation (`meshgen.py`, the "Meshy mode")

For organic or composite objects with **no recipe and no photo** (or when you
want generation rather than part-by-part assembly). This is the deterministic
equivalent of the Meshy pipeline — **you are the diffusion model**: instead of
coding primitives, you *imagine* the object as three orthographic views
painted with material letters. The hidden angles are constrained by the other
two views, exactly like multi-view synthesis.

| Meshy step | meshgen v2 equivalent |
|---|---|
| 1. Internal representation | spec JSON: PBR palette (`palette` or `materials`), optional anisotropic `dims`/`grid`, + 3 views (**2D vector shapes** OR ASCII) |
| 2. Multi-view synthesis | continuous 2D vector canvas (`spline`, `poly`, `rect`, `ellipse`, `circle`, `capsule`, `void`/`erase`) or ASCII |
| 3. Volume reconstruction | continuous 2D Euclidean SDF visual hull (`ndimage.zoom(..., mode="nearest")`) with Z-up (`row 0 = +Z`, `z=0` base) |
| 4. Remesh / retopology | marching cubes → Taubin smoothing → quadric decimation to triangle budget → XY centering + exact `z=0` grounding |
| 5. UV unwrap | `pbr.unwrap` (`xatlas` chart packing, shared with `Builder.bake_pbr`) |
| 6. PBR textures | 3-map procedural glTF 2.0 bake (`albedo` + `metallicRoughness` + tangent-space `normal`): `rust`, seamless `wrap` / `diamond` (*tsuka-maki*), `edge_wear`, `wood_grain`, `brushed_metal`, `hamon`, `patina`, `speckle` |
| 7. Consistency check | aligned 3-view silhouette IoU (`> 0.90` even on 7 mm thin blades via anisotropic `dims`/`grid`) + direct UV-PBR renders |

### Vector 2D view format (preferred over ASCII — zero staircase artifacts)

```json
{
  "name": "epee_rouillee",
  "dims": [0.215, 0.044, 0.96],
  "grid": [96, 40, 208],
  "smooth": 5,
  "texture_size": 1024,
  "normal_strength": 2.3,
  "materials": {
    "blade":  {"base": "#9ca2a9", "roughness": 0.26, "metallic": 0.90},
    "fuller": {"base": "#666c74", "roughness": 0.42, "metallic": 0.84},
    "guard":  {"base": "#cc9e42", "roughness": 0.30, "metallic": 0.93},
    "grip":   {"base": "#3b2517", "roughness": 0.76, "metallic": 0.03},
    "pommel": {"base": "#cf9f44", "roughness": 0.28, "metallic": 0.94}
  },
  "overlays": [
    {"type": "brushed_metal", "on": ["blade", "fuller"], "axis": "z", "scale": 165.0, "amount": 0.14},
    {"type": "rust", "on": ["blade", "fuller"], "color": "#8f421d", "coverage": 0.40, "scale": 14.5},
    {"type": "wrap", "on": "grip", "count": 11.0, "ribbon_width": 0.44},
    {"type": "edge_wear", "on": ["blade", "guard", "pommel"], "amount": 0.68, "scale": 18.0}
  ],
  "views": {
    "front": {"size": [224, 512], "shapes": [
      {"op": "spline", "mat": "blade", "center": [[2, 112], [404, 112]],
       "half_width": [[2, 1.5], [44, 17.5], [220, 27.0], [404, 32.0]]},
      {"op": "capsule", "mat": "guard", "a": [12, 405], "b": [212, 405], "r": 10.5},
      {"op": "ellipse", "mat": "pommel", "cx": 112, "cy": 489, "rx": 26.5, "ry": 22.0}
    ]},
    "side": {"size": [96, 512], "shapes": ["..."]},
    "top":  {"size": [224, 96], "shapes": ["..."]}
  }
}
```

Legacy ASCII specs (`size_m` + `res` + `palette` + string arrays) remain 100% supported:

```json
{
  "name": "epee_ascii",
  "prompt": "épée médiévale rouillée avec pommeau en or",
  "size_m": 1.05, "res": 80, "upsample": 2, "smooth": 10,
  "budget_tris": 15000, "symmetry_x": true, "mc_level": 0.47,
  "texture_size": 1024,
  "palette": [
    {"id": "s", "name": "acier", "color": "#a8adb4", "metallic": 0.9,  "roughness": 0.38},
    {"id": "g", "name": "or",    "color": "#d8a93a", "metallic": 1.0,  "roughness": 0.28},
    {"id": "L", "name": "cuir",  "color": "#6b4a32", "metallic": 0.0,  "roughness": 0.72},
    {"id": "r", "name": "rouille","color": "#7d4426","metallic": 0.2,  "roughness": 0.88}
  ],
  "views": {
    "front": ["       s       ", "      sss      ", "..."],
    "side":  ["  s  ", "  s  ", "..."],
    "top":   ["               ", "ggggggggggggggg", "..."]
  },
  "overlays": [
    {"type": "rust", "on": "s", "with": "r", "coverage": 0.42, "band": [0.14, 0.6], "scale": 6.5},
    {"type": "wrap", "on": "L", "count": 8, "twist": 0.32, "darken": 0.5},
    {"type": "edge_wear", "on": ["s", "g"], "amount": 0.5, "scale": 18.0}
  ]
}
```

View drawing rules (this is the craft — think like a multi-view artist):
- `.` or space = empty, `#` = primary material (palette[0]), any palette `id`
  letter = that material. Rows are listed **top to bottom** in world space.
- **Orientation des vues (l'erreur n°1 — la lire deux fois)** :
  - `front` : X×Z — ligne 0 = **sommet** de l'objet, dernière ligne = sol ;
    colonne 0 = côté **gauche** de l'objet vu de face.
  - `side` : Y×Z — même hauteur que front ; colonne 0 = **arrière** de
    l'objet, dernière colonne = **avant** (comme un profil droit : ce qui
    est dessiné à droite de ta vue se retrouve devant). Inverser coûte
    2 itérations.
  - `top` : X×Y — ligne 0 = **arrière**, dernière ligne = avant ;
    colonne 0 = gauche (cohérent avec front).
  - Les vues décrivent l'**enveloppe extérieure** : ne dessine JAMAIS
    l'intérieur creux (coque en anneau) — le visual hull est plein et les
    cavités fermées sont comblées automatiquement (`fill_cavities`, défaut
    on). Un creux doit être OUVERT (vase, bol) pour survivre.
- **`symmetry_x` (défaut `true`)** : l'objet est miroité en X puis uni à
  son reflet. Économie : dessine une moitié, l'autre vient gratuite.
  Piège : tout détail décentré (antenne, pupille unique, emblème latéral)
  est **dupliqué en miroir silencieusement** — `symmetry_x: false` pour
  tout objet non symétrique. meshgen affiche un avertissement quand les
  vues sont visiblement asymétriques.
- The 3 views must be **mutually consistent** (same height in front/side,
  same width in front/top): the hull intersection is the shape where all
  three agree. A feature must appear in the views that see it.
- Thin features (blades, poles) need ≥1 px in every view that sees them;
  2 px is safer — smoothing rounds 1-px fins.
- Material zones: each voxel takes a **majority vote** of the letters that
  cover it in the 3 views. Paint zones in at least 2 views to win reliably.
- `band` in overlays = normalized height [0=bottom, 1=top].

```bash
python3 scripts/meshgen.py specs/epee_rouillee.json --out out/epee \
    --faces all --references out/epee/references
#    → GLB texturé (albedo+roughness+metallic+normal), OBJ, STL, USDZ,
#      *_view_*.png (tes vues d'entrée), rendus, report.json
#    → report.coherence.per_view = IoU face/profil/dessus
#    → --faces all : PHOTOS DE TOUTES LES FACES — 6 face photos
#      (face/dos/gauche/droite/dessus/dessous) + planche *_all_faces.png
#      + turntable 8 angles + planche *_turntable.png
#    → --references : copie la planche des détails à respecter (Stage 0) et
#      enregistre report.references.details_to_respect = ta checklist QA
```

Delivery rule (Meshy parity): a generation is deliverable only with
`--faces all` — inspect the six-face sheet and the turntable exactly like
Meshy's preview gallery, and tick off every detail from
`report.references.details_to_respect` on those photos. Face/dos/gauche must
tell the same story as your three drawn views; if a detail is missing, fix
the spec (views or palette/overlays) and re-run.

Iteration protocol: read `report.validation.iou_views` — a low view means
your drawing disagrees with the hull (or smoothing ate a thin feature).
Raise `res` (80→96) for detail, lower `smooth` (10→6) to protect thin fins,
raise `mc_level` (0.47–0.5) to inflate slightly, `budget_tris` for game
assets. Two to three iterations are normal. The sword reference run:
12 196 tris, watertight, IoU face 0.63 / profil 0.45 / dessus 0.72 in ~39 s.

When to use which workflow: **A (recipes)** parametric families; **B
(img2mesh)** a photo exists; **C (meshgen)** anything else — organic shapes,
props, "Meshy-style" generation; **D (assemble)** composite objects worth
generating part by part (katana, moto multi-organes, lampadaire…). You can
also combine: draw views guided by measurements from `img2mesh analyze`.

## Workflow D — Multi-part assembly (`assemble.py`, the "katana mode")

Composite objects deserve **sub-generations**: decompose the object into
parts, give each part its own spec (its own resolution, palette, overlays,
own scored refinement loop), then place and assemble. This is the
Meshy-style pipeline applied per part — finer detail per region (a small
part spends its voxels on ITS details), and part generation runs **in
parallel** (one meshgen process per part).

Manifest format (Z-up, meters — `at` = position of the part CENTER):

```json
{
  "name": "katana",
  "prompt": "katana forgé, lame courbée, tsuka wrappée",
  "parallel": true,
  "parts": [
    {"id": "tsuka", "spec": "specs/parts/tsuka.json", "at": [0, 0, 0.17]},
    {"id": "tsuba", "spec": "specs/parts/tsuba.json", "at": [0, 0, 0.30],
     "rot_deg": [90, 0, 0]}
  ]
}
```

Each part is generated standing (meshgen convention: base z=0, +Z up), then
centered on its bbox and transformed scale → rot_deg (about its center) →
`at`. Tricks of the trade:
- **Model thin flat parts on edge** (a tsuba is drawn as a vertical disc in
  its own frame, then laid flat with `rot_deg: [90,0,0]`) — an extreme
  aspect ratio drawn flat explodes the voxel grid (OOM).
- **Overlap consecutive parts by 2–3 mm** — exact face-to-face contact makes
  fragile boolean unions; interpenetration is robust.
- Keep view grids mutually consistent per part (front.cols = top.cols,
  front.rows = side.rows, side.cols = top.rows) — same rules as Workflow C.
- Per-part budgets: the sum of part budgets is your total; the per-part
  refinement loop (critique.py on `parts/<id>/`) only regenerates THAT part.

```bash
python3 scripts/assemble.py manifest.json --out out/katana --faces all
#    → <name>.glb (grouped scene, per-part PBR textures), <name>.stl
#      (watertight boolean union, print-ready), OBJ, USDZ, renders,
#      photos of all faces + turntable, preview.html, report.json
#    → report.parts[] = per-part triangles/watertight/IoU (QA checklist)

# ITERATION (the whole point): only one part is wrong?
# edit specs/parts/lame.json, then:
python3 scripts/assemble.py manifest.json --out out/katana --faces all \
    --part lame
#    → only the blade regenerates (others come from cache), assembly reruns

python3 scripts/assemble.py manifest.json --out out/katana --force  # all parts
# --jobs N : parallel processes (default 4, capped by part count)
```

Delivery rule (same as Workflow C): `--faces all` + the scored self-critique
loop (Stage 3) on the ASSEMBLY — plus a glance at each part's own renders in
`parts/<id>/` when its IoU is the weakest. Assembly coherence is measured as
the mean per-part IoU in `report.coherence`.

## Stage 3 — Scored self-critique (`critique.py`, the 9.5 loop, MANDATORY)

You are your own QA. After every generation (recipes or meshgen), before any
delivery, run the scored self-critique loop — the full prompt lives in
`AUTOCRITIQUE.md` and applies verbatim:

> **Rate yourself 1–10. Below 9.5, keep refining (fix the spec, regenerate,
> re-critique). At 9.5 or above, deliver — and only then.**

The deterministic engine structures the loop and protects you from
complacency:

```bash
# 1. BRIEF — regenerate the critique sheet for this iteration
python3 scripts/critique.py brief --dir out/epee --iter 1
#    -> iter_1/critique_brief.md: objective metrics (IoU views, watertight,
#       budget, suggested T score), the PHOTOS you must open (all faces,
#       turntable, control views, reference sheet), the Stage-0 details
#       checklist, the 10-point grading rubric (S=3 V=2 M=2 D=2 T=1)

# 2. VERDICT — after LOOKING at every photo, record your score.
#    Each point lost = one concrete issue (AXE|problem|fix).
python3 scripts/critique.py verdict --dir out/epee --iter 1 \
    --note 7.2 --justification "proportions ok, details manquants" \
    --issue "S|pointe trop fine, mangée par le lissage|res 80->96, smooth 10->7" \
    --issue "D|fuller invisible de profil|peindre le fuller dans side aussi"
#    -> REFINE (note < 9.5: fix the spec, regenerate into iter_2, re-critique)
#       DELIVER (note >= 9.5 with --deliver) — only then ship

# 3. STATUS — history of the loop
python3 scripts/critique.py status --dir out/epee
#    -> notes per iteration, trend, current decision
```

Anti-complacency rules (enforced by the code, not by willpower):
- a note >= 9.5 **with open issues** is REJECTED — fix first or lower the note;
- a note < 9.5 **without any issue** is REJECTED — diagnosis is mandatory;
- IoU mean < 0.5 makes any note >= 9.5 impossible (objective proportions);
- a 10 given without having opened the photos is cheating — the brief lists
  them, `critique_log.json` keeps the trace;
- iteration budget (default 4) exhausted -> **FORCE_DELIVER**: honest final
  note + residual issues documented and announced. Never a fake 9.5.
- **9.5 is a deliberately demanding ceiling, not a target you must reach**:
  the note is mechanically bounded by the technical grade and the IoU, so a
  clean loop ends in FORCE_DELIVER at 8.5-9.2 with documented residuals —
  that is the normal outcome, not a failure. `critique_log.json` keeps
  `best_note` so the final grade is tracked, not decorative.

Rubric (10 points): **S** silhouette & proportions /3 (IoU multi-view +
photos), **V** volume consistency across faces /2, **M** materials & textures
/2 (overlays visible and stable between angles), **D** details-to-respect /2
(Stage 0 checklist, −0.5 per missing detail), **T** technique /1 (watertight,
budget, degenerates — suggested automatically by the code).

Each iteration regenerates into its own folder (`out/epee/iter_1/`,
`iter_2/`, …) with the same spec workflow; the log is central
(`out/epee/critique_log.json`). Two to three iterations are normal; if you
still sit below 9.5 at iteration 3, the issue is usually the drawn views
(redraw them from the reference sheet) rather than pipeline knobs.

## The catalog (18 recipes)

| recipe | highlights | key params |
|---|---|---|
| `chair` | scandinavian/classic styles | style, wood_color, seat_color |
| `table` | rect or pedestal round | style, width, height |
| `stool` | 3 splayed legs + ring | height, radius |
| `bookshelf` | n shelves + back panel | width, height, depth, shelves |
| `lamp` | floor/desk, emissive shade | style, height, shade_color |
| `mug` | hollow (wall thickness) + torus handle | height, radius, handle |
| `vase` | amphora/bulb/cylinder/flask, spline profiles | shape, height, radius |
| `bottle` | glass, spline shoulder, cap | height, radius, color, cap |
| `bowl` / `plate` / `wine_glass` | lathe with real wall thickness | radius, height, color |
| `chess_pawn` | spline lathe | height, color |
| `sword` | blade+fuller, guard, grip, pommel | length, blade_color, guard_color |
| `rocket` | fins, porthole, emissive-free but crisp | height, radius, fins, accent_color |
| `house` | gable roof, door, glazed windows, chimney | width, depth, wall/roof colors |
| `tree` | pine (stacked tiers) or oak (blob canopy) | kind, height |
| `car` | extruded side profile, CSG wheel arches | length, width, color |
| `motocross` | dirt bike: knobby wheels, raked fork, expansion chamber, seat, shrouds, fenders, chain, disc brakes | length, body_color, plate_color, seat_color |

Every recipe documents its parameters via `--list`. Parameters are coerced
(`float`, `int`, `bool`, `choice`, `color`) and unknown keys are rejected with
the valid list — read that error message, it saves a cycle.

## When no recipe fits: custom geometry

You are expected to build new objects yourself — that is the point of the
skill. Read `references/cookbook.md` for the full method (decomposition,
profile design, CSG patterns, worked example) and the meshkit API cheatsheet.
Short version:

```python
import sys; sys.path.insert(0, "<skill>/scripts")
import meshkit as mk
from recipes import catalog, get as get_recipe

b = mk.Builder("my_object")
b.add(mk.box(0.4, 0.4, 0.05), mk.mat.wood("#b08850"), name="seat", at=(0, 0, 0.44))
b.add(mk.frustum(0.024, 0.016, 0.44), mk.mat.wood("#b08850"), name="leg", at=(0.17, 0.17, 0))
# ... assemble parts, then reuse the same export path as generate.py
```

You can also *extend the catalog*: write a new `@register(...)` recipe in
`scripts/recipes/` following the existing ones — that is the contribution
model (see PLAN.md).

## Materials (PBR)

`mk.mat.*` presets: `wood`, `plastic`, `ceramic`, `glass`, `fabric`,
`rubber`, `paint`, `metal`, `emissive`, plus named metals `gold`, `brass`,
`copper`, `bronze`, `steel`, `silver`, `aluminum`, `chrome` (physically-based
RGB + roughness). Presets accept overrides: `mk.mat.wood("#5b3a1e", 0.5)`.
Details and guidance: `references/materials.md`.

## Formats

- **GLB** — default. Web/Three.js/Unity/Godot, PBR materials embedded. Z-up, meters.
- **STL** — binary, built from the boolean union of all parts → single
  watertight solid, slicer-ready. Check `report.json` → `is_printable`.
- **OBJ+MTL** — hand-written exporter, one material per PBR preset
  (Kd/Ks/Ns/d derived from baseColor/metallic/roughness/opacity).
- **USDZ** — native package via `usd-core` (Pixar): real crate + UsdPreviewSurface
  materials, AR Quick Look compatible, Z-up declared. Fallback to a plain
  zipped `.usda` if usd-core is missing (flagged experimental).

## Quality gates (before you deliver)

1. `report.json`: `watertight: true`, `is_printable: true` (for print jobs).
2. Triangle count reasonable: < ~50k for web assets (lower `--quality` to
   0.5 if needed), < ~200k for print.
3. You have *seen* at least the three-quarter render and it matches the
   request (shape, proportions, colors).
4. Dimensions are human-scale sensible (a "cup" is not 2 meters).
5. Stage 0 done: `reference_sheet.png` exists and EVERY detail listed in
   `--notes` (→ `report.references.details_to_respect`) is visible on the
   all-faces photos (`--faces all`). A detail you cannot show is a detail
   you did not build — fix the spec/recipe and re-run.
6. Multi-view consistency: face / dos / gauche photos tell the same story
   (same object, same materials, no texture sliding between angles).
7. **Scored self-critique closed**: `critique.py status` shows a final note
   ≥ 9.5 with `DELIVER` (or `FORCE_DELIVER` with documented residual issues
   at the iteration budget). Delivering below threshold without the forced
   decision is a broken delivery.

## Neural fallback (optional, usually off)

If `detect_env.py` reports a CUDA GPU with ≥6 GB VRAM, image-to-3D models
(TripoSR, Hunyuan3D, TRELLIS) can complement the catalog for organic sculpts.
They are *not* installed by default and this skill works fully without them.
Setup: `neural/README.md`.

## Troubleshooting

- `manifold3d` missing → CSG disabled: `pip install manifold3d`.
- Renders fail but exports succeed → generation is still valid; report it,
  deliver files, and re-run renders at `--size 512` if time-constrained.
- `usd-core` missing → usdz falls back to experimental usda zip.
- Odd colors in another viewer → remember models are Z-up; most viewers
  (Blender, three.js) import GLB as Y-up: rotate -90° on X if needed.
