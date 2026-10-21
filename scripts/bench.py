#!/usr/bin/env python3
"""
bench.py — benchmarks MESURÉS de `3d-forge` (source de vérité des tableaux README).

    python3 scripts/bench.py            # régénère docs/bench.json + table README
    python3 scripts/bench.py --check    # recompte et compare tris/octets (CI) :
                                        # exit 1 si le doc a dérivé du code

Les anciens tableaux « avant/après » du README étaient recopiés à la main et
avaient dérivé (katana LOD0 « 2 598 tris » doc vs 8 200 réels). Désormais la
table est injectée entre les marqueurs `<!-- BENCH:START -->` / `<!-- BENCH:END -->`.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

CASES = [
    {"name": "katana", "args": {"target": "katana", "lod0_tris": 8200}},
    {"name": "sci_fi_crate", "args": {"target": "sci_fi_crate", "lod0_tris": 3800}},
]


def run_case(case: dict) -> dict:
    import turbo_forge as tf
    with tempfile.TemporaryDirectory(prefix="bench_") as td:
        t0 = time.perf_counter()
        man = tf.run_turbo(out_dir=td, run_gates=False, **case["args"])
        dur = round(time.perf_counter() - t0, 2)
    lods = man.get("lods", {})
    return {
        "asset": case["name"],
        "high_poly_tris": man.get("high_poly_tris"),
        "lod0_tris": lods.get("LOD0", {}).get("tris"),
        "lod0_bytes": lods.get("LOD0", {}).get("bytes"),
        "lod1_tris": lods.get("LOD1", {}).get("tris"),
        "lod2_tris": lods.get("LOD2", {}).get("tris"),
        "draw_calls_before": man.get("draw_calls_before"),
        "draw_calls_after": man.get("draw_calls_after"),
        "duration_s": dur,  # indicatif : non comparé en --check
    }


def table_md(rows: list[dict]) -> str:
    L = ["| asset | high-poly | LOD0 (poids) | LOD1 | LOD2 | draw calls | turbo CPU (indicatif) |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| `{r['asset']}` | {r['high_poly_tris']:,} tris | "
                 f"**{r['lod0_tris']:,} tris** ({r['lod0_bytes'] / 1024:.0f} Ko) | "
                 f"{r['lod1_tris']:,} tris | {r['lod2_tris']:,} tris | "
                 f"{r['draw_calls_before']} ➔ {r['draw_calls_after']} | {r['duration_s']} s |")
    return "\n".join(L)


def inject_readme(table: str) -> bool:
    rp = ROOT / "README.md"
    txt = rp.read_text(encoding="utf-8")
    start, end = "<!-- BENCH:START -->", "<!-- BENCH:END -->"
    if start not in txt or end not in txt:
        return False
    pre, rest = txt.split(start, 1)
    _, post = rest.split(end, 1)
    rp.write_text(pre + start + "\n" + table + "\n" + end + post, encoding="utf-8")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="compare tris/octets mesurés à docs/bench.json (exit 1 si dérive)")
    args = ap.parse_args(argv)

    rows = [run_case(c) for c in CASES]
    bench_p = ROOT / "docs" / "bench.json"

    if args.check:
        if not bench_p.is_file():
            print("docs/bench.json absent — lance `python3 scripts/bench.py`", file=sys.stderr)
            return 1
        old = {r["asset"]: r for r in json.loads(bench_p.read_text(encoding="utf-8"))["rows"]}
        drift = []
        for r in rows:
            o = old.get(r["asset"])
            if not o:
                drift.append(f"{r['asset']}: absent du bench commité")
                continue
            # tris : strictement déterministes (géométrie générée par le code).
            for k in ("high_poly_tris", "lod0_tris", "lod1_tris", "lod2_tris"):
                if o.get(k) != r[k]:
                    drift.append(f"{r['asset']}.{k}: commité {o.get(k)} != mesuré {r[k]}")
            # octets : la taille du GLB dépend de la version de libwebp (encodage
            # des textures) : tolérance 5 % pour attraper une vraie dérive
            # (ex. bascule webp -> PNG = ×5) sans casser sur un arrondi d'encodeur.
            ob, rb = o.get("lod0_bytes"), r.get("lod0_bytes")
            if ob and rb and abs(ob - rb) / max(ob, rb) > 0.05:
                drift.append(f"{r['asset']}.lod0_bytes: commité {ob} vs mesuré {rb} "
                             f"(> 5 %, encodeur différent ou régression de taille)")
        if drift:
            print("DÉRIVE DOC/CODE :", file=sys.stderr)
            for d in drift:
                print("  -", d, file=sys.stderr)
            print("=> régénère : python3 scripts/bench.py", file=sys.stderr)
            return 1
        print(f"bench à jour ({len(rows)} assets, tris identiques, octets à ±5 %).")
        return 0

    payload = {
        "generated_by": "scripts/bench.py",
        "note": "durées indicatives (machine dépendante) ; tris déterministes (comparés strictement en CI), octets à ±5 % (encodeur webp versionné)",
        "rows": rows,
    }
    bench_p.parent.mkdir(parents=True, exist_ok=True)
    bench_p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    table = table_md(rows)
    ok = inject_readme(table)
    print(f"docs/bench.json écrit ({len(rows)} assets) | table README injectée : {ok}")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
