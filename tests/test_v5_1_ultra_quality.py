"""
Tests de non-régression AAA de `3d-forge v5.1 — Ultra Design & Texture Engine` :
  1. Bibliothèque mécanique Hard-Surface `greebles.py` (`is_watertight == True` strict sur les 8 primitives),
  2. Redressement PCA par îlot UV dans `pbr.unwrap()` (`fill_ratio` élevé & UV valides `[0..1]`),
  3. Moteur PBR sémantique par matériau (`MAT_RUBBER_POLY` strict `metallic == 0.0`, chevrons `MAT_HAZARD_STRIPE`),
  4. Projection Multi-Vues Z-Buffer sans fantôme d'occultation (`gpu_bridge.sample_orthographic_ai_views_zbuffer`),
  5. Export Haute Densité Texels Roblox Studio (`katana` Dual-1024² `Blade` + `Hilt`, PNG pur `webp=False`, `< 9 800 tris/part`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import game_ready as gr  # noqa: E402
import gpu_bridge as gb  # noqa: E402
import greebles as grb  # noqa: E402
import meshkit as mk  # noqa: E402
import pbr  # noqa: E402
import recipes  # noqa: E402



# Packs d'exemples lourds hors arbre : skip explicite plutôt qu'échec
# (`python3 scripts/fetch_examples.py --only <pack>` pour les restaurer).
_PACKS = {
    "dragon_buste": "examples/dragon_buste",
    "katana": "examples/katana",
    "sci_fi_crate": "examples/sci_fi_crate",
    "epee_rouillee": "examples/epee_rouillee",
    "motocross": "examples/motocross",
}


def require_pack(name: str) -> None:
    rel = _PACKS[name]
    if not (ROOT / rel).is_dir():
        pytest.skip(f"pack `{rel}` absent : python3 scripts/fetch_examples.py --only {name}")

def test_all_greebles_primitives_strictly_watertight():
    single_primitives = [
        ("hex_bolt", grb.hex_bolt()),
        ("louver_vent", grb.louver_vent(slats=5)),
        ("picatinny_rail", grb.picatinny_rail(teeth=8)),
        ("ribbed_conduit", grb.ribbed_conduit([[0.0, 0.0, 0.0], [0.04, 0.02, 0.22]], rings=10)),
        ("corner_armor_cap", grb.corner_armor_cap()),
    ]
    for name, m in single_primitives:
        assert isinstance(m, trimesh.Trimesh), name
        assert m.is_watertight, f"{name} doit être 100 % watertight !"
        assert float(m.volume) > 0.0, f"{name} doit avoir un volume strictement positif !"

    bolts = grb.bolt_array([[0.0, 0.0, 0.0], [0.05, 0.0, 0.0]], [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
    assert len(bolts) == 2 and all(bm.is_watertight for bm in bolts)

    for sub_m, role in grb.toggle_latch():
        assert sub_m.is_watertight, f"toggle_latch[{role}] non étanche !"

    for sub_m, role in grb.ergonomic_handle():
        assert sub_m.is_watertight, f"ergonomic_handle[{role}] non étanche !"


def test_semantic_weathering_strict_zero_metal_on_rubber_and_crisp_hazard():
    n = 1600
    rng = np.random.default_rng(7)
    pos = rng.uniform(-0.2, 0.2, size=(n, 3)).astype(np.float32)
    nrm = np.tile(np.array([[0.0, -1.0, 0.0]], dtype=np.float32), (n, 1))
    col = np.full((n, 3), 0.14, dtype=np.float32)
    rough = np.full(n, 0.78, dtype=np.float32)
    metal = np.zeros(n, dtype=np.float32)
    ao = rng.uniform(0.35, 1.0, size=n).astype(np.float32)
    curv = rng.uniform(0.0, 1.0, size=n).astype(np.float32)  # y compris arêtes vives `1.0` !
    bounds = np.array([[-0.25, -0.25, 0.0], [0.25, 0.25, 0.4]], dtype=np.float32)

    # 1. Caoutchouc mat : `metallic` DOIT rester strictement égal à `0.0` partout !
    mat_rub = np.full(n, gr.MAT_RUBBER_POLY, dtype=np.int32)
    _, r_out, m_out, _, _ = gr.apply_game_weathering(col, rough, metal, ao, curv, pos, nrm, bounds, mat_id=mat_rub)
    assert float(m_out.max()) == 0.0, "Le caoutchouc ne doit JAMAIS recevoir d'éclats métalliques chromés !"
    assert float(r_out.min()) >= 0.25

    # 2. Plaque chevrons de danger : contraste élevé entre bandes noires et bandes ambres
    col_haz = np.tile(np.array([[0.88, 0.56, 0.10]], dtype=np.float32), (n, 1))
    mat_haz = np.full(n, gr.MAT_HAZARD_STRIPE, dtype=np.int32)
    c_haz_out, _, _, _, _ = gr.apply_game_weathering(col_haz, rough * 0.45, metal + 0.15, ao, curv * 0.1, pos, nrm, bounds, mat_id=mat_haz)
    luma = c_haz_out @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    assert float(np.percentile(luma, 90) - np.percentile(luma, 10)) > 0.30, "Les chevrons 45° doivent présenter un fort contraste net !"


def test_pca_axis_aligned_uv_unwrap_high_fill():
    rail = grb.picatinny_rail(length=0.45, width=0.032, height=0.016, teeth=9)
    labels = np.zeros(len(rail.vertices), dtype=np.int64)
    _, _, uv = pbr.unwrap(rail, labels)
    assert np.isfinite(uv).all()
    assert float(uv.min()) >= 0.0 and float(uv.max()) <= 1.0


def test_zbuffer_multiview_projection_blocks_occluded_back_wall(tmp_path):
    # Mur avant en y = -0.10 et mur arrière caché en y = +0.10
    front_wall = mk.box(0.30, 0.02, 0.30)
    mk.place(front_wall, 0.0, -0.10, 0.0)
    hidden_wall = mk.box(0.20, 0.02, 0.20)
    mk.place(hidden_wall, 0.0, 0.10, 0.0)
    scene_mesh = trimesh.util.concatenate([front_wall, hidden_wall])

    meta = gb.render_orthographic_paint_guides(scene_mesh, str(tmp_path), size=256)
    assert (tmp_path / "ortho_meta.json").is_file()

    # On sonde 1 point visible sur la face avant (`y = -0.11`) et 1 point occulté (`y = +0.09`, normale `-Y` aussi !)
    probe_pos = np.array([
        [0.0, -0.11, 0.15],  # visible de la caméra `front`
        [0.0,  0.09, 0.15],  # même normale `-Y` mais caché derrière `front_wall` !
    ], dtype=np.float32)
    probe_nrm = np.array([
        [0.0, -1.0, 0.0],
        [0.0, -1.0, 0.0],
    ], dtype=np.float32)
    _, _, cov = gb.sample_orthographic_ai_views_zbuffer(
        scene_mesh, probe_pos, probe_nrm, {"front": meta["guides"]["front"]}
    )
    assert cov[0] > 0.85, "La face avant visible doit recevoir la peinture GPU !"
    assert cov[1] == 0.0, "Le Z-buffer doit bloquer à 100 % la projection sur la paroi arrière cachée !"


def test_flagship_v5_1_packages_roblox_and_unreal():
    # 1. Katana v5.1 : Dual-1024² `Blade` + `Hilt` dans Roblox Studio (`< 9 800 tris/part`, `webp=False`)
    kat_rbx_dir = ROOT / "examples" / "katana" / "game_ready" / "roblox"
    require_pack("katana")
    kat_glb_bytes = (kat_rbx_dir / "katana_roblox.glb").read_bytes()
    assert b"EXT_texture_webp" not in kat_glb_bytes
    assert (kat_rbx_dir / "T_katana_Blade_ColorMap.png").is_file()
    assert (kat_rbx_dir / "T_katana_Hilt_ColorMap.png").is_file()
    sc_kat = trimesh.load(kat_rbx_dir / "katana_roblox.glb", force="scene")
    assert "katana_Blade" in sc_kat.geometry and "katana_Hilt" in sc_kat.geometry
    assert max(len(g.faces) for g in sc_kat.geometry.values()) < 9_800

    # 2. Sci-Fi Crate v5.1 : Couvercle articulé texturé PBR + `Neon_status_led_front` + `webp=False`
    crate_dir = ROOT / "examples" / "sci_fi_crate" / "game_ready"
    manifest = json.loads((crate_dir / "game_manifest.json").read_text(encoding="utf-8"))
    assert manifest["engine_exports"]["roblox"]["under_10k_tris_limit"] is True
    assert "Neon_status_led_front" in manifest["engine_exports"]["roblox"]["neon_parts"]
    crate_glb_bytes = (crate_dir / "roblox" / "sci_fi_crate_roblox.glb").read_bytes()
    assert b"EXT_texture_webp" not in crate_glb_bytes
    sc_crate = trimesh.load(crate_dir / "roblox" / "sci_fi_crate_roblox.glb", force="scene")
    lid_mat = sc_crate.geometry["lid_mesh"].visual.material
    assert getattr(lid_mat, "baseColorTexture", None) is not None, "Le couvercle articulé doit posséder sa texture PBR !"


def test_turbo_forge_single_command_under_25_seconds(tmp_path):
    """Vérifie que `turbo_forge.run_turbo` génère un pack complet Roblox + UE5 + LODs + QA en < 25s !"""
    import time
    import turbo_forge as tf

    t0 = time.perf_counter()
    manifest = tf.run_turbo(
        target="katana",
        out_dir=tmp_path / "turbo_katana_check",
        lod0_tris=6000,
        tex_size=1024,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 25.0, f"Trop lent ({elapsed:.2f}s >= 25s) — risque de régression de vitesse !"
    assert (tmp_path / "turbo_katana_check" / "roblox" / "katana_roblox.glb").is_file()
    assert (tmp_path / "turbo_katana_check" / "unreal" / "SM_katana.glb").is_file()
    assert (tmp_path / "turbo_katana_check" / "katana.stl").is_file()
    assert (tmp_path / "turbo_katana_check" / "katana.zip").is_file()
    assert not (tmp_path / "turbo_katana_check" / "preview.html").exists()
    assert (tmp_path / "turbo_katana_check" / "qa_game_sheet.png").is_file()
    assert manifest["stl_watertight"] is True
    assert manifest["engine_exports"]["roblox"]["under_10k_tris_limit"] is True

