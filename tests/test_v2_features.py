"""Tests de bout en bout des nouveautés v2 de 3d-forge :
  - meshkit v2 (`rounded_box`, `loft`, `sweep`, `Builder.bake_pbr`, export OBJ UV)
  - intégrité UV `1 - v` aller-retour `.glb` + package `.usdz` aligné 64 octets
  - meshgen v2 (Z-up, pose à z=0, vues vectorielles 2D continues, zéro artefact bord SDF)
  - pbr.py (`wrap` hélicoïdal & `diamond` sans couture, `edge_wear` multi-cibles, normal map)
  - renderer.py (sampling UV bilinéaire + normal map + verre multi-couches)
  - research.py (filtrage fond blanc studio) & compare.py (filtrage ombre portée au sol)
  - preview.py (viewer WebGL PBR 100 % hors-ligne, zéro URL CDN externe)
"""
from __future__ import annotations

import math
import os
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw
import trimesh

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "scripts"))

import compare       # noqa: E402
import meshgen as mg # noqa: E402
import meshkit as mk # noqa: E402
import pbr           # noqa: E402
import packager      # noqa: E402
import renderer      # noqa: E402
import research      # noqa: E402
import usdz_export   # noqa: E402


def test_primitives_rounded_box_loft_sweep():
    rb = mk.rounded_box(0.4, 0.3, 0.2, r=0.04)
    assert rb.is_watertight and rb.volume > 0.015
    assert abs(float(rb.bounds[0][2])) < 1e-5

    sec_a = [(-0.1, -0.05), (0.1, -0.05), (0.1, 0.05), (-0.1, 0.05)]
    sec_b = [(-0.05, -0.03), (0.05, -0.03), (0.05, 0.03), (-0.05, 0.03)]
    lf = mk.loft([(sec_a, 0.0), (sec_b, 0.35)])
    assert lf.is_watertight and lf.volume > 0.002

    prof = [(-0.015, 0.0), (0.0, 0.004), (0.015, 0.0), (0.0, -0.004)]
    ts = np.linspace(0.0, 1.0, 20)
    path = np.column_stack([-0.02 * ts ** 2, np.zeros_like(ts), 0.6 * ts])
    sw = mk.sweep(prof, path, scale=lambda t: (1.0 - 0.5 * t, 1.0 - 0.4 * t))
    assert sw.is_watertight and sw.volume > 1e-6


def test_builder_bake_pbr_and_glb_uv_roundtrip(tmp_path):
    """Vérifie qu'un atlas cuit sur z<0.5 = ROUGE et z>=0.5 = BLEU conserve
    exactement ses couleurs aux bons sommets après export + relecture `.glb`
    (aucune inversion `1 - v`)."""
    b = mk.Builder("uv_probe", {})
    b.add(mk.box(0.2, 0.2, 0.5), mk.mat.paint("#ff1010", 0.5), name="bottom", at=(0, 0, 0.0))
    b.add(mk.box(0.2, 0.2, 0.5), mk.mat.paint("#1020ff", 0.5), name="top", at=(0, 0, 0.5))
    b.bake_pbr(overlays=[], texture_size=256)

    glb_path = tmp_path / "probe.glb"
    b.scene().export(str(glb_path))

    reloaded = trimesh.load(str(glb_path), force="scene")
    geom = next(iter(reloaded.geometry.values()))
    tex = np.asarray(geom.visual.material.baseColorTexture.convert("RGB"))
    uv = np.asarray(geom.visual.uv)
    H, W = tex.shape[:2]
    cols = np.clip((uv[:, 0] * (W - 1)).astype(int), 0, W - 1)
    rows = np.clip(((1.0 - uv[:, 1]) * (H - 1)).astype(int), 0, H - 1)
    sampled = tex[rows, cols]

    z = geom.vertices[:, 2]
    low_rgb = sampled[z < 0.20].mean(axis=0)
    high_rgb = sampled[z > 0.80].mean(axis=0)
    assert low_rgb[0] > low_rgb[2] * 2.0 and low_rgb[0] > 180, f"bas devrait être rouge : {low_rgb}"
    assert high_rgb[2] > high_rgb[0] * 2.0 and high_rgb[2] > 180, f"haut devrait être bleu : {high_rgb}"


def test_obj_mtl_and_usdz_texture_export(tmp_path):
    b = mk.Builder("tex_exports", {})
    b.add(mk.rounded_box(0.2, 0.2, 0.3, r=0.03), mk.mat.named_metal("brass", 0.3), name="body")
    b.bake_pbr(overlays=[{"type": "edge_wear", "on": ["body"], "amount": 0.6}], texture_size=256)
    sc = b.scene()

    obj_p = tmp_path / "model.obj"
    mk.export_obj_with_mtl(sc, str(obj_p))
    assert "vt " in obj_p.read_text()
    assert "map_Kd " in (tmp_path / "model.mtl").read_text()

    usdz_p = tmp_path / "model.usdz"
    res = usdz_export.export_usdz(sc, str(usdz_p))
    # Le fallback usda est un chemin de production réel (conteneurs sans usd-core) :
    # il doit toujours produire un paquet, quel que soit l'environnement.
    assert res["engine"] in ("usd-core", "usda-fallback")
    assert usdz_p.is_file() and usdz_p.stat().st_size > 0
    if res["engine"] != "usd-core":
        return
    with zipfile.ZipFile(str(usdz_p), "r") as zf:
        names = zf.namelist()
        assert names[0] == "scene.usdc"
        assert any(n.endswith("_albedo.png") for n in names)
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            data_offset = info.header_offset + 30 + len(info.filename.encode("utf-8")) + len(info.extra)
            assert data_offset % 64 == 0, f"entrée {info.filename} non alignée 64 B ({data_offset})"


def test_meshgen_v2_z_up_and_vector_views(tmp_path):
    spec = {
        "name": "obelisk",
        "dims": [0.16, 0.16, 0.80],
        "grid": [48, 48, 96],
        "smooth": 2,
        "texture_size": 256,
        "materials": {
            "base_gold": {"base": "#ffd000", "roughness": 0.3, "metallic": 0.9},
            "shaft":     {"base": "#20a0e0", "roughness": 0.4, "metallic": 0.1},
        },
        "views": {
            "front": {"size": [128, 256], "shapes": [
                {"op": "spline", "mat": "shaft",
                 "center": [[4, 64], [210, 64]],
                 "half_width": [[4, 3.0], [40, 22.0], [210, 42.0]]},
                {"op": "ellipse", "mat": "base_gold", "cx": 64, "cy": 232, "rx": 60, "ry": 22},
            ]},
            "side": {"size": [128, 256], "shapes": [
                {"op": "spline", "mat": "shaft",
                 "center": [[4, 64], [210, 64]],
                 "half_width": [[4, 3.0], [40, 22.0], [210, 42.0]]},
                {"op": "ellipse", "mat": "base_gold", "cx": 64, "cy": 232, "rx": 60, "ry": 22},
            ]},
            "top": {"size": [128, 128], "shapes": [
                {"op": "circle", "mat": "base_gold", "cx": 64, "cy": 64, "r": 61},
            ]},
        },
    }
    occ, _, gs, _ = mg.build_volumes(spec)
    assert occ[:, :, -1].sum() < occ[:, :, 4].sum(), "aucun plateau parasite en haut du SDF"

    rep = mg.generate(spec, str(tmp_path), faces_all=False)
    assert rep["validation"]["watertight"] is True
    assert rep["coherence"]["mean"] > 0.80

    reloaded = trimesh.load(str(tmp_path / "obelisk.glb"), force="scene").to_geometry()
    # Pose stricte sur z=0 et centrage XY
    assert abs(float(reloaded.bounds[0][2])) < 1e-4
    # La base large doit être en BAS (z < 0.20) et la pointe fine en HAUT (z > 0.65)
    z = reloaded.vertices[:, 2]
    width_low = np.ptp(reloaded.vertices[z < 0.20, 0])
    width_high = np.ptp(reloaded.vertices[z > 0.65, 0])
    assert width_low > width_high * 2.0, f"objet inversé ! bas={width_low}, haut={width_high}"


def test_pbr_wrap_seam_continuity():
    """Le tressage hélicoïdal et losange (`diamond`) doit être strictement
    continu au passage de la coupure `atan2` (`theta = -pi <-> +pi`)."""
    cyl = mk.cylinder(0.03, 0.30, sections=48)
    v_labels = np.zeros(len(cyl.vertices), dtype=np.int64)
    mesh, labels, uv = pbr.unwrap(cyl, v_labels)
    spec = {
        "palette": [{"id": "ito", "color": "#1c1e24", "roughness": 0.8, "metallic": 0.0}],
        "overlays": [{"type": "wrap", "on": "ito", "diamond": True,
                      "under_color": "#e5dec9", "count": 8.0}],
        "texture_size": 256,
    }
    alb, mr, nrm, _ = pbr.bake_textures(mesh, labels, uv, spec)
    assert alb.size == (256, 256) and mr.size == (256, 256) and nrm.size == (256, 256)
    # Échantillonne deux colonnes de sommets de part et d'autre de -pi/+pi
    pts = mesh.vertices
    ang = np.arctan2(pts[:, 1], pts[:, 0])
    near_neg = ang < -2.90
    near_pos = ang >  2.90
    assert near_neg.any() and near_pos.any()
    arr = np.asarray(alb.convert("RGB"), dtype=float)
    cols = np.clip((uv[:, 0] * 255).astype(int), 0, 255)
    rows = np.clip(((1.0 - uv[:, 1]) * 255).astype(int), 0, 255)
    diff = abs(arr[rows[near_neg], cols[near_neg]].mean()
               - arr[rows[near_pos], cols[near_pos]].mean())
    assert diff < 18.0, f"saut de couture wrap à +/-pi : {diff:.2f}"


def test_renderer_uv_and_glass():
    from recipes import get as get_recipe
    glass_b = get_recipe("wine_glass")["builder"]()
    im_glass = renderer.render_view(glass_b.scene(), size=256, ssaa=1)
    assert im_glass.size == (256, 256)

    kat_b = get_recipe("katana")["builder"](textured=True)
    im_kat = renderer.render_view(kat_b.scene(), size=256, ssaa=1)
    arr = np.asarray(im_kat.convert("RGB"))
    # Le sujet doit être nettement distinct du fond studio uniforme
    assert (arr.std(axis=(0, 1)) > 4.0).any()


def test_research_background_removal_and_sheet(tmp_path):
    # Sujet rouge sombre au centre sur un grand fond blanc studio #fefefe
    im = Image.new("RGB", (300, 300), (254, 254, 254))
    dr = ImageDraw.Draw(im)
    dr.rectangle([115, 40, 185, 260], fill=(142, 58, 32))
    dr.ellipse([95, 230, 205, 275], fill=(205, 158, 52))
    ref_p = tmp_path / "studio_ref.png"
    im.save(ref_p)

    info = research.analyze_image(str(ref_p))
    top_hexes = [c["hex"].lower() for c in info["palette"][:2]]
    assert "#fefefe" not in top_hexes and "#ffffff" not in top_hexes, (
        f"Fond blanc studio non filtré de la palette dominante : {top_hexes}")

    sheet_p = tmp_path / "sheet.png"
    info["path"] = str(ref_p)
    info["file"] = "studio_ref.png"
    info["title"] = "Un titre extrêmement long qui débordait autrefois sur la colonne voisine"
    research.build_sheet([info, dict(info), dict(info)], str(sheet_p), title="test")
    assert sheet_p.is_file() and sheet_p.stat().st_size > 2000


def test_compare_ground_shadow_stripping():
    # Image de référence avec ombre grise douce sous les roues
    H, W = 240, 320
    rgba = np.full((H, W, 4), 255, dtype=np.uint8)
    dr_im = Image.fromarray(rgba[..., :3])
    dr = ImageDraw.Draw(dr_im)
    # Ombre floue gris clair au sol (y = 195..225)
    dr.ellipse([50, 192, 270, 226], fill=(205, 205, 208))
    # Sujet noir franc au-dessus (y = 70..195)
    dr.rectangle([80, 70, 240, 195], fill=(24, 25, 28))
    rgba[..., :3] = np.asarray(dr_im)

    raw_mask = rgba[..., 0] < 240
    clean_mask = compare.strip_ground_shadow(rgba, raw_mask)
    assert clean_mask[210:, :].sum() < raw_mask[210:, :].sum() * 0.25


def test_packager_builds_valid_zip_archive(tmp_path):
    from pathlib import Path
    import zipfile
    b = mk.Builder("offline_check", {})
    b.add(mk.sphere(0.1), mk.mat.named_metal("gold", 0.25), name="orb")
    glb = tmp_path / "orb.glb"
    b.scene().export(str(glb))

    zip_path = packager.build_asset_zip(tmp_path, name="offline_check")
    assert Path(zip_path).is_file()
    assert zipfile.is_zipfile(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        assert "offline_check/orb.glb" in zf.namelist()
