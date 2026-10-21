"""Tests d'intégration v3 : CAO mécanique, GGX+HDRI+SSAO+ShadowMap, AO cuite
dans glTF ORM (`mr.r`), pont GPU datacenter (`gpu_bridge` + `photo_pass`) et
critère `R` (photoréalisme) dans `critique.py`."""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image
import trimesh

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import critique
import cycles_render
import gpu_bridge
import meshkit as mk
import pbr
import photo_pass
import renderer


def test_mechanical_cad_primitives_watertight():
    cbox = mk.chamfer_box(0.12, 0.08, 0.05, c=0.008)
    assert cbox.is_watertight and cbox.volume > 0

    curve = [[0, 0, 0], [0.10, 0.02, 0.08], [0.22, -0.03, 0.05], [0.30, 0.0, 0.14]]
    pipe_solid = mk.tube_sweep(curve, r=0.016, sections=16, smooth_pts=28)
    assert pipe_solid.is_watertight and pipe_solid.volume > 0

    pipe_hollow = mk.tube_sweep([[0, 0, 0], [0, 0, 0.12]], r=0.020, r_inner=0.013,
                                sections=18, smooth_pts=8)
    assert pipe_hollow.is_watertight
    assert 0 < pipe_hollow.volume < mk.tube_sweep([[0, 0, 0], [0, 0, 0.12]], r=0.020,
                                                   sections=18, smooth_pts=8).volume

    spring = mk.helix_spring(r_coil=0.035, r_wire=0.006, pitch=0.022, turns=5.0,
                             sections=10, pts_per_turn=16)
    assert spring.is_watertight and spring.volume > 0

    hose = mk.cable([[0, 0, 0.3], [0.2, 0.05, 0.05]], r=0.005, sag=0.04)
    assert hose.is_watertight and hose.volume > 0


def test_baked_ao_in_gltf_orm_and_directional_overlays():
    # Bloc en U creusé : l'intérieur de la cavité doit avoir une AO plus basse que l'extérieur
    outer = mk.box(0.20, 0.20, 0.20)
    cut = mk.box(0.10, 0.10, 0.16)
    mk.place(cut, 0, 0, 0.05)
    u_shape = mk.difference(outer, [cut])
    ao = pbr.compute_ambient_occlusion(u_shape)
    assert ao.min() < 0.75 and ao.max() > 0.90

    mesh_uv, labels, uv = pbr.unwrap(u_shape, np.zeros(len(u_shape.vertices), dtype=np.int32))
    spec = {
        "texture_size": 256,
        "materials": [{"id": "body", "base": "#e06020", "roughness": 0.35, "metallic": 0.0}],
        "overlays": [
            {"kind": "mud_splash", "amount": 0.7, "height": 0.45},
            {"kind": "contact_wear", "amount": 0.6},
            {"kind": "decal_stripe", "axis": "z", "span": [0.65, 0.75], "color": "#f5f5f5"},
        ],
    }
    alb, mr, nrm, _ = pbr.bake_textures(mesh_uv, labels, uv, spec)
    mr_arr = np.asarray(mr)
    # Canal R = AO cuite non constante (< 255 dans la cavité !)
    assert mr_arr[..., 0].min() < 225
    assert mr_arr[..., 0].max() > 240


def test_ggx_hdri_ssao_shadow_and_gbuffer():
    s1 = trimesh.Scene()
    m_shiny = mk.sphere(0.12, subdivisions=3)
    m_shiny.visual = trimesh.visual.ColorVisuals(m_shiny)
    m_shiny.visual.material = mk.mat.brushed_stainless("#dce2ea", roughness=0.08).to_pbr()
    s1.add_geometry(m_shiny, geom_name="chrome_ball")

    im = renderer.render_view(s1, size=256)
    arr = np.asarray(im)
    # Le dôme HDRI studio crée de vrais reflets lumineux vifs + contraste sombre
    assert arr.max() > 235
    assert arr.std() > 12.0

    sil = renderer.render_silhouette(s1, size=256)
    dep = renderer.render_depth(s1, size=256)
    nrm = renderer.render_normals(s1, size=256)
    assert np.asarray(sil).max() == 255
    assert np.asarray(dep).max() > 200
    assert np.asarray(nrm).shape == (256, 256, 3)
    assert isinstance(cycles_render.cycles_available(), bool)


def test_gpu_bridge_tiles_and_multiview_bake(tmp_path):
    # Génère une tuile matière synthétique haute-fréquence + bake dans un .glb
    tile_p = tmp_path / "tile.png"
    rng = np.random.default_rng(7)
    tile_arr = np.clip(150 + 45 * rng.standard_normal((128, 128, 3)), 0, 255).astype(np.uint8)
    Image.fromarray(tile_arr).save(tile_p)

    box_m = mk.chamfer_box(0.16, 0.12, 0.24, c=0.015)
    glb_in = tmp_path / "raw.glb"
    box_m.export(glb_in)

    spec = {
        "texture_size": 256,
        "regions": [{"name": "all", "z": [0.0, 1.0], "tile": str(tile_p),
                     "scale": 2.0, "metallic": 0.6, "roughness": 0.35, "edge_polish": 0.4}],
    }
    baked, meta = gpu_bridge.bake_ai_tiles_to_mesh(box_m, spec)
    glb_out = tmp_path / "baked_ai.glb"
    baked.export(glb_out)
    assert glb_out.stat().st_size > 20_000
    assert meta["uv_coverage"] > 0.25

    # Prépare les guides caméra + reprojection multi-vues dans l'atlas UV
    gdir = tmp_path / "guides"
    manifest = gpu_bridge.prepare_guides(str(glb_out), str(gdir),
                                         views={"hero": [42.0, 22.0], "back": [222.0, 22.0]},
                                         size=256)
    mv_mesh, mv_meta = gpu_bridge.bake_multiview_to_mesh(
        box_m, manifest,
        {"hero": manifest["views"]["hero"]["studio"],
         "back": manifest["views"]["back"]["studio"]},
        texture_size=256,
    )
    assert mv_meta["projected_coverage"] > 0.70
    mv_glb = tmp_path / "mv.glb"
    mv_mesh.export(mv_glb)
    assert mv_glb.stat().st_size > 15_000

    # Vérifie aussi photo_pass.prepare_photo_pass
    pp = photo_pass.prepare_photo_pass(str(glb_out), str(tmp_path / "pp"), "test mechanical part", size=256)
    assert os.path.isfile(pp["recommended_generate_image_call"]["images"][0])


def test_critique_photorealism_axis_R(tmp_path):
    assert "R" in critique.AXES
    it0 = tmp_path / "iter_0"
    it0.mkdir()
    img_p = it0 / "render.png"
    Image.new("RGB", (128, 128), (180, 180, 180)).save(img_p)
    rep = {
        "prompt": "moto de cross KTM",
        "validation": {"watertight": True, "winding_consistent": True,
                       "triangles": 12000, "budget_tris": 40000,
                       "degenerate_faces": 0, "components": 1, "volume_m3": 0.24},
        "comparison": {"iou_mean": 0.78, "views": {"side": {"iou": 0.80}, "front": {"iou": 0.76}}},
        "renders": [str(img_p)],
    }
    (it0 / "report.json").write_text(json.dumps(rep), encoding="utf-8")

    r_brief = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts/critique.py"),
         "brief", "--dir", str(tmp_path), "--iter", "0"],
        capture_output=True, text=True, check=True,
    )
    assert "critique_brief.md" in r_brief.stdout
    assert "| R | 0-1.5 |" in (it0 / "critique_brief.md").read_text(encoding="utf-8")

    # Un verdict < 9.5 pointant explicitement l'axe R (photoréalisme) est accepté et tracé
    r_v = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts/critique.py"),
         "verdict", "--dir", str(tmp_path), "--iter", "0",
         "--note", "8.6", "--justification", "Manque la passe photo GPU datacenter",
         "--issue", "R|plastique ABS encore trop uniforme sans passe GPU|lancer photo_pass + bake-tiles"],
        capture_output=True, text=True, check=True,
    )
    log = json.loads((tmp_path / "critique_log.json").read_text(encoding="utf-8"))
    assert log["entries"][0]["issues"][0]["axe"] == "R"
