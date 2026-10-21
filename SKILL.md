---
name: 3d-forge
description: >-
  Procedural 3D generation toolkit: turns any object description into clean,
  watertight meshes with PBR materials, exported to GLB/GLTF, OBJ+MTL, STL and
  USDZ, plus multi-angle PNG renders — no external API, no GPU, no neural
  network required. The agent reasons (decompose the object, choose proportions
  and materials), the toolkit executes geometry deterministically. Use this
  skill whenever the user asks for 3D models, meshes, 3D assets, game props,
  printable STL files, 3D product visuals, turntable renders, text-to-3D,
  image-to-3D, photo-to-3D, "make me a 3D X", "model this photo", "match this
  picture", "model a chair/vase/rocket/motocross", AR-ready models, or any
  mention of GLB/OBJ/STL/USDZ export — even casually or in French. Multi-part
  composite objects (katana, lamps, vehicles) get part-by-part parallel
  generation via assemble.py; every full delivery also ships an interactive
  self-contained preview.html (GLB embedded, opens in any browser), photos
  of all 6 faces + a turntable (Meshy-style preview gallery) and starts with
  a mandatory web-reference stage (research.py) that produces a
  details-to-respect sheet and measured palette hints.
---

# 3d-forge — procedural 3D generation (no API, no GPU)

## The core idea

There is no neural network here and there doesn't need to be one. **You are the
generator.** A text-to-3D model would guess a blobby approximation of "a
chair"; you can *reason* about what makes a chair a chair — four legs, a seat
at 45 cm, a reclined backrest — and express it exactly. This skill gives you a
deterministic geometry factory (`meshkit`) so your reasoning becomes a clean,
watertight, printable mesh in seconds.

Division of labor:
- **You (the agent)**: parse the request → pick or compose geometry → choose
  real-world dimensions and PBR materials → run the CLI → check the renders →
  iterate if the preview looks off → deliver.
- **meshkit**: primitives, CSG booleans (manifold3d, guaranteed watertight),
  lathe/extrude, PBR materials, multi-format export.
- **renderer**: software rasterizer (numpy) producing studio-lit PNGs from any
  angle — your feedback loop. Never ship an object you haven't looked at.

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

| Meshy step | meshgen equivalent |
|---|---|
| 1. Internal representation | spec JSON: palette PBR + 3 ASCII views |
| 2. Multi-view synthesis | you draw front/side/top consistently |
| 3. Volume reconstruction | visual hull (intersection of extrusions) |
| 4. Remesh / retopology | marching cubes → Taubin smoothing → quadric decimation to triangle budget (retry at larger budgets before keeping the raw mesh) |
| 5. UV unwrap | xatlas (automatic seams + atlas packing) |
| 6. PBR textures | procedural bake reprojected from the 3 views: albedo + metallicRoughness + normal map, overlays (rust / wrap / edge wear) |
| 7. Consistency check | silhouette IoU of the final mesh re-projected against your 3 views + watertight + budget |

Spec format (`specs/epee_rouillee.json` is the reference example):

```json
{
  "name": "epee_rouillee",
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
    "front": ["       s       ", "      sss      ", "..."],   // X×Z, ligne 0 = sommet
    "side":  ["  s  ", "  s  ", "..."],                        // Y×Z
    "top":   ["               ", "ggggggggggggggg", "..."]     // X×Y, ligne 0 = arrière
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
