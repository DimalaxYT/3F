#!/usr/bin/env python3
"""
generate.py — pipeline principal 3d-forge.

    python generate.py <recette> [--set cle=valeur ...] [options]

Chaîne : résolution recette → construction géométrique → validation →
exports (GLB / OBJ+MTL / STL / USDZ) → rendus PNG multi-angles → rapport JSON.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
import time
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import meshkit as mk                      # noqa: E402
from recipes import catalog, get as get_recipe   # noqa: E402
import renderer                           # noqa: E402
import usdz_export                        # noqa: E402
import validate as valmod                 # noqa: E402

VALID_FORMATS = ("glb", "obj", "stl", "usdz")
DEFAULT_VIEWS = ("front", "three_quarter", "top")


def coerce_params(recipe_name, raw_sets, json_path=None):
    recipe = get_recipe(recipe_name)
    defaults = recipe["defaults"]
    info = {i["name"]: i for i in recipe["info"]}
    params = dict(defaults)

    if json_path:
        with open(json_path) as f:
            override = json.load(f)
        for k, v in override.items():
            if k not in defaults:
                raise ValueError(f"paramètre inconnu pour « {recipe_name} » : {k} "
                                 f"(disponibles : {sorted(defaults)})")
            params[k] = v

    for kv in raw_sets or []:
        if "=" not in kv:
            raise ValueError(f"--set attend cle=valeur, reçu : {kv}")
        k, v = kv.split("=", 1)
        if k not in defaults:
            raise ValueError(f"paramètre inconnu pour « {recipe_name} » : {k} "
                             f"(disponibles : {sorted(defaults)})")
        t = info.get(k, {}).get("type", "str")
        if t == "float":
            params[k] = float(v)
        elif t == "int":
            params[k] = int(float(v))
        elif t == "bool":
            params[k] = v.strip().lower() in ("1", "true", "yes", "on", "vrai", "oui")
        elif t == "choice":
            choices = info[k].get("choices", [])
            if v not in choices:
                raise ValueError(f"{k}={v!r} invalide, choix : {choices}")
            params[k] = v
        else:
            params[k] = v
    return params


def _parse_quality(v: str) -> float:
    presets = {"low": 0.6, "draft": 0.6, "medium": 1.0, "high": 1.5, "ultra": 2.0}
    return presets[v.lower()] if v.lower() in presets else float(v)


def unique_dir(base):
    if not os.path.exists(base):
        return base
    i = 2
    while os.path.exists(f"{base}_{i}"):
        i += 1
    return f"{base}_{i}"


def run(recipe_name, params, formats, outdir, views, size, quality,
        render=True, quiet=False, faces_all=False, render_engine="auto",
        texture_ai=None, game_ready_mode=False, game_engine="roblox_unreal", lod0_tris=3200):
    t0 = time.time()
    mk.set_quality(quality)
    recipe = get_recipe(recipe_name)
    builder = recipe["builder"](**params)
    scene = builder.scene()
    stats = builder.stats()

    solid = None
    if "stl" in formats or texture_ai:
        solid = builder.union_solid()
    if texture_ai:
        import gpu_bridge
        with open(texture_ai, encoding="utf-8") as fh:
            ai_spec = json.load(fh)
        solid_ai, _ = gpu_bridge.bake_ai_tiles_to_mesh(solid.copy(), ai_spec)
        scene = trimesh.Scene(solid_ai)
    checks = valmod.check_mesh(solid if solid is not None else scene)
    printable = checks.get("is_printable", False)

    stem = recipe_name
    outdir = unique_dir(os.path.join(outdir, stem))
    os.makedirs(outdir, exist_ok=True)
    files = {}

    if "glb" in formats:
        p = os.path.join(outdir, stem + ".glb")
        mk.export_glb_pbr(scene, p)
        files["glb"] = p
    if "obj" in formats:
        p = os.path.join(outdir, stem + ".obj")
        mk.export_obj_with_mtl(scene, p)
        files["obj"] = p
    if "stl" in formats:
        p = os.path.join(outdir, stem + ".stl")
        solid.export(p)
        files["stl"] = p
    if "usdz" in formats:
        p = os.path.join(outdir, stem + ".usdz")
        engine = usdz_export.export_usdz(scene, p)
        files["usdz"] = p

    renders = []
    if render:
        try:
            if render_engine == "cycles":
                import cycles_render
                if "glb" not in files:
                    tmp_g = os.path.join(outdir, "_cycles_tmp.glb")
                    scene.export(tmp_g)
                else:
                    tmp_g = files["glb"]
                vmap = {v: renderer.DEFAULT_VIEWS[v] for v in views}
                omap = {v: os.path.join(outdir, f"{stem}_{v}.png") for v in views}
                cycles_render.render_cycles_glb(tmp_g, vmap, omap, size=size)
                renders = list(omap.values())
                if "glb" not in files and os.path.exists(tmp_g):
                    os.unlink(tmp_g)
            else:
                renders = renderer.render_views(scene, outdir, stem, views=list(views),
                                                size=size)
        except Exception as e:  # le rendu ne doit jamais tuer la génération
            if not quiet:
                print(f"[renderer] rendu échoué ({e}) — exports conservés", file=sys.stderr)

    # photos de TOUTES les faces + turntable (livraison complète)
    photos = {}
    if render and faces_all:
        try:
            face_paths, faces_sheet = renderer.render_all_faces(scene, outdir,
                                                                stem, size=768)
            turn_paths, turn_sheet = renderer.render_turntable(scene, outdir,
                                                               stem, n=8, size=560)
            photos = {"all_faces": faces_sheet, "faces": face_paths,
                      "turntable": turn_sheet, "turn_images": turn_paths}
        except Exception as e:
            if not quiet:
                print(f"[renderer] photos toutes faces échouées ({e})",
                      file=sys.stderr)

    game_pack = None
    if game_ready_mode:
        import game_ready as gr
        game_pack = gr.export_game_package(
            builder,
            out_dir=os.path.join(outdir, "game_ready"),
            name=stem,
            engine=game_engine,
            lod0_tris=lod0_tris,
            tex_size=1024,
        )

    report = {
        "recipe": recipe_name,
        "params": params,
        "stats": stats,
        "validation": checks,
        "files": {k: {"path": os.path.abspath(v),
                      "bytes": os.path.getsize(v)} for k, v in files.items()},
        "renders": [os.path.abspath(p) for p in renders],
        "output_dir": os.path.abspath(outdir),
        "duration_s": round(time.time() - t0, 2),
    }
    if photos:
        report["photos"] = {k: [os.path.abspath(p) for p in v] if isinstance(v, list)
                            else os.path.abspath(v)
                            for k, v in photos.items()}
    if game_pack:
        report["game_ready"] = game_pack
    with open(os.path.join(outdir, "report.json"), "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    if not quiet:
        dims = " × ".join(f"{d * 100:.0f}cm" for d in stats["dims_m"])
        wt = "OK" if checks.get("watertight") else "NON ÉTANCHE"
        print(f"▶ {recipe_name}  ({stats['parts']} pièces, {stats['triangles']} tris, {dims})")
        print(f"  étanchéité : {wt} | impression : {'OK' if printable else 'à vérifier'}")
        for k, p in files.items():
            print(f"  {k.upper():4s} → {os.path.relpath(p)}")
        for p in renders:
            print(f"  PNG  → {os.path.relpath(p)}")
        print(f"  durée : {report['duration_s']}s")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="3d-forge : génération 3D paramétrique")
    ap.add_argument("recipe", nargs="?", help="nom de recette (voir --list)")
    ap.add_argument("--set", nargs="*", default=[], metavar="CLE=VALEUR",
                    help="surcharges de paramètres")
    ap.add_argument("--json", help="fichier JSON de surcharges de paramètres")
    ap.add_argument("-f", "--formats", nargs="*", default=["glb", "stl"],
                    choices=VALID_FORMATS, help="formats d'export")
    ap.add_argument("-o", "--out", default=os.path.join(os.getcwd(), "out"),
                    help="répertoire de sortie")
    ap.add_argument("--views", nargs="*", default=list(DEFAULT_VIEWS),
                    choices=list(renderer.DEFAULT_VIEWS), help="vues à rendre")
    ap.add_argument("--size", type=int, default=1024, help="taille PNG")
    ap.add_argument("-q", "--quality", type=_parse_quality, default=1.0,
                    help="densité de maillage (0.5 rapide, 2 fin, ou low/medium/high/ultra)")
    ap.add_argument("--render", dest="render_engine",
                    choices=["auto", "numpy", "cycles"], default="auto",
                    help="moteur de rendu : auto (GGX+HDRI+SSAO), cycles (Blender headless)")
    ap.add_argument("--texture-ai", dest="texture_ai", default=None,
                    help="JSON de tuiles matière GPU datacenter à cuire dans l'atlas UV du .glb")
    ap.add_argument("--game-ready", dest="game_ready", action="store_true",
                    help="Génère le pack AAA complet (High->Low Normal Bake, LOD0/1/2, ORM/MaskMap/DirectX, UCX colliders, Sockets)")
    ap.add_argument("--engine", dest="game_engine",
                    choices=["roblox_unreal", "roblox", "unreal", "unity", "godot", "gltf", "all"],
                    default="roblox_unreal",
                    help="Profil moteur cible pour --game-ready (défaut: roblox_unreal = Roblox Studio + Unreal 5)")
    ap.add_argument("--lod0-tris", dest="lod0_tris", type=int, default=3200,
                    help="Budget triangles cible du LOD0 en mode --game-ready (< 10 000 tris Roblox Studio)")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--faces", choices=["all"], default=None,
                    help="all = photos des 6 faces + turntable en plus des vues")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-preview", action="store_true",
                    help="ne pas générer la preview.html interactive")
    ap.add_argument("--list", action="store_true", help="lister les recettes")
    ap.add_argument("--markdown", action="store_true",
                    help="avec --list : table markdown (source de references/recipes.md, "
                         "vérifiée en CI contre le registre)")
    args = ap.parse_args(argv)

    if args.list or not args.recipe:
        rows = catalog()
        if args.markdown:
            print(f"<!-- GENERATED by `python3 scripts/generate.py --list --markdown` "
                  f"({len(rows)} recettes) — ne pas éditer à la main -->")
            print()
            print("| recette | module | paramètres | défauts |")
            print("|---|---|---|---|")
            for name, meta in rows.items():
                pdesc = ", ".join(
                    f"`{p['name']}`" + (f" ∈ {p['choices']}" if p.get("choices") else "")
                    for p in meta["info"]) or "—"
                defs = json.dumps(meta["defaults"], ensure_ascii=False)
                print(f"| `{name}` | {meta['module']} | {pdesc} | `{defs}` |")
            return 0
        print(f"{len(rows)} recettes disponibles :\n")
        for name, meta in rows.items():
            pdesc = ", ".join(
                f"{p['name']}" + (f"∈{p['choices']}" if p.get("choices") else "")
                for p in meta["info"])
            print(f"  {name:12s} [{meta['module']:10s}] {pdesc}")
            print(f"  {'':12s} défauts : {json.dumps(meta['defaults'], ensure_ascii=False)}")
        return 0

    params = coerce_params(args.recipe, args.set, args.json)
    report = run(args.recipe, params, args.formats, args.out, args.views,
                 args.size, args.quality, render=not args.no_render,
                 quiet=args.quiet, faces_all=(args.faces == "all"),
                 render_engine=args.render_engine, texture_ai=args.texture_ai,
                 game_ready_mode=args.game_ready, game_engine=args.game_engine,
                 lod0_tris=args.lod0_tris)
    if report and not args.no_preview:
        try:
            import preview
            glb = (report.get("files") or {}).get("glb")
            glb_path = glb["path"] if isinstance(glb, dict) else glb
            p = preview.build_preview(report["output_dir"],
                                      title=str(args.recipe),
                                      glb=glb_path, report=report)
            if p and not args.quiet:
                print(f"  preview → {p}")
        except Exception as e:
            if not args.quiet:
                print(f"[preview] échec ({e}) — génération conservée", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
