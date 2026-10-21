"""Déterminisme du pipeline : mêmes entrées ⇒ mêmes sorties (tris ET octets).

C'est la condition pour que `bench.py --check` (fraîcheur doc/code en CI) et
`turbo_forge --resume` (hash des entrées) veuillent dire quelque chose : si un
run variait d'un exécution à l'autre, toute comparaison serait du bruit.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import game_ready as gr  # noqa: E402
from generate import get_recipe  # noqa: E402


def _build(out: Path) -> dict:
    builder = get_recipe("vase")["builder"]()
    return gr.export_game_package(
        builder, out_dir=out, name="vase", engine="roblox_unreal",
        lod0_tris=900, tex_size=128,
    )


def test_pipeline_deterministe(tmp_path):
    m1 = _build(tmp_path / "a")
    m2 = _build(tmp_path / "b")

    for lod in ("LOD0", "LOD1", "LOD2"):
        assert m1["lods"][lod]["tris"] == m2["lods"][lod]["tris"], f"{lod} non déterministe"
        assert m1["lods"][lod]["bytes"] == m2["lods"][lod]["bytes"], \
            f"{lod} : octets différents entre deux runs identiques"

    assert m1["draw_calls_after"] == m2["draw_calls_after"]
    assert m1["high_poly_tris"] == m2["high_poly_tris"]

    # export Roblox : mêmes dimensions Studs au centième, même poids
    r1 = m1["engine_exports"]["roblox"]
    r2 = m2["engine_exports"]["roblox"]
    assert [round(v, 3) for v in r1["size_studs_xyz"]] == [round(v, 3) for v in r2["size_studs_xyz"]]
    b1 = Path(r1["studio_ready_glb_png"]).stat().st_size
    b2 = Path(r2["studio_ready_glb_png"]).stat().st_size
    assert b1 == b2, f"GLB Roblox non déterministe ({b1} vs {b2} octets)"
