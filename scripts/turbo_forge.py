#!/usr/bin/env python3
"""
turbo_forge.py — Pipeline Express "One-Shot" (`< 8 s` CPU !) de `3d-forge v5.1`.

Conçu pour éliminer radicalement les générations IA de 30+ minutes en exécutant
**EN UNE SEULE COMMANDE ULTRA-RAPIDE** :
  1. Construction géométrique CAO exacte :
     - soit une recette du catalogue (`sci_fi_crate`, `katana`, `car`, `motocross`, ...),
     - soit un script Python sur mesure définissant `build() -> mk.Builder` (avec `greebles.py` !),
     - soit une sculpture organique multi-vues GPU (`--front ... --side ... [--back ...]`),
  2. Export optionnel des guides orthographiques millimétrés (`--emit-guides`) pour peinture GPU,
  3. Validation d'étanchéité (`is_watertight`) + export `.stl` imprimable si demandé,
  4. Cuisson PBR `1024²` sémantique (8 archétypes + Z-buffer GPU optionnel) + `LOD0 / LOD1 / LOD2`,
  5. Pack complet **Roblox Studio** (`Studs` + `PNG` pur + `Neon_*` + `setup_<Name>.lua`)
     ET **Unreal Engine 5** (`SM_<Name>.glb` + `UCX_*` + `BC / ORM / DirectX -Y`) + `qa_game_sheet.png` !

Exemples :
  # 1. Recette existante (avec paramètres custom) en ~5 secondes :
  python3 scripts/turbo_forge.py katana -o out/katana_fast

  # 2. Modèle 3D 100 % inédit écrit en 1 seul fichier `build()` par l'IA en ~6 secondes :
  python3 scripts/turbo_forge.py custom_plasma_rifle.py -o out/plasma_rifle --emit-guides

  # 3. Sculpture organique depuis 2-3 vues GPU Datacenter + Game-Ready Roblox/UE5 en 1 passe (~18 s) :
  python3 scripts/turbo_forge.py --front f.png --side s.png --back b.png --name wyvern -o out/wyvern
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import game_ready as gr  # noqa: E402
import gpu_bridge as gb  # noqa: E402
import gpu_sculpt as gs  # noqa: E402
import meshkit as mk  # noqa: E402
import recipes  # noqa: E402


def _load_custom_python_builder(py_path: Path, params: dict) -> mk.Builder:
    spec = importlib.util.spec_from_file_location(f"_custom_forge_{py_path.stem}", str(py_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger le module Python {py_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn_name in ("build", f"build_{py_path.stem}"):
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            sig = inspect.signature(fn)
            call_kw = {k: v for k, v in params.items() if k in sig.parameters}
            res = fn(**call_kw)
            if isinstance(res, mk.Builder):
                return res
    for val in vars(mod).values():
        if isinstance(val, mk.Builder):
            return val
    raise ValueError(f"{py_path} doit exposer `def build() -> mk.Builder` (ou une variable `Builder`).")


def _parse_kv_pairs(pairs: list[str] | None) -> dict:
    out = {}
    for item in pairs or []:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        vl = v.strip()
        if vl.lower() in ("true", "false"):
            out[k.strip()] = vl.lower() == "true"
        else:
            try:
                out[k.strip()] = int(vl)
            except ValueError:
                try:
                    out[k.strip()] = float(vl)
                except ValueError:
                    out[k.strip()] = vl
    return out


def run_turbo(
    target: str | None = None,
    out_dir: str | Path = "out/turbo_asset",
    name: str | None = None,
    params: dict | None = None,
    front_view: str | None = None,
    side_view: str | None = None,
    back_view: str | None = None,
    ai_views: dict[str, str] | None = None,
    emit_guides: bool = False,
    export_stl: bool = False,
    lod0_tris: int = 3800,
    tex_size: int = 1024,
    sculpt_res: int = 152,
    engine: str = "roblox_unreal",
) -> dict:
    t0 = time.perf_counter()
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    params = params or {}
    mk.set_quality(1.0)

    sculpt_info = None
    guides_info = None

    if front_view and side_view:
        asset_name = name or (Path(target).stem if target else "sculpt_asset")
        sculpt_dir = out_p / "sculpt_source"
        sculpt_dir.mkdir(parents=True, exist_ok=True)
        mesh_hi, vpack = gs.sculpt_from_views(
            front_view, side_view, back_view,
            grid_res=int(sculpt_res),
        )
        stl_p = sculpt_dir / f"{asset_name}.stl"
        mesh_hi.export(stl_p)
        mesh_pbr, _, _, _ = gs.bake_sculpt_pbr(mesh_hi, vpack, resolution=int(tex_size))
        glb_src = sculpt_dir / f"{asset_name}.glb"
        glb_src.write_bytes(mesh_pbr.export(file_type="glb"))
        sculpt_info = {
            "source_glb": str(glb_src),
            "source_stl": str(stl_p),
            "watertight": bool(mesh_hi.is_watertight),
            "high_tris": int(len(mesh_hi.faces)),
        }
        src_obj = glb_src
    elif target and Path(target).suffix.lower() == ".py" and Path(target).is_file():
        py_p = Path(target)
        src_obj = _load_custom_python_builder(py_p, params)
        asset_name = name or src_obj.name or py_p.stem
    elif target and target in recipes.REGISTRY:
        fn_b = recipes.get(target)["builder"]
        sig = inspect.signature(fn_b)
        call_kw = dict(params)
        if "textured" in sig.parameters:
            call_kw.setdefault("textured", False)
        src_obj = fn_b(**call_kw)
        asset_name = name or target
    elif target and Path(target).exists():
        src_obj = Path(target)
        asset_name = name or Path(target).stem
    else:
        raise ValueError(f"Cible introuvable : {target!r} (recette catalogue, script `.py`, `.glb`, ou `--front/--side`).")

    if emit_guides and isinstance(src_obj, mk.Builder):
        guides_info = gb.render_orthographic_paint_guides(src_obj, str(out_p / "ortho_guides"), size=768)

    stl_out = None
    if export_stl and isinstance(src_obj, mk.Builder):
        stl_out = str(out_p / f"{asset_name}.stl")
        src_obj.export_stl(stl_out)

    manifest = gr.export_game_package(
        src_obj,
        out_dir=out_p,
        name=asset_name,
        engine=engine,
        lod0_tris=int(lod0_tris),
        tex_size=int(tex_size),
        ai_views=ai_views,
    )
    manifest["turbo_total_s"] = round(time.perf_counter() - t0, 2)
    if guides_info is not None:
        manifest["ortho_guides"] = guides_info
    if sculpt_info is not None:
        manifest["sculpt_source"] = sculpt_info
    if stl_out is not None:
        manifest["printable_stl"] = stl_out
    (out_p / "game_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", default=None,
                    help="Recette catalogue (`katana`), script Python custom (`mon_objet.py`), ou `.glb`")
    ap.add_argument("-o", "--out", required=True, help="Dossier de sortie complet")
    ap.add_argument("--name", default=None, help="Nom de l'asset")
    ap.add_argument("--set", nargs="*", default=None, help="Paramètres clé=valeur (ex: length=1.1)")
    ap.add_argument("--front", default=None, help="Vue avant GPU pour sculpture organique")
    ap.add_argument("--side", default=None, help="Vue profil GPU pour sculpture organique")
    ap.add_argument("--back", default=None, help="Vue arrière GPU optionnelle pour sculpture organique")
    ap.add_argument("--ai-front", default=None, help="Peinture orthographique GPU face avant")
    ap.add_argument("--ai-side", default=None, help="Peinture orthographique GPU profil")
    ap.add_argument("--ai-top", default=None, help="Peinture orthographique GPU dessus")
    ap.add_argument("--emit-guides", action="store_true", help="Génère aussi `ortho_guides/` en < 0.4s")
    ap.add_argument("--stl", action="store_true", help="Exporte aussi le `.stl` étanche d'impression 3D")
    ap.add_argument("--engine", default="roblox_unreal",
                    choices=["roblox_unreal", "roblox", "unreal", "unity", "godot", "gltf", "all"])
    ap.add_argument("--lod0-tris", type=int, default=3800)
    ap.add_argument("--tex-size", type=int, default=1024)
    ap.add_argument("--sculpt-res", type=int, default=152)
    args = ap.parse_args(argv)

    ai_v = {k: v for k, v in (("front", args.ai_front), ("side", args.ai_side), ("top", args.ai_top)) if v} or None
    res = run_turbo(
        target=args.target,
        out_dir=args.out,
        name=args.name,
        params=_parse_kv_pairs(args.set),
        front_view=args.front,
        side_view=args.side,
        back_view=args.back,
        ai_views=ai_v,
        emit_guides=args.emit_guides,
        export_stl=args.stl,
        lod0_tris=args.lod0_tris,
        tex_size=args.tex_size,
        sculpt_res=args.sculpt_res,
        engine=args.engine,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
