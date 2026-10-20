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


def unique_dir(base):
    if not os.path.exists(base):
        return base
    i = 2
    while os.path.exists(f"{base}_{i}"):
        i += 1
    return f"{base}_{i}"


def run(recipe_name, params, formats, outdir, views, size, quality,
        render=True, quiet=False, faces_all=False):
    t0 = time.time()
    mk.set_quality(quality)
    recipe = get_recipe(recipe_name)
    builder = recipe["builder"](**params)
    scene = builder.scene()
    stats = builder.stats()

    solid = None
    if "stl" in formats:
        solid = builder.union_solid()
    checks = valmod.check_mesh(solid if solid is not None else scene)
    printable = checks.get("is_printable", False)

    stem = recipe_name
    outdir = unique_dir(os.path.join(outdir, stem))
    os.makedirs(outdir, exist_ok=True)
    files = {}

    if "glb" in formats:
        p = os.path.join(outdir, stem + ".glb")
        scene.export(p)
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
    ap.add_argument("--formats", nargs="*", default=["glb", "stl"],
                    choices=VALID_FORMATS, help="formats d'export")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "out"),
                    help="répertoire de sortie")
    ap.add_argument("--views", nargs="*", default=list(DEFAULT_VIEWS),
                    choices=list(renderer.DEFAULT_VIEWS), help="vues à rendre")
    ap.add_argument("--size", type=int, default=1024, help="taille PNG")
    ap.add_argument("--quality", type=float, default=1.0,
                    help="densité de maillage (0.5 rapide, 2 fin)")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--faces", choices=["all"], default=None,
                    help="all = photos des 6 faces + turntable en plus des vues")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--list", action="store_true", help="lister les recettes")
    args = ap.parse_args(argv)

    if args.list or not args.recipe:
        rows = catalog()
        print(f"{len(rows)} recettes disponibles :\n")
        for name, meta in rows.items():
            pdesc = ", ".join(
                f"{p['name']}" + (f"∈{p['choices']}" if p.get("choices") else "")
                for p in meta["info"])
            print(f"  {name:12s} [{meta['module']:10s}] {pdesc}")
            print(f"  {'':12s} défauts : {json.dumps(meta['defaults'], ensure_ascii=False)}")
        return 0

    params = coerce_params(args.recipe, args.set, args.json)
    return run(args.recipe, params, args.formats, args.out, args.views,
               args.size, args.quality, render=not args.no_render,
               quiet=args.quiet, faces_all=(args.faces == "all")) and 0 or 0


if __name__ == "__main__":
    sys.exit(main())
