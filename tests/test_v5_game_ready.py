"""Suite de tests automatisés de `3d-forge v5 — Game-Ready Edition`.

Vérifie de bout en bout toutes les briques AAA temps réel :
  1. De-Lighting physique `delight.py` (Harmoniques Sphériques `Y_0..Y_8` IRLS 3D + 2D)
  2. Espace Tangent Mikk `compute_mikk_tangents` (`VEC4`, orthogonalité `N ⊥ T`, `w ∈ {-1, +1}`)
  3. Export `.glb` v5 : attribut `TANGENT`, compression `EXT_texture_webp` sans bloc mort,
     nœuds `SOCKET_*`, et pistes d'animation standard `gltf.animations` (`Idle_Action`)
  4. Recette n°20 `sci_fi_crate` (`100 % watertight`, charnière `lid`, sockets gameplay)
  5. Pipeline complet `game_ready.py` (`High-Poly -> LOD0/LOD1/LOD2`, DirectX `-Y` Unreal,
     `MaskMap` RGBA Unity HDRP, `-colonly` Godot 4, colliders convexes `UCX_*`)
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import delight as dl
import game_ready as gr
from generate import get_recipe
import meshkit as mk
import pbr


def _parse_glb_json(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    magic, version, _ = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67 and version == 2
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    assert j_type == 0x4E4F534A
    gltf = json.loads(raw[20 : 20 + j_len].decode("utf-8"))
    b_off = 20 + j_len
    b_len, _ = struct.unpack_from("<II", raw, b_off)
    return gltf, raw[b_off + 8 : b_off + 8 + b_len]


def test_delight_3d_removes_baked_directional_shadow_preserving_hue():
    """Une sphère bicolore éclairée par un soleil latéral fort retrouve un albédo uniforme."""
    sph = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    nrm = np.asarray(sph.vertex_normals, dtype=np.float32)
    # Matériau intrinsèque : hémisphère X>0 rouge brique, X<=0 bleu acier
    intrinsic = np.where(
        sph.vertices[:, 0:1] > 0.0,
        np.array([[0.72, 0.22, 0.18]], dtype=np.float32),
        np.array([[0.20, 0.36, 0.68]], dtype=np.float32),
    )
    sun = np.array([0.35, -0.45, 0.82], dtype=np.float32)
    sun /= np.linalg.norm(sun)
    shading = 0.28 + 0.95 * np.clip(nrm @ sun, 0.0, 1.0)[:, None]
    baked_rgb = np.clip(intrinsic * shading, 0.02, 1.0)

    clean_rgb, stats = dl.delight_albedo_3d(baked_rgb, nrm, strength=0.88)
    assert stats["sh_variance_reduction"] > 0.45
    assert clean_rgb.shape == baked_rgb.shape
    # Les deux teintes intrinsèques restent parfaitement distinctes !
    red_side = clean_rgb[sph.vertices[:, 0] > 0.25].mean(axis=0)
    blue_side = clean_rgb[sph.vertices[:, 0] < -0.25].mean(axis=0)
    assert red_side[0] > red_side[2] * 1.8
    assert blue_side[2] > blue_side[0] * 1.8


def test_delight_2d_image_pipeline():
    x = np.linspace(0.0, 1.0, 128, dtype=np.float32)[None, :]
    y = np.linspace(0.0, 1.0, 128, dtype=np.float32)[:, None]
    checker = (((x * 8).astype(int) + (y * 8).astype(int)) % 2) * 0.25 + 0.45
    grad_shadow = 0.35 + 0.85 * x
    img = np.clip(np.dstack([checker * grad_shadow] * 3) * 255.0, 0, 255).astype(np.uint8)
    pil_in = Image.fromarray(img, mode="RGB")
    pil_out, meta = dl.delight_image_2d(pil_in, strength=0.85)
    assert pil_out.size == (128, 128)
    assert meta["sh_variance_reduction"] > 0.20


def test_mikk_tangents_orthonormal_and_handed():
    box = mk.chamfer_box(0.5, 0.4, 0.3, c=0.03)
    uv_m, _, uv = pbr.unwrap(box, np.zeros(len(box.vertices), dtype=np.int64))
    tang = mk.compute_mikk_tangents(uv_m, uv)
    assert tang.shape == (len(uv_m.vertices), 4)
    assert tang.dtype == np.float32
    t_norms = np.linalg.norm(tang[:, :3], axis=1)
    assert np.allclose(t_norms, 1.0, atol=1e-3)
    dots = np.abs(np.sum(tang[:, :3] * uv_m.vertex_normals, axis=1))
    assert float(dots.max()) < 1e-3
    assert set(np.unique(tang[:, 3])).issubset({-1.0, 1.0})


def test_sci_fi_crate_recipe_watertight_joints_and_sockets():
    rec = get_recipe("sci_fi_crate")
    assert rec is not None
    mk.set_quality(1.0)
    b = get_recipe("sci_fi_crate")["builder"]()
    solid = b.union_solid()
    assert solid.is_watertight, "sci_fi_crate doit être 100 % watertight !"
    sc = b.scene()
    assert "lid" in sc.metadata.get("joints", {})
    assert "SOCKET_lid_latch" in sc.metadata.get("sockets", {})
    assert "SOCKET_top_mount" in sc.metadata.get("sockets", {})


def test_game_ready_end_to_end_multi_engine_package(tmp_path: Path):
    out_dir = tmp_path / "katana_pack"
    manifest = gr.export_game_package(
        "katana",
        out_dir=out_dir,
        engine="all",
        lod0_tris=1800,
        tex_size=512,
        webp=True,
    )
    # 1. Hiérarchie stricte des LODs et Draw-Call Merging
    t0 = manifest["lods"]["LOD0"]["tris"]
    t1 = manifest["lods"]["LOD1"]["tris"]
    t2 = manifest["lods"]["LOD2"]["tris"]
    assert t0 > t1 > t2 > 50
    assert manifest["draw_calls_after"] == 1
    assert manifest["draw_calls_before"] >= 6

    # 2. Inspection binaire du `.glb` LOD0 : `TANGENT VEC4` + `EXT_texture_webp` + `SOCKET_*`
    glb0 = Path(manifest["lods"]["LOD0"]["path"])
    gltf, bin_chunk = _parse_glb_json(glb0)
    assert "EXT_texture_webp" in gltf.get("extensionsUsed", [])
    assert gltf["buffers"][0]["byteLength"] == len(bin_chunk)
    assert all(im.get("mimeType") == "image/webp" for im in gltf.get("images", []))

    prim0 = gltf["meshes"][0]["primitives"][0]
    assert "TANGENT" in prim0["attributes"]
    t_acc = gltf["accessors"][prim0["attributes"]["TANGENT"]]
    assert t_acc["type"] == "VEC4" and t_acc["componentType"] == 5126

    node_names = {n.get("name", "") for n in gltf.get("nodes", [])}
    assert "SOCKET_grip" in node_names
    assert "SOCKET_tip" in node_names

    # 3. Vérification pixel par pixel : DirectX (-Y Unreal) vs OpenGL (+Y Unity) + MaskMap HDRP
    n_dx = np.asarray(Image.open(manifest["engine_exports"]["unreal"]["normal_directx_neg_y"]), dtype=np.int32)
    n_gl = np.asarray(Image.open(manifest["engine_exports"]["unity"]["normal_opengl_pos_y"]), dtype=np.int32)
    assert np.all(np.abs((n_dx[..., 1] + n_gl[..., 1]) - 255) <= 1), "Le canal G DirectX doit être exactement `255 - G_OpenGL` !"

    orm = np.asarray(Image.open(manifest["engine_exports"]["unreal"]["orm_packed"]), dtype=np.int32)
    mask = np.asarray(Image.open(manifest["engine_exports"]["unity"]["hdrp_mask_map_rgba"]), dtype=np.int32)
    assert mask.shape[2] == 4
    # MaskMap Unity HDRP : R = Metallic (`ORM.B`), G = AO (`ORM.R`), A = Smoothness (`255 - ORM.G`)
    assert np.all(np.abs(mask[..., 0] - orm[..., 2]) <= 1)
    assert np.all(np.abs(mask[..., 1] - orm[..., 0]) <= 1)
    assert np.all(np.abs((mask[..., 3] + orm[..., 1]) - 255) <= 1)

    # 4. Colliders physiques `UCX_*` (Unreal) et `-colonly` (Godot 4) + animation `gltf.animations` sur `sci_fi_crate`
    ue_gltf, _ = _parse_glb_json(Path(manifest["engine_exports"]["unreal"]["static_mesh_with_ucx"]))
    gd_gltf, _ = _parse_glb_json(Path(manifest["engine_exports"]["godot"]["scene_with_colonly"]))
    assert any(n.get("name", "").startswith("UCX_SM_") for n in ue_gltf.get("nodes", []))
    assert any(n.get("name", "").endswith("-colonly") for n in gd_gltf.get("nodes", []))

    # Vérifie aussi la piste d'animation standard `Idle_Action` sur `sci_fi_crate`
    crate_gltf, _ = _parse_glb_json(ROOT / "examples" / "sci_fi_crate" / "game_ready" / "sci_fi_crate_game.glb")
    assert len(crate_gltf.get("animations", [])) >= 1
    assert crate_gltf["animations"][0]["name"] == "Idle_Action"
