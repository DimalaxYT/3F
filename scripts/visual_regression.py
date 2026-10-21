#!/usr/bin/env python3
"""
visual_regression.py — CI VISUELLE de `3d-forge` (régression non couverte par pytest).

    python3 scripts/visual_regression.py --write-baseline   # fige les IoU actuelles
    python3 scripts/visual_regression.py                    # compare au baseline
    python3 scripts/visual_regression.py --recipes vase --min-iou 0.8   # seuil absolu

Régénère chaque recette tête haute, rend la vue `front` et mesure l'IoU de
silhouette (`compare.py`, axes `xz` = vue de face) contre la PNG de référence
commitée sous `examples/`. Comme l'IoU absolue dépend de l'objet (0.61 sur une
chaise ajourée, 0.83 sur un vase plein) et du biais photo/ortho, la gate
compare au **baseline mesuré** (`docs/visreg_baseline.json`) avec une tolérance
`--tol` : une modif de proportions qui ne casse aucun test unitaire fait chuter
l'IoU sous le baseline et échoue ici. C'est la promesse Phase 3 du PLAN.md.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "visreg_baseline.json"

REFS = {
    "vase": "examples/vase/vase_front.png",
    "chair": "examples/chaise_scandinave/chair_front.png",
    "rocket": "examples/rocket/rocket_front.png",
}


def score_recipe(recipe: str, ref: str, tmp: Path, size: int) -> float:
    out = tmp / f"{recipe}_gen"
    subprocess.run(
        [sys.executable, "scripts/generate.py", recipe, "--formats", "glb",
         "--out", str(out), "--size", str(size), "--no-preview", "--quiet"],
        cwd=ROOT, check=True, capture_output=True)
    mesh = out / recipe / f"{recipe}.glb"
    cmp_dir = tmp / f"{recipe}_cmp"
    subprocess.run(
        [sys.executable, "scripts/compare.py", "--mesh", str(mesh),
         "--ref", str(ROOT / ref), "--axes", "xz", "--out", str(cmp_dir)],
        cwd=ROOT, check=True, capture_output=True)
    score = json.loads((cmp_dir / "score.json").read_text(encoding="utf-8"))
    return float(score.get("iou", 0.0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recipes", nargs="*", default=sorted(REFS), choices=sorted(REFS))
    ap.add_argument("--write-baseline", action="store_true",
                    help="mesure et fige les IoU dans docs/visreg_baseline.json")
    ap.add_argument("--tol", type=float, default=0.03,
                    help="tolérance sous le baseline avant RÉGRESSION")
    ap.add_argument("--min-iou", type=float, default=None,
                    help="seuil absolu (outrepasse le baseline)")
    ap.add_argument("--size", type=int, default=256)
    args = ap.parse_args(argv)

    base = {}
    if BASELINE.is_file():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))

    measured: dict[str, float] = {}
    failures = []
    with tempfile.TemporaryDirectory(prefix="visreg_") as td:
        tmp = Path(td)
        for recipe in args.recipes:
            ref = REFS[recipe]
            if not (ROOT / ref).is_file():
                print(f"[SKIP] {recipe} : référence {ref} absente "
                      f"(python3 scripts/fetch_examples.py)")
                continue
            iou = score_recipe(recipe, ref, tmp, args.size)
            measured[recipe] = round(iou, 4)
            if args.write_baseline:
                print(f"  [base] {recipe:8s} IoU face {iou:.3f} vs {ref}")
                continue
            if args.min_iou is not None:
                ok, ref_txt = iou >= args.min_iou, f">= {args.min_iou}"
            elif recipe in base:
                ok, ref_txt = iou >= base[recipe] - args.tol, \
                    f">= baseline {base[recipe]} - {args.tol}"
            else:
                print(f"  [SKIP] {recipe} : pas de baseline (--write-baseline d'abord)")
                continue
            mark = "OK  " if ok else "FAIL"
            print(f"  [{mark}] {recipe:8s} IoU face {iou:.3f} ({ref_txt}) vs {ref}")
            if not ok:
                failures.append(recipe)

    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(measured, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"=> baseline écrit : {BASELINE}")
        return 0
    if failures:
        print(f"=> RÉGRESSION VISUELLE : {', '.join(failures)}", file=sys.stderr)
        return 1
    print("=> aucune régression visuelle détectée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
