#!/usr/bin/env python3
"""
gates.py — Portes de qualité MESURABLES de `3d-forge` (v5.2).

Les gates Roblox/UE5/print étaient déjà *écrits* dans `tests/test_v5_game_ready.py`
mais invisibles pour l'agent et la CI E2E. Ce module les expose en CLI :

    python3 scripts/gates.py out/<nom> [--target hero|ugc|print] [--json]

→ écrit `out/<nom>/gates.json` (1 ligne par gate : id / libellé / pass / valeur /
  attendu), imprime un résumé lisible et sort avec un code non nul si un gate
  échoue. `turbo_forge.py` l'appelle automatiquement en fin de run.

Cibles (`--target`) — plafonds DOCUMENTÉS par cible, le code est la source de vérité :
  * `hero`  : asset temps réel standard   — <= 9 800 tris/MeshPart (budget de perf ;
              le plafond moteur Roblox actuel est 20 000 tris/mesh), textures <= 1024².
  * `ugc`   : accessoire UGC rigide Roblox — <= 4 000 tris (modération UGC),
              textures <= 1024².
  * `print` : impression 3D — STL watertight + volume > 0 obligatoire, tris libres.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

ROBLOX_STUDS_PER_METER = 25.0 / 7.0  # 1 Stud = 0.28 m (spec Roblox 25:7)
ROBLOX_MAX_TEX_SIZE = 1024
ROBLOX_ENGINE_MESH_CAP = 20_000  # plafond moteur Roblox (Creator Store)
ROBLOX_UGC_RIGID_CAP = 4_000  # modération UGC accessoire rigide

TARGETS = {
    "hero": {"max_part_tris": 9_800, "max_tex": ROBLOX_MAX_TEX_SIZE, "require_stl": False},
    "ugc": {"max_part_tris": ROBLOX_UGC_RIGID_CAP, "max_tex": ROBLOX_MAX_TEX_SIZE, "require_stl": False},
    "print": {"max_part_tris": ROBLOX_ENGINE_MESH_CAP, "max_tex": ROBLOX_MAX_TEX_SIZE, "require_stl": True},
}


def _glb_json(path: Path) -> dict | None:
    """Lit le chunk JSON d'un `.glb` sans charger les binaries (rapide, sans trimesh)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) < 20 or raw[:4] != b"glTF":
        return None
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    if j_type != 0x4E4F534A:
        return None
    try:
        return json.loads(raw[20:20 + j_len].decode("utf-8"))
    except Exception:
        return None


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        raw = path.read_bytes()[:33]
    except OSError:
        return None
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", raw[16:24])
    return int(w), int(h)


class GateList:
    def __init__(self) -> None:
        self.gates: list[dict] = []

    def add(self, gid: str, label: str, ok: bool, value, expected) -> None:
        self.gates.append({
            "id": gid, "label": label, "pass": bool(ok),
            "value": value, "expected": expected,
        })

    @property
    def all_pass(self) -> bool:
        return all(g["pass"] for g in self.gates)

    def to_dict(self, target: str, out_dir: str) -> dict:
        return {
            "target": target,
            "out_dir": str(out_dir),
            "all_pass": self.all_pass,
            "n_pass": sum(1 for g in self.gates if g["pass"]),
            "n_total": len(self.gates),
            "gates": self.gates,
        }


def check_package(out_dir: str | Path, target: str = "hero") -> dict:
    """Évalue toutes les gates d'un dossier produit par `turbo_forge.py`/`game_ready.py`."""
    out_p = Path(out_dir)
    cfg = TARGETS[target]
    g = GateList()

    man_p = out_p / "game_manifest.json"
    if not man_p.is_file():
        g.add("manifest", "game_manifest.json présent", False, str(man_p), "fichier existant")
        return g.to_dict(target, out_p)
    man = json.loads(man_p.read_text(encoding="utf-8"))
    g.add("manifest", "game_manifest.json présent", True, str(man_p), "fichier existant")

    name = man.get("asset_name", out_p.name)
    lods = man.get("lods", {})

    # --- budget triangles par MeshPart / par cible -------------------------
    rbx = man.get("engine_exports", {}).get("roblox", {})
    max_part = int(rbx.get("max_part_tris", lods.get("LOD0", {}).get("tris", 0)))
    g.add("tris_part", f"tris/MeshPart <= {cfg['max_part_tris']} (cible {target})",
          0 < max_part <= cfg["max_part_tris"], max_part, f"<= {cfg['max_part_tris']}")
    g.add("tris_engine_cap", f"tris/MeshPart <= plafond moteur Roblox {ROBLOX_ENGINE_MESH_CAP}",
          max_part <= ROBLOX_ENGINE_MESH_CAP, max_part, f"<= {ROBLOX_ENGINE_MESH_CAP}")

    # --- chaîne LOD monotone ------------------------------------------------
    t0 = int(lods.get("LOD0", {}).get("tris", 0))
    t1 = int(lods.get("LOD1", {}).get("tris", 0))
    t2 = int(lods.get("LOD2", {}).get("tris", 0))
    g.add("lod_chain", "LOD0 > LOD1 > LOD2 > 50 tris", t0 > t1 > t2 > 50,
          f"{t0}/{t1}/{t2}", "décroissant")

    # --- pack Roblox : PNG pur, textures <= 1024², Studs raisonnables --------
    rbx_glb = rbx.get("studio_ready_glb_png")
    if rbx_glb and Path(rbx_glb).is_file():
        gj = _glb_json(Path(rbx_glb)) or {}
        mimes = [im.get("mimeType") for im in gj.get("images", [])]
        g.add("roblox_png", "roblox/*.glb = PNG pur (zéro EXT_texture_webp)",
              bool(mimes) and all(m == "image/png" for m in mimes)
              and "EXT_texture_webp" not in (gj.get("extensionsUsed") or []),
              sorted(set(mimes)), "['image/png']")
        tex_ok = True
        dims = []
        sa = rbx.get("surface_appearance", {})
        for p in sa.values():
            d = _png_size(Path(p)) if isinstance(p, str) else None
            if d:
                dims.append(d)
                if d[0] > cfg["max_tex"] or d[1] > cfg["max_tex"]:
                    tex_ok = False
        g.add("roblox_tex", f"textures SurfaceAppearance <= {cfg['max_tex']}²",
              tex_ok and bool(dims), dims, f"<= {cfg['max_tex']}x{cfg['max_tex']}")
        studs = rbx.get("size_studs_xyz") or [0, 0, 0]
        g.add("roblox_studs", "dims Studs dans [0.1, 2048] par axe",
              all(0.1 <= s <= 2048 for s in studs), [round(s, 2) for s in studs], "[0.1, 2048]")
        lua = rbx.get("luau_setup_script")
        g.add("roblox_lua", "setup_<Name>.lua présent et non vide",
              bool(lua) and Path(lua).is_file() and Path(lua).stat().st_size > 200,
              lua, "fichier > 200 o")
    else:
        g.add("roblox_png", "pack roblox/ présent", False, rbx_glb, "roblox/<name>_roblox.glb")

    # --- pack Unreal ---------------------------------------------------------
    ue = man.get("engine_exports", {}).get("unreal", {})
    ue_glb = ue.get("static_mesh_with_ucx") or ue.get("static_mesh_glb")
    if ue_glb is None:
        cand = list((out_p / "unreal").glob("SM_*.glb")) if (out_p / "unreal").is_dir() else []
        ue_glb = str(cand[0]) if cand else None
    if ue_glb and Path(ue_glb).is_file():
        gj = _glb_json(Path(ue_glb)) or {}
        nodes = [n.get("name", "") for n in gj.get("nodes", [])]
        g.add("ue_ucx", "colliders convexes UCX_SM_* présents",
              any(n.startswith("UCX_") for n in nodes),
              sum(1 for n in nodes if n.startswith("UCX_")), ">= 1")
        bc = ue.get("base_color")
        orm = ue.get("orm_packed") or ue.get("orm")
        nrm = ue.get("normal_directx_neg_y") or ue.get("normal_dx")
        g.add("ue_maps", "T_*_BC / T_*_ORM / T_*_N (DirectX -Y) présents",
              all(p and Path(p).is_file() for p in (bc, orm, nrm)),
              [bool(bc), bool(orm), bool(nrm)], "[True, True, True]")
    else:
        g.add("ue_ucx", "pack unreal/ présent", False, ue_glb, "unreal/SM_<name>.glb")

    # --- STL impression ------------------------------------------------------
    stl = man.get("printable_stl")
    if stl and Path(stl).is_file():
        wt = man.get("stl_watertight")
        vol = None
        try:
            import trimesh
            # process=True (défaut) : fusion des sommets coïncidents, comme le fait
            # un slicer — c'est la sémantique « étanche » qui compte pour l'impression.
            m = trimesh.load(stl)
            wt = bool(m.is_watertight)
            vol = float(m.volume)
        except Exception:
            pass
        g.add("stl_watertight", "STL 100 % watertight", bool(wt), wt, True)
        g.add("stl_volume", "STL volume strictement positif", bool(vol and vol > 0),
              round(vol, 6) if vol is not None else None, "> 0")
    elif cfg["require_stl"]:
        g.add("stl_watertight", "STL présent (cible print)", False, stl, "<name>.stl")

    # --- QA visuelle ---------------------------------------------------------
    qa = man.get("qa_sheet")
    g.add("qa_sheet", "qa_game_sheet.png présent", bool(qa) and Path(qa).is_file(), qa, "png")

    return g.to_dict(target, out_p)


def write_outputs(out_dir: str | Path, result: dict, summary_md: bool = True) -> Path:
    out_p = Path(out_dir)
    gp = out_p / "gates.json"
    gp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if summary_md:
        man_p = out_p / "game_manifest.json"
        man = json.loads(man_p.read_text(encoding="utf-8")) if man_p.is_file() else {}
        lines = [f"# QA summary — {man.get('asset_name', out_p.name)}", ""]
        lines.append(f"Cible : **{result['target']}** | gates : "
                     f"**{result['n_pass']}/{result['n_total']} OK** "
                     f"({'LIVRABLE' if result['all_pass'] else 'NON LIVRABLE'})")
        lines.append("")
        lines.append("| gate | résultat | valeur | attendu |")
        lines.append("|---|---|---|---|")
        for gt in result["gates"]:
            lines.append(f"| {gt['label']} | {'✅' if gt['pass'] else '❌'} "
                         f"| {gt['value']} | {gt['expected']} |")
        lods = man.get("lods", {})
        if lods:
            lines.append("")
            lines.append(f"- LOD0 {lods.get('LOD0', {}).get('tris')} tris | "
                         f"LOD1 {lods.get('LOD1', {}).get('tris')} | "
                         f"LOD2 {lods.get('LOD2', {}).get('tris')} | "
                         f"draw calls {man.get('draw_calls_before')} -> {man.get('draw_calls_after')}")
        rbx = man.get("engine_exports", {}).get("roblox", {})
        if rbx:
            studs = rbx.get("size_studs_xyz") or []
            lines.append(f"- Roblox : {rbx.get('max_part_tris')} tris/part max, "
                         f"{' x '.join(f'{s:.2f}' for s in studs)} Studs, "
                         f"{len(rbx.get('neon_parts', []))} pièce(s) Neon")
        lines.append(f"- STL : `{man.get('printable_stl', '-')}` "
                     f"(watertight={man.get('stl_watertight')})")
        lines.append(f"- Durée pipeline : {man.get('turbo_total_s', man.get('duration_s', '?'))} s")
        (out_p / "qa_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return gp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir", help="dossier de sortie turbo_forge/game_ready")
    ap.add_argument("--target", choices=sorted(TARGETS), default="hero")
    ap.add_argument("--json", action="store_true", help="imprime gates.json complet")
    ap.add_argument("--no-summary", action="store_true", help="n'écrit pas qa_summary.md")
    args = ap.parse_args(argv)

    res = check_package(args.out_dir, args.target)
    write_outputs(args.out_dir, res, summary_md=not args.no_summary)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        for gt in res["gates"]:
            mark = "OK  " if gt["pass"] else "FAIL"
            print(f"  [{mark}] {gt['label']} : {gt['value']} (attendu {gt['expected']})")
        print(f"=> gates {res['n_pass']}/{res['n_total']} "
              f"({'LIVRABLE' if res['all_pass'] else 'NON LIVRABLE'}) "
              f"-> {Path(args.out_dir) / 'gates.json'}")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
