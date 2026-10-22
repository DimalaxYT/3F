# Workflows détaillés de `3d-forge` (référence progressive)

> Ce fichier complète `SKILL.md` (qui reste le routeur). Profils d'exécution :
> - **`turbo`** (défaut agent) : zéro fetch web, 1 commande `turbo_forge.py`, lecture unique
>   de `qa_game_sheet.png`, max 1 retouche (`critique.py --fast`).
> - **`standard`** : Stage 0 léger (requêtes web, pas de download), 3 vues de contrôle,
>   boucle notée seuil/budget = `critique.py policy`.
> - **`showcase`** : Stage 0 complet (`research.py fetch`), `--faces all`, boucle notée
>   complète — réservé aux livraisons vitrine.

## Stage 0 — Web research & reference sheet (`research.py` — profils `standard`/`showcase`)

En profils `standard`/`showcase` : avant de générer un objet non validé,
ancre-toi dans le réel — the deterministic equivalent of a diffusion model's training data.
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

## Stage 3 — Scored self-critique (`critique.py` — seuil & budget : `critique.py policy`)

> **GARDE-FOU DE VITESSE OBLIGATOIRE (`MAX_ITERS = 1`, `< 90 s` total)** :
> Ne lance **JAMAIS** de boucle de 4, 8 ou 10 reconstructions ni `--faces all` en mode agent standard (`turbo`).
> Source de vérité unique du seuil et du budget = **`python3 scripts/critique.py policy`** (`THRESHOLD = 8.8`, `MAX_ITERS = 1`) :
> - **Passe 0 (`turbo_forge.py`, `~15 s`)** -> ouvre `qa_game_sheet.png` : si tout est net et `gates.json` = `all_pass: true`, **livre immédiatement**.
> - **Si un défaut précis est visible** -> corrige tout en **UNE SEULE passe groupée (`iter_1`)**, relance `turbo_forge.py` une fois et **livre immédiatement (`FORCE_DELIVER`)**.

```bash
# 0. Consulter la politique active (seuil 8.8, budget MAX 1 retouche)
python3 scripts/critique.py policy

# 1. BRIEF — génère la fiche de critique de l'itération
python3 scripts/critique.py brief --dir out/epee --iter 1

# 2. VERDICT — enregistre la note et livre dès passe 0 ou après 1 retouche max
python3 scripts/critique.py verdict --dir out/epee --iter 1 \
    --note 9.0 --justification "volumes sculptés propres, 25/25 gates vertes" --deliver

# 3. STATUS — historique
python3 scripts/critique.py status --dir out/epee
```


