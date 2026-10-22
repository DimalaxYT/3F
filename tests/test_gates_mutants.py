"""Test des gates : on casse volontairement un package VALIDE et on vérifie que
la gate correspondante passe bien au rouge.

Sans ces tests, une gate peut rester verte pour de mauvaises raisons (chemin
mal résolu, exception avalée, seuil jamais atteint) — c'est exactement comme ça
que le budget UCX à 28 tris a pu être annoncé sans être tenu.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import game_ready as gr  # noqa: E402
import gates as gt  # noqa: E402
from generate import get_recipe  # noqa: E402

NAME = "sci_fi_crate"


@pytest.fixture(scope="module")
def valid_pkg(tmp_path_factory):
    """Package sain construit une fois pour tout le module (petites textures)."""
    out = tmp_path_factory.mktemp("valid")
    builder = get_recipe(NAME)["builder"]()
    solid = builder.union_solid()          # même chemin que turbo_forge
    stl = out / f"{NAME}.stl"
    solid.export(stl)
    man = gr.export_game_package(
        builder, out_dir=out, name=NAME, engine="roblox_unreal",
        lod0_tris=1400, tex_size=256,
    )
    man["printable_stl"] = str(stl)
    man["stl_watertight"] = bool(solid.is_watertight)
    (out / "game_manifest.json").write_text(
        json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    import packager
    man["bundle_zip"] = packager.build_asset_zip(out, name=NAME)
    (out / "game_manifest.json").write_text(
        json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _rewrite(obj, old: str, new: str):
    if isinstance(obj, str) and obj.startswith(old):
        return new + obj[len(old):]
    if isinstance(obj, dict):
        return {k: _rewrite(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite(v, old, new) for v in obj]
    return obj


def clone(pkg: Path, dst: Path) -> Path:
    """Copie le package ET réécrit les chemins absolus du manifest (les gates
    lisent les fichiers via `man[...]['path']`)."""
    shutil.copytree(pkg, dst)
    mp = dst / "game_manifest.json"
    man = json.loads(mp.read_text(encoding="utf-8"))
    man = _rewrite(man, str(pkg), str(dst))
    mp.write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    return dst


def mutate_manifest(pkg: Path, fn) -> None:
    mp = pkg / "game_manifest.json"
    man = json.loads(mp.read_text(encoding="utf-8"))
    fn(man)
    mp.write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")


def mutate_glb_json(glb: Path, fn) -> None:
    """Réécrit le chunk JSON d'un GLB (mêmes offsets binaires, padding 4 octets)."""
    raw = glb.read_bytes()
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    doc = json.loads(raw[20:20 + j_len])
    fn(doc)
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    rest = raw[20 + j_len:]
    total = 12 + 8 + len(js) + len(rest)
    glb.write_bytes(
        raw[:4] + struct.pack("<II", 2, total)
        + struct.pack("<II", len(js), j_type) + js + rest
    )


def gate_map(pkg: Path) -> dict:
    return {g["id"]: g for g in gt.check_package(pkg, "hero")["gates"]}


# --- contrôle positif ------------------------------------------------------
def test_package_sain_toutes_gates_vertes(valid_pkg):
    res = gt.check_package(valid_pkg, "hero")
    failed = [g["id"] for g in res["gates"] if not g["pass"]]
    assert res["all_pass"], f"gates rouges sur un package sain : {failed}"


# --- mutants ---------------------------------------------------------------
def test_gate_tris_part_detecte_depassement_budget(valid_pkg, tmp_path):
    pkg = clone(valid_pkg, tmp_path / "m_tris")

    def boom(man):
        man["lods"]["LOD0"]["tris"] = 99_999
        man["engine_exports"]["roblox"]["max_part_tris"] = 99_999
    mutate_manifest(pkg, boom)
    g = gate_map(pkg)
    assert not g["tris_part"]["pass"], "un dépassement de budget doit faire échouer tris_part"


def test_gate_luau_structure_detecte_bloc_non_ferme(valid_pkg, tmp_path):
    pkg = clone(valid_pkg, tmp_path / "m_lua")
    man = json.loads((pkg / "game_manifest.json").read_text(encoding="utf-8"))
    lua_p = Path(man["engine_exports"]["roblox"]["luau_setup_script"])
    lua = lua_p.read_text(encoding="utf-8")
    i = lua.rfind("end")          # casse un bloc : un `end` disparaît
    lua_p.write_text(lua[:i] + lua[i + 3:], encoding="utf-8")
    g = gate_map(pkg)
    assert not g["luau_structure"]["pass"], "un `end` manquant doit faire échouer luau_structure"


def test_gate_texture_content_detecte_carte_plate(valid_pkg, tmp_path):
    from PIL import Image
    pkg = clone(valid_pkg, tmp_path / "m_tex")
    flat = pkg / "unreal" / f"T_{NAME}_BC.png"
    Image.new("RGB", Image.open(flat).size, (128, 128, 128)).save(flat)
    g = gate_map(pkg)
    assert not g["texture_content"]["pass"], "une ColorMap unie doit être détectée"


def test_gate_emissive_detecte_neon_eteint(valid_pkg, tmp_path):
    pkg = clone(valid_pkg, tmp_path / "m_emis")
    man = json.loads((pkg / "game_manifest.json").read_text(encoding="utf-8"))
    glb = Path(man["engine_exports"]["roblox"]["studio_ready_glb_png"])
    mutate_glb_json(glb, lambda d: [m.update({"emissiveFactor": [0.0, 0.0, 0.0]})
                                    for m in d.get("materials", [])])
    g = gate_map(pkg)
    assert not g["emissive"]["pass"], "un néon déclaré mais éteint doit être détecté"


def test_gate_roblox_png_detecte_texture_webp(valid_pkg, tmp_path):
    pkg = clone(valid_pkg, tmp_path / "m_png")
    man = json.loads((pkg / "game_manifest.json").read_text(encoding="utf-8"))
    glb = Path(man["engine_exports"]["roblox"]["studio_ready_glb_png"])
    mutate_glb_json(glb, lambda d: d["images"][0].update({"mimeType": "image/webp"}))
    g = gate_map(pkg)
    assert not g["roblox_png"]["pass"], "une texture webp dans le pack Roblox doit échouer"


def test_gate_stl_watertight_detecte_trou(valid_pkg, tmp_path):
    import trimesh
    pkg = clone(valid_pkg, tmp_path / "m_stl")
    man = json.loads((pkg / "game_manifest.json").read_text(encoding="utf-8"))
    stl = Path(man["printable_stl"])
    m = trimesh.load(stl)
    holes = trimesh.Trimesh(vertices=m.vertices, faces=m.faces[:-1], process=False)
    holes.export(stl)
    g = gate_map(pkg)
    assert not g["stl_watertight"]["pass"], "un STL percé doit faire échouer stl_watertight"


def test_gate_lod1_silhouette_detecte_lod_intermediaire_casse(valid_pkg, tmp_path):
    """LOD1 déformé (sommets dilatés de 15 %) : l'écart LOD0↔LOD1 doit exploser."""
    import numpy as np
    import trimesh

    pkg = clone(valid_pkg, tmp_path / "m_lod1")
    man = json.loads((pkg / "game_manifest.json").read_text(encoding="utf-8"))
    lod1 = Path(man["lods"]["LOD1"]["path"])
    scene = trimesh.load(lod1, force="scene")
    for geom in scene.geometry.values():
        geom.vertices = np.asarray(geom.vertices) * 1.15
    scene.export(lod1)
    g = gate_map(pkg)
    assert not g["lod1_silhouette"]["pass"], "un LOD1 déformé doit être détecté"


def test_gate_uv_overlap_detecte_atlas_superpose(valid_pkg, tmp_path):
    """UV multipliées puis repliées : les îlots se superposent."""
    import numpy as np
    import trimesh

    pkg = clone(valid_pkg, tmp_path / "m_uv")
    man = json.loads((pkg / "game_manifest.json").read_text(encoding="utf-8"))
    lod0 = Path(man["lods"]["LOD0"]["path"])
    scene = trimesh.load(lod0, force="scene")
    for geom in scene.geometry.values():
        if getattr(geom.visual, "uv", None) is not None:
            uv = np.asarray(geom.visual.uv, dtype=np.float64)
            geom.visual.uv = (uv * 2.5) % 1.0
    scene.export(lod0)
    g = gate_map(pkg)
    assert not g["uv_overlap"]["pass"], "un atlas superposé doit être détecté"


def test_gate_albedo_design_detecte_albedo_crame(valid_pkg, tmp_path):
    """Albédo cramé (toute la réserve de dynamique perdue) : la gate doit le voir.

    C'est le défaut réel mesuré sur le pion d'échecs v5.6 : luminance médiane
    0.94, p99 1.00, dynamique du rendu 0.09. Un simple aplat gris n'est PAS un
    défaut (une porcelaine ou un aplat émaillé sont des designs valides), donc
    le mutant cible le cramage : tout monter à blanc.
    """
    import numpy as np
    from PIL import Image

    pkg = clone(valid_pkg, tmp_path / "m_alb")
    fp = pkg / "unreal" / f"T_{NAME}_BC.png"
    a = np.asarray(Image.open(fp).convert("RGB"), dtype=np.float32) / 255.0
    blown = np.clip(a * 0.25 + 0.78, 0, 1)               # > 0.78 partout, p99 = 1.0
    Image.fromarray((blown * 255).astype(np.uint8)).save(fp)
    g = gate_map(pkg)
    assert not g["albedo_design"]["pass"], "un albédo cramé doit être détecté"
