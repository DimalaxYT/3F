#!/usr/bin/env python3
"""preview.py — preview HTML autoportante d'une génération 3d-forge.

Produit un unique `preview.html` dans le dossier de sortie :
viewer 3D interactif (model-viewer via CDN) avec le GLB embarqué en base64
+ bandeau des photos de la génération + statistiques du report.json.
Double-clic dans n'importe quel navigateur, zéro serveur, zéro installation.

Le GLB source (Z-up) est tourné -90° X à l'embarquement (convention Y-up du
web) — le fichier original n'est jamais modifié.

Usage :
    python3 scripts/preview.py --dir out/epee
    python3 scripts/preview.py --dir out/epee --title "épée médiévale rouillée"
    python3 scripts/preview.py --dir out/katana --glb out/katana/katana.glb
"""
from __future__ import annotations

import argparse
import base64
import glob
import io
import json
import os
import sys

PHOTO_PREFS = [  # (motif, légende) par ordre d'utilité
    ("*_trois_quarts.png", "vue 3/4"),
    ("*_three_quarter.png", "vue 3/4"),
    ("*_all_faces.png", "les 6 faces"),
    ("*_turntable.png", "turntable"),
    ("*_references.png", "références (Stage 0)"),
    ("*_front.png", "face"),
    ("*_face.png", "face"),
]
MAX_PHOTOS = 3


def _b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _yup_glb_b64(glb_path: str) -> str:
    """Charge le GLB, tourne Z-up -> Y-up (-90° X) et ré-exporte en base64."""
    import numpy as np
    import trimesh

    scene = trimesh.load(glb_path, force="scene")
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2.0, [1, 0, 0])
    scene.apply_transform(rot)
    buf = io.BytesIO()
    scene.export(buf, file_type="glb")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def find_glb(outdir: str) -> str | None:
    glbs = sorted(glob.glob(os.path.join(outdir, "*.glb")))
    return glbs[0] if glbs else None


def find_photos(outdir: str) -> list[tuple[str, str]]:
    """Photos les plus parlantes du dossier (max MAX_PHOTOS, sans doublon)."""
    seen, photos = set(), []
    for pattern, label in PHOTO_PREFS:
        for p in sorted(glob.glob(os.path.join(outdir, pattern))):
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                photos.append((ap, label))
    return photos[:MAX_PHOTOS]


def _stats_html(report: dict | None) -> str:
    if not report:
        return ""
    chips = []
    v = report.get("validation") or report.get("stats") or {}
    tri = v.get("triangles") or v.get("triangle_count")
    if tri:
        chips.append(f"{tri:,} triangles".replace(",", " "))
    wt = v.get("watertight")
    if wt is not None:
        chips.append("étanche ✓" if wt else "non étanche ⚠")
    coh = (report.get("coherence") or {}).get("mean")
    if coh:
        chips.append(f"IoU {coh}")
    parts = (report.get("stats") or {}).get("parts")
    if parts and parts > 1:
        chips.append(f"{parts} parties assemblées")
    dur = report.get("duration_s")
    if dur:
        chips.append(f"{dur}s")
    if not chips:
        return ""
    return "<div class='chips'>" + "".join(
        f"<span>{c}</span>" for c in chips) + "</div>"


def build_preview(outdir: str, title: str | None = None, glb: str | None = None,
                  report: dict | None = None, out_name: str = "preview.html",
                  quiet: bool = False) -> str | None:
    """Écrit <outdir>/preview.html et retourne son chemin (None si échec)."""
    outdir = os.path.abspath(outdir)
    glb = glb or find_glb(outdir)
    if not glb or not os.path.isfile(glb):
        if not quiet:
            print("[preview] aucun GLB trouvé, preview sautée", file=sys.stderr)
        return None
    if report is None:
        rp = os.path.join(outdir, "report.json")
        if os.path.isfile(rp):
            try:
                with open(rp) as fh:
                    report = json.load(fh)
            except Exception:
                report = None
    title = title or (os.path.basename((report or {}).get("output_dir", outdir)))
    photos = find_photos(outdir)

    photo_html = ""
    if photos:
        cells = "".join(
            f"<figure><img src='data:image/png;base64,{_b64(p)}' alt='{lab}' "
            f"loading='lazy'><figcaption>{lab}</figcaption></figure>"
            for p, lab in photos)
        photo_html = f"<section id='shots'><h2>Photos de la génération</h2>{cells}</section>"

    mv_src = f"data:model/gltf-binary;base64,{_yup_glb_b64(glb)}"
    html = _TEMPLATE.format(title=title, mv_src=mv_src,
                            stats=_stats_html(report), photos=photo_html)
    out_path = os.path.join(outdir, out_name)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path


_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — 3d-forge preview</title>
<script type="module" src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #101014; color: #e8e6e3; font: 15px/1.5 system-ui, sans-serif; }}
  header {{ padding: 20px 24px 8px; display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
  h1 {{ font-size: 20px; font-weight: 650; }}
  .badge {{ font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
           color: #b9a26a; border: 1px solid #3a352a; border-radius: 999px; padding: 2px 10px; }}
  model-viewer {{ width: 100%; height: min(72vh, 760px); background:
      radial-gradient(1200px 500px at 50% 0%, #23232b, #101014); }}
  .tools {{ display: flex; gap: 10px; padding: 10px 24px 0; align-items: center; }}
  button {{ background: #1d1d24; color: #e8e6e3; border: 1px solid #34343e;
           border-radius: 8px; padding: 7px 14px; cursor: pointer; font-size: 13px; }}
  button:hover {{ background: #26262f; }}
  .chips {{ display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 24px 0; }}
  .chips span {{ font-size: 12px; color: #b9b7b2; background: #1a1a20;
                border: 1px solid #2c2c34; border-radius: 999px; padding: 3px 10px; }}
  #shots {{ padding: 18px 24px 30px; }}
  #shots h2 {{ font-size: 14px; font-weight: 600; color: #b9b7b2; margin-bottom: 10px;
              text-transform: uppercase; letter-spacing: .1em; }}
  #shots figure {{ display: inline-block; margin: 0 10px 10px 0; vertical-align: top; }}
  #shots img {{ max-height: 230px; border-radius: 10px; border: 1px solid #2c2c34; display: block; }}
  #shots figcaption {{ font-size: 11px; color: #8d8b86; margin-top: 5px; }}
  .fallback {{ margin: 0 24px; padding: 10px 14px; border: 1px dashed #4a4436;
              border-radius: 8px; color: #c9b98a; font-size: 13px; display: none; }}
</style>
</head>
<body>
<header><h1>{title}</h1><span class="badge">3d-forge</span></header>

<div class="fallback" id="fb">Viewer 3D indisponible (connexion internet requise pour
le composant). Les photos ci-dessous fonctionnent hors ligne.</div>

<model-viewer id="mv" src="{mv_src}" camera-controls auto-rotate
  rotation-per-second="18deg" shadow-intensity="1" exposure="1"
  environment-image="neutral" interaction-prompt="auto" alt="modèle 3D"></model-viewer>

<div class="tools">
  <button id="rot">⏸ rotation</button>
  <button id="cam">🎥 vue 3/4</button>
</div>

{stats}
{photos}

<script type="module">
  const mv = document.getElementById('mv');
  setTimeout(() => {{
    if (!mv.loaded && customElements.get('model-viewer') === undefined)
      document.getElementById('fb').style.display = 'block';
  }}, 4000);
  document.getElementById('rot').onclick = (e) => {{
    mv.autoRotate = !mv.autoRotate;
    e.target.textContent = mv.autoRotate ? '⏸ rotation' : '▶ rotation';
  }};
  document.getElementById('cam').onclick = () => {{
    mv.cameraOrbit = '42deg 68deg auto'; mv.autoRotate = false;
  }};
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Preview HTML autoportante")
    ap.add_argument("--dir", required=True, help="dossier de sortie de la génération")
    ap.add_argument("--title", default=None)
    ap.add_argument("--glb", default=None, help="GLB spécifique (défaut : 1er trouvé)")
    args = ap.parse_args()
    p = build_preview(args.dir, title=args.title, glb=args.glb)
    if p:
        print(f"preview → {p}")


if __name__ == "__main__":
    main()
