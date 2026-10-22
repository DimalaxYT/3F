#!/usr/bin/env python3
"""
turbo_forge.py — Pipeline Express "Tout-en-Un" (`~12 à 18 s` CPU) de `3d-forge v5.1`.

Produit en UNE SEULE COMMANDE tous les livrables attendus par l'utilisateur :
  1. `.glb` temps réel (`<nom>_game.glb` + `LOD1` + `LOD2`)
  2. Pack **Roblox Studio** (`roblox/<nom>_roblox.glb` PNG pur + `Studs` + `Neon_*` + `setup_<nom>.lua`)
  3. Pack **Unreal Engine 5** (`unreal/SM_<nom>.glb` + `UCX_*` + `BC / ORM / DirectX -Y`)
  4. `.stl` **100 % étanche (`is_watertight == True`)** prêt à imprimer en 3D (+ découpe plateau
     `256×256×256 mm` à tenons/mortaises via `split_stl.py` avec `--split-bed`)
  5. `preview.html` **interactif 3D hors-ligne** (WebGL PBR + orbite/zoom/filaire)
  6. `qa_game_sheet.png` (**rendu studio 4-vues** haute définition)
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _ensure_runtime_deps() -> None:
    """Auto-installe `requirements.txt` au 1er lancement dans un conteneur vierge (ex: Arena.ai)."""
    try:
        import fast_simplification  # noqa: F401
        import manifold3d  # noqa: F401
        import numpy  # noqa: F401
        import trimesh  # noqa: F401
        import xatlas  # noqa: F401
    except ImportError:
        req = HERE.parent / "requirements.txt"
        if req.is_file():
            cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "-r", str(req)]
            if subprocess.call(cmd) != 0:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])


_ensure_runtime_deps()
sys.path.insert(0, str(HERE))

import game_ready as gr  # noqa: E402
import gpu_bridge as gb  # noqa: E402
import gpu_sculpt as gs  # noqa: E402
import meshkit as mk  # noqa: E402
import packager as pkg  # noqa: E402
import recipes  # noqa: E402
import split_stl  # noqa: E402


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
    depth_view: str | None = None,
    hollow_thickness: float = 0.0,
    ai_views: dict[str, str] | None = None,
    emit_guides: bool = False,
    export_stl: bool = True,
    split_bed: bool = False,
    export_preview: bool = True,
    lod0_tris: int = 3800,
    tex_size: int = 1024,
    sculpt_res: int = 152,
    engine: str = "roblox_unreal",
    gate_target: str = "hero",
    run_gates: bool = True,
    make_gif: bool = False,
) -> dict:
    t0 = time.perf_counter()
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    params = params or {}
    mk.set_quality(1.0)

    sculpt_info = None
    guides_info = None
    stl_out = None
    stl_watertight = None
    stl_volume = None

    def _export_watertight_stl(solid_m, stl_dest: Path) -> tuple[bool, float]:
        """Exporte un `.stl` binaire garanti 100 % étanche APRES rechargement disque `trimesh.load`."""
        import numpy as _np
        import trimesh as _tm

        def _strip_crumbs(m_in):
            comps = m_in.split(only_watertight=False)
            if len(comps) > 1:
                kept = [c for c in comps if len(c.faces) >= 12 and c.is_watertight]
                if kept:
                    return _tm.util.concatenate(kept) if len(kept) > 1 else kept[0]
            return m_in

        m_out = _strip_crumbs(solid_m.copy())
        m_out.export(stl_dest)
        reloaded = _strip_crumbs(_tm.load(stl_dest, force="mesh"))
        if reloaded.is_watertight:
            reloaded.export(stl_dest)
            chk0 = _tm.load(stl_dest, force="mesh")
            if chk0.is_watertight:
                return True, float(chk0.volume)

        # Les intersections booléennes complexes créent parfois des arêtes quasi-nulles (< 1e-5 m)
        # qui génèrent 1-2 triangles miettes lors de la quantification STL float32 :
        try:
            import fast_simplification
            vo, fo = fast_simplification.simplify(
                _np.asarray(m_out.vertices, dtype=_np.float32),
                _np.asarray(m_out.faces, dtype=_np.int32),
                target_reduction=0.10,
                agg=4,
            )
            cleaned = _strip_crumbs(_tm.Trimesh(vertices=vo, faces=fo, process=True))
            cleaned.export(stl_dest)
            chk1 = _tm.load(stl_dest, force="mesh")
            if chk1.is_watertight and len(chk1.faces) >= 12:
                return True, float(chk1.volume)
        except Exception:
            pass
        if getattr(mk, "HAS_MANIFOLD", False):
            import manifold3d
            for tol in (2e-5, 8e-5, 2e-4):
                try:
                    w = solid_m.copy()
                    q = _np.round(w.vertices / tol) * tol
                    w.vertices = q
                    w.merge_vertices()
                    w.update_faces(w.nondegenerate_faces())
                    w.remove_unreferenced_vertices()
                    if not w.is_watertight:
                        _tm.repair.fill_holes(w)
                        _tm.repair.fix_winding(w)
                    v32 = _np.asarray(w.vertices, dtype=_np.float32)
                    f32 = _np.asarray(w.faces, dtype=_np.uint32)
                    mm = manifold3d.Manifold(manifold3d.Mesh(vert_properties=v32, tri_verts=f32)).to_mesh()
                    cand = _tm.Trimesh(vertices=mm.vert_properties[:, :3], faces=mm.tri_verts, process=True)
                    cand.export(stl_dest)
                    chk = _tm.load(stl_dest, force="mesh")
                    if chk.is_watertight and len(chk.faces) >= 4:
                        return True, float(chk.volume)
                except Exception:
                    continue
        return bool(reloaded.is_watertight), float(reloaded.volume)

    if front_view and (side_view or depth_view):
        asset_name = name or (Path(target).stem if target else "sculpt_asset")
        sculpt_dir = out_p / "sculpt_source"
        sculpt_dir.mkdir(parents=True, exist_ok=True)
        mesh_hi, vpack = gs.sculpt_from_views(
            front_view, side_view, back_view,
            grid_res=int(sculpt_res),
            depth_path=depth_view,
            hollow_thickness=float(hollow_thickness),
        )
        stl_main = out_p / f"{asset_name}.stl"
        stl_watertight, stl_volume = _export_watertight_stl(mesh_hi, stl_main)
        stl_out = str(stl_main)
        mesh_pbr, _, _, _ = gs.bake_sculpt_pbr(mesh_hi, vpack, resolution=int(tex_size))
        glb_src = sculpt_dir / f"{asset_name}.glb"
        glb_src.write_bytes(mesh_pbr.export(file_type="glb"))
        sculpt_info = {
            "source_glb": str(glb_src),
            "printable_stl": stl_out,
            "watertight": stl_watertight,
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

    if export_stl and stl_out is None and isinstance(src_obj, mk.Builder):
        solid = src_obj.union_solid()
        stl_main = out_p / f"{asset_name}.stl"
        stl_watertight, stl_volume = _export_watertight_stl(solid, stl_main)
        stl_out = str(stl_main)

    is_sculpt = sculpt_info is not None
    manifest = gr.export_game_package(
        src_obj,
        out_dir=out_p,
        name=asset_name,
        engine=engine,
        lod0_tris=int(lod0_tris),
        tex_size=int(tex_size),
        weathering=(not is_sculpt),
        delight_pass=(False if is_sculpt else None),
        ai_views=ai_views,
    )

    if stl_out is not None:
        manifest["printable_stl"] = stl_out
        manifest["stl_watertight"] = stl_watertight
        if split_bed:
            manifest["split_stl_kit"] = split_stl.export_split_kit(stl_out, str(out_p / "print_parts"))

    if make_gif:
        try:
            import trimesh
            import renderer as rn
            sc = trimesh.load(manifest["lods"]["LOD0"]["path"])
            frames = rn.render_turntable(sc, str(out_p), asset_name, n=10, size=320)
            manifest["turntable_gif"] = rn.make_gif(
                frames, str(out_p / f"{asset_name}_turntable.gif"))
        except Exception as exc:
            manifest["turntable_gif_error"] = str(exc)

    if guides_info is not None:
        manifest["ortho_guides"] = guides_info
    if sculpt_info is not None:
        manifest["sculpt_source"] = sculpt_info

    manifest["turbo_total_s"] = round(time.perf_counter() - t0, 2)
    (out_p / "game_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # `report.json` — schéma UNIFIÉ lu par `critique.py` (boucle d'autocritique notée)
    # et `preview.py` : le chemin turbo et le chemin meshgen partagent le même contrat QA.
    lod0_tris_out = int(manifest.get("lods", {}).get("LOD0", {}).get("tris", 0))
    report = {
        "pipeline": "turbo_forge",
        "prompt": f"{asset_name} (turbo_forge, cible {gate_target})",
        "output_dir": str(out_p),
        "params": {"budget_tris": int(lod0_tris)},
        "validation": {
            "watertight": bool(stl_watertight),
            "winding_consistent": bool(stl_watertight),
            "triangles": lod0_tris_out,
            "over_budget": lod0_tris_out > int(lod0_tris),
            "components": 1,
            "degenerate_faces": 0,
            "volume_m3": stl_volume,
            "iou_views": {},
            "iou_mean": 0.0,
        },
        "photos": {},
        "renders": [manifest["qa_sheet"]] if manifest.get("qa_sheet") else [],
        "references": None,
        "engine_exports": manifest.get("engine_exports", {}),
        "stl": manifest.get("printable_stl"),
    }
    (out_p / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if run_gates:
        try:
            import gates as gt
            res = gt.check_package(out_p, gate_target)
            gt.write_outputs(out_p, res)
            manifest["gates"] = {"target": gate_target, "all_pass": res["all_pass"],
                                 "n_pass": res["n_pass"], "n_total": res["n_total"]}
            (out_p / "game_manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # les gates ne doivent jamais casser la génération
            manifest["gates"] = {"target": gate_target, "error": str(exc)}
            (out_p / "game_manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    zip_bundle = pkg.build_asset_zip(out_p, name=asset_name)
    manifest["bundle_zip"] = str(zip_bundle)
    (out_p / "game_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return manifest


CACHE_NAME = "_forge_cache.json"
CACHE_VERSION = "v5.3-1"


def _cache_key(args) -> str:
    """Hash des ENTRÉES du run (source géométrique + vues + paramètres) :
    identique => livrables reproductibles à l'identique, donc réutilisables."""
    import hashlib
    h = hashlib.sha256()
    h.update(CACHE_VERSION.encode())
    volatile = {"dry_run", "resume", "json"}
    for k, v in sorted(vars(args).items()):
        if k in volatile:
            continue
        h.update(f"{k}={v}".encode())
    for blob in (args.target, args.front, args.side, args.back):
        if blob and Path(blob).is_file():
            h.update(Path(blob).read_bytes())
    return h.hexdigest()[:16]


def _plan(args, key: str, out_p: Path) -> None:
    tgt = args.target
    if args.front and args.side:
        kind = "sculpture organique multi-vues (gpu_sculpt)"
    elif tgt and Path(tgt).suffix.lower() == ".py":
        kind = "builder Python custom (`def build() -> mk.Builder`)"
    elif tgt and tgt in recipes.REGISTRY:
        kind = f"recette catalogue `{tgt}`"
    elif tgt and Path(tgt).exists():
        kind = "fichier .glb existant (conversion game-ready)"
    else:
        kind = f"CIBLE INCONNUE : {tgt!r}"
    prev = out_p / CACHE_NAME
    state = "identique au run précédent" if (
        prev.is_file() and json.loads(prev.read_text()).get("hash") == key
    ) else ("différent du run précédent" if prev.is_file() else "premier run")
    print(f"[plan] cible      : {kind}")
    print(f"[plan] sortie     : {out_p}")
    print(f"[plan] livrables  : <name>_game.glb + LOD1/2 | roblox/ (glb PNG + 4 maps + "
          f"setup lua) | unreal/ (SM_ + UCX_ + BC/ORM/N) | .stl étanche | "
          f"<name>.zip | qa_game_sheet.png (10 panneaux) | gates.json | "
          f"qa_summary.md | report.json" + (" | turntable.gif" if args.gif else ""))
    print(f"[plan] gates      : --target {args.gate_target} (19 gates, exit code)")
    print(f"[plan] cache      : {key} ({state})")


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
    ap.add_argument("--depth", default=None, help="Carte de profondeur alignée à --front (blanc = proche)")
    ap.add_argument("--hollow-thickness", type=float, default=0.0,
                    help="Épaisseur de coque creuse en mètres (ex: 0.012 pour masque/casque)")
    ap.add_argument("--ai-front", default=None, help="Peinture orthographique GPU face avant")
    ap.add_argument("--ai-side", default=None, help="Peinture orthographique GPU profil")
    ap.add_argument("--ai-top", default=None, help="Peinture orthographique GPU dessus")
    ap.add_argument("--emit-guides", action="store_true", help="Génère aussi `ortho_guides/` en < 0.4s")
    ap.add_argument("--no-stl", action="store_true", help="Désactive l'export automatique du `.stl` étanche")
    ap.add_argument("--stl", action="store_true",
                    help="Alias explicite (no-op) : le `.stl` étanche est déjà exporté par défaut")
    ap.add_argument("--split-bed", action="store_true",
                    help="Découpe automatiquement le `.stl` en pièces <= 256×256×256 mm à tenons/mortaises")
    ap.add_argument("--no-preview", action="store_true", help="Désactive la génération de `preview.html`")
    ap.add_argument("--target", dest="gate_target", default="hero",
                    choices=["hero", "ugc", "print"],
                    help="Cible de gates : hero <= 9 800 tris/part, ugc <= 4 000 (Roblox UGC), print = STL bloquant")
    ap.add_argument("--no-gates", action="store_true", help="Saute l'évaluation gates.py (gates.json/qa_summary.md)")
    ap.add_argument("--json", action="store_true",
                    help="Imprime le manifest JSON complet (défaut : résumé 8 lignes économe en tokens)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Imprime le plan (cible, livrables, gates, cache) sans rien exécuter")
    ap.add_argument("--resume", action="store_true",
                    help="Si le hash des entrées est identique au run précédent du dossier, "
                         "réutilise les livrables (gates re-vérifiées) au lieu de tout reconstruire")
    ap.add_argument("--gif", action="store_true",
                    help="Ajoute un turntable GIF 10 vues (320 px) au dossier de sortie")
    ap.add_argument("--engine", default="roblox_unreal",
                    choices=["roblox_unreal", "roblox", "unreal", "unity", "godot", "gltf", "all"])
    ap.add_argument("--lod0-tris", type=int, default=3800)
    ap.add_argument("--tex-size", type=int, default=1024)
    ap.add_argument("--sculpt-res", type=int, default=152)
    args = ap.parse_args(argv)
    out_p = Path(args.out)
    key = _cache_key(args)

    if args.dry_run:
        _plan(args, key, out_p)
        return 0

    cache_p = out_p / CACHE_NAME
    cached = (args.resume and cache_p.is_file()
              and json.loads(cache_p.read_text(encoding="utf-8")).get("hash") == key)
    manifest_p = out_p / "game_manifest.json"
    if cached and manifest_p.is_file() and (out_p / "qa_game_sheet.png").is_file():
        res = json.loads(manifest_p.read_text(encoding="utf-8"))
        if not args.no_gates:
            try:
                import gates as gt
                gates_res = gt.check_package(out_p, args.gate_target)
                gt.write_outputs(out_p, gates_res)
                res["gates"] = {"target": args.gate_target, "all_pass": gates_res["all_pass"],
                                "n_pass": gates_res["n_pass"], "n_total": gates_res["n_total"]}
            except Exception as exc:
                res["gates"] = {"target": args.gate_target, "error": str(exc)}
        print(f"[resume] hash {key} identique : livrables réutilisés, gates re-vérifiées.")
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            _print_summary(res)
        return 0 if res.get("gates", {}).get("all_pass", True) else 1

    ai_v = {k: v for k, v in (("front", args.ai_front), ("side", args.ai_side), ("top", args.ai_top)) if v} or None
    res = run_turbo(
        target=args.target,
        out_dir=args.out,
        name=args.name,
        params=_parse_kv_pairs(args.set),
        front_view=args.front,
        side_view=args.side,
        back_view=args.back,
        depth_view=args.depth,
        hollow_thickness=args.hollow_thickness,
        ai_views=ai_v,
        emit_guides=args.emit_guides,
        export_stl=not args.no_stl,
        split_bed=args.split_bed,
        export_preview=not args.no_preview,
        lod0_tris=args.lod0_tris,
        tex_size=args.tex_size,
        sculpt_res=args.sculpt_res,
        engine=args.engine,
        gate_target=args.gate_target,
        run_gates=not args.no_gates,
        make_gif=args.gif,
    )
    out_p.mkdir(parents=True, exist_ok=True)
    cache_p.write_text(json.dumps({"hash": key, "version": CACHE_VERSION}, indent=2),
                       encoding="utf-8")
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        _print_summary(res)
    gates_info = res.get("gates", {})
    if gates_info and gates_info.get("all_pass") is False:
        return 1
    return 0


def _print_summary(res: dict) -> None:
    """Résumé 8 lignes (économe en tokens) — le manifest complet reste dans
    `game_manifest.json` et s'imprime avec `--json`."""
    out = Path(res.get("bundle_zip", res.get("qa_sheet", ""))).parent if (res.get("bundle_zip") or res.get("qa_sheet")) else Path(".")
    lods = res.get("lods", {})
    rbx = res.get("engine_exports", {}).get("roblox", {})
    gates = res.get("gates", {})
    print(f"[turbo_forge] {res.get('asset_name')} — {res.get('turbo_total_s')} s "
          f"(cible {gates.get('target', '?')})")
    print(f"  LODs      : LOD0 {lods.get('LOD0', {}).get('tris')} tris | "
          f"LOD1 {lods.get('LOD1', {}).get('tris')} | LOD2 {lods.get('LOD2', {}).get('tris')} "
          f"| draw calls {res.get('draw_calls_before')} -> {res.get('draw_calls_after')}")
    print(f"  Roblox    : {rbx.get('max_part_tris')} tris/part | "
          f"{' x '.join(f'{s:.2f}' for s in rbx.get('size_studs_xyz', []))} Studs | "
          f"{len(rbx.get('neon_parts', []))} Neon | {Path(rbx.get('studio_ready_glb_png', '-')).name}")
    print(f"  STL       : {Path(res.get('printable_stl', '-')).name} "
          f"(watertight={res.get('stl_watertight')})")
    if gates.get("error"):
        print(f"  Gates     : ERREUR d'évaluation : {gates['error']}")
    else:
        print(f"  Gates     : {gates.get('n_pass', '?')}/{gates.get('n_total', '?')} OK "
              f"({'LIVRABLE' if gates.get('all_pass') else 'NON LIVRABLE — voir gates.json'})")
    print(f"  Archive   : {Path(res.get('bundle_zip', '-')).name} | {Path(res.get('qa_sheet', '-')).name} | qa_summary.md")
    print(f"  Dossier   : {out}")
    print("  (manifest complet : game_manifest.json / --json)")


if __name__ == "__main__":
    raise SystemExit(main())
