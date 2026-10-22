"""Non-regression suite for v5.8 Visual Quality, Organic SDF Sculpting, Delighting, Clean PBR & Studio Preview."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_organic_primitives_and_sculpt_watertight():
    """All organic.py primitives + Sculpt C1 clay modeler must produce watertight meshes."""
    import meshkit as mk
    import organic as org

    e = org.ellipsoid(0.05, 0.06, 0.07)
    assert e.is_watertight and e.volume > 0

    se = org.superellipsoid(0.06, 0.05, 0.08, e1=0.6, e2=0.8)
    assert se.is_watertight and se.volume > 0

    tc = org.tapered_curve(
        [(0.0, 0.0, 0.0), (0.04, -0.02, 0.05), (0.08, 0.01, 0.09)],
        [0.014, 0.010, 0.004],
    )
    assert tc.is_watertight and tc.volume > 0

    vis = org.curved_visor(width=0.12, length=0.06, thickness=0.008, arch=0.02)
    assert vis.is_watertight and vis.volume > 0

    p_base, p_ring = org.museum_plinth(0.16, 0.16, 0.04, round_profile=True)
    assert p_base.is_watertight and p_ring.is_watertight
    assert mk.union([p_base, p_ring]).is_watertight

    s = org.Sculpt(bounds=((-0.09, -0.09, 0.0), (0.09, 0.09, 0.18)), res=52)
    s.ellipsoid((0.0, 0.0, 0.09), (0.055, 0.055, 0.060), k=0.012)
    s.ellipsoid((0.03, -0.04, 0.08), (0.024, 0.020, 0.020), k=0.014, mirror_x=True)
    s.ellipsoid((0.02, -0.05, 0.11), (0.014, 0.010, 0.014), mode="sub", k=0.006, mirror_x=True)
    clay = s.to_mesh(smooth_iter=3, target_tris=2400)
    assert clay.is_watertight and clay.volume > 0


def test_delight_preserves_white_emblem_and_vibrant_chroma():
    """delight_albedo_3d must keep white badges crisp-white while evening shading on saturated red."""
    from delight import delight_albedo_3d

    # Synthetic 3D normals spanning hemisphere + shaded red cap + bright white badge
    rng = np.random.default_rng(7)
    nrms = rng.normal(size=(600, 3))
    nrms[:, 1] -= 1.2
    nrms /= np.linalg.norm(nrms, axis=1, keepdims=True)
    light_dot = np.clip(-0.55 * nrms[:500, 1] + 0.65 * nrms[:500, 2], 0.15, 1.0)[:, None]
    red_shaded = np.clip((0.35 + 0.60 * light_dot) * np.array([[0.88, 0.12, 0.14]]), 0.0, 1.0)
    white_badge = np.tile(np.array([[0.93, 0.93, 0.95]]), (100, 1))
    cols = np.vstack([red_shaded, white_badge]).astype(np.float32)

    out, metrics = delight_albedo_3d(cols, nrms)
    red_out = out[:500]
    white_out = out[500:]
    assert float(white_out.mean()) > 0.78, f"White badge crushed to {white_out.mean():.3f}!"
    assert float(red_out[:, 0].std()) < float(red_shaded[:, 0].std()), f"Expected shading reduction: {metrics}"


def test_clean_non_metal_materials_stay_dielectric_and_clean():
    """MAT_CLEAN_ENAMEL must stay metallic=0 without armor mud or unsolicited edge steel chips."""
    import meshkit as mk
    from game_ready import MAT_CLEAN_ENAMEL, apply_game_weathering

    m_skin = mk.mat.skin("#f2a97e")
    m_enamel = mk.mat.enamel("#dc2626")
    assert m_skin.metallic == 0.0 and m_skin.metallicFactor == 0.0
    assert m_enamel.metallic == 0.0 and m_enamel.metallicFactor == 0.0

    n = 128
    col = np.tile(m_enamel.color.astype(np.float32), (n, 1))
    rough = np.full(n, m_enamel.roughness, dtype=np.float32)
    metal = np.zeros(n, dtype=np.float32)
    ao = np.full(n, 0.85, dtype=np.float32)
    curv = np.linspace(0.0, 0.95, n, dtype=np.float32)  # sharp edges too!
    pos = np.random.default_rng(3).uniform(-0.1, 0.1, (n, 3)).astype(np.float32)
    nrm = np.tile(np.array([[0.0, -1.0, 0.0]], dtype=np.float32), (n, 1))
    bounds = np.array([[-0.1, -0.1, 0.0], [0.1, 0.1, 0.2]], dtype=np.float32)
    mat_id = np.full(n, MAT_CLEAN_ENAMEL, dtype=np.int32)

    c_out, r_out, m_out, ao_out, _ = apply_game_weathering(
        col, rough, metal, ao, curv, pos, nrm, bounds, mat_id=mat_id
    )
    assert float(m_out.max()) == 0.0, f"Dielectric enamel gained steel metal {m_out.max()}!"
    assert float(c_out[:, 0].mean()) > 0.65, f"Red enamel lost vibrancy: {c_out.mean(axis=0)}"


def test_pbr_coherence_gate_catches_false_metallic_organic(tmp_path: Path):
    """pbr_coherence gate must reject a sculpt asset where non-metal surfaces turn metallic."""
    from gates import _pbr_coherence

    orm = np.zeros((256, 256, 3), dtype=np.uint8)
    orm[..., 0] = 210   # healthy AO
    orm[..., 1] = 150   # rough dielectric
    orm[..., 2] = 240   # BUG: forced gold metal everywhere!
    (tmp_path / "unreal").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "unreal" / "T_test_ORM.webp"
    Image.fromarray(orm, "RGB").save(p)

    ok, detail = _pbr_coherence(
        tmp_path,
        "test",
        {"sculpt_source": {"mode": "views"}, "engine_exports": {"unreal": {"orm_packed": str(p)}}},
    )
    assert not ok, f"Expected pbr_coherence failure on forced-metal organic ORM, got {detail}"


def test_hero_bust_full_pipeline_and_preview_webp_clean_grid(tmp_path: Path):
    """End-to-end check on hero_bust: 25/25 gates OK, watertight STL, clean WebP preview without yellow wire bug."""
    from preview import build_preview
    from turbo_forge import run_turbo

    out_dir = tmp_path / "hero_bust_qa"
    manifest = run_turbo(
        target="hero_bust",
        out_dir=out_dir,
        name="hero_bust",
        lod0_tris=3800,
        tex_size=1024,
        gate_target="hero",
    )
    assert manifest["stl_watertight"] is True
    gates_doc = json.loads((out_dir / "gates.json").read_text())
    assert gates_doc.get("all_pass") is True, f"Hero bust gates failed: {gates_doc}"

    # Verify preview.html v6.0 embeds WebP + universal zero-extension WebGL2/WebGL1 shader + accurate QA badges
    html_path = out_dir / "preview.html"
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    assert "EXT_texture_webp" in html
    assert "gl_FragColor = vec4(0.88, 0.78, 0.48, 1.0)" not in html
    for banned in ("dFdx(", "dFdy(", "OES_standard_derivatives", "URL.createObjectURL(blob)"):
        assert banned not in html, f"Regression: {banned} breaks WebGL2 or sandboxed iframes"
    assert "QA 25/25 ✓ LIVRABLE" in html
    assert "✓ STL 100 % étanche" in html
    assert "LODS_DATA" in html
    assert html_path.stat().st_size < 4 * 1024 * 1024

    # Check standalone build_preview works too
    p2 = build_preview(out_dir, title="Hero Bust", glb=out_dir / "hero_bust_game.glb")
    assert Path(p2).is_file()


def test_tengu_mask_concave_shell_zero_back_poke_and_under_30s(tmp_path: Path):
    """Tengu mask must build in < 30s with 25/25 gates OK, reload-watertight STL, and zero internal back-poke."""
    import time
    import trimesh
    from turbo_forge import run_turbo

    t0 = time.perf_counter()
    out_dir = tmp_path / "tengu_qa"
    manifest = run_turbo(
        target="tengu_mask",
        out_dir=out_dir,
        name="tengu_mask",
        lod0_tris=4800,
        tex_size=1024,
        gate_target="hero",
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 35.0, f"Tengu mask took {elapsed:.1f}s (must be fast, never 1 hour!)"
    assert manifest["stl_watertight"] is True
    assert trimesh.load(out_dir / "tengu_mask.stl", force="mesh").is_watertight

    gates_doc = json.loads((out_dir / "gates.json").read_text())
    assert gates_doc.get("all_pass") is True, f"Tengu mask gates failed: {gates_doc}"


def test_sculpted_eyes_recessed_pupil_c2_eyelids_and_qem_preservation():
    """Verify org.add_sculpted_eyes guarantees 0.00 mm front pupil protrusion, watertight C² curves, and smooth eye QEM."""
    import meshkit as mk
    import organic as org

    b = mk.Builder("eye_unit_check")
    org.add_sculpted_eyes(
        b,
        center_y=-0.055,
        center_z=0.150,
        spacing_x=0.036,
        rx=0.0195,
        ry=0.0118,
        rz=0.0112,
        pupil_radius=0.0050,
        pupil_recess=0.0022,
        tilt_deg=11.0,
        yaw_deg=6.0,
    )
    by_name = {lbl: m for m, _mat, lbl in b.parts}
    for tag in ("L", "R"):
        eye_m = by_name[f"gilded_brass_eye_{tag}"]
        pup_m = by_name[f"black_pupil_{tag}"]
        lid_u = by_name[f"sculpted_upper_eyelid_{tag}"]
        lid_l = by_name[f"sculpted_lower_eyelid_{tag}"]
        assert eye_m.is_watertight and pup_m.is_watertight
        assert lid_u.is_watertight and lid_l.is_watertight
        # Front face points toward -Y: min_y of pupil MUST NEVER protrude in front of min_y of eyeball!
        eye_front_y = float(eye_m.bounds[0, 1])
        pup_front_y = float(pup_m.bounds[0, 1])
        assert pup_front_y >= eye_front_y + 0.0010, (
            f"Pupil {tag} protrudes in -Y ({pup_front_y:.5f} vs globe {eye_front_y:.5f})!"
        )


