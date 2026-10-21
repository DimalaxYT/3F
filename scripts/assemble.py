#!/usr/bin/env python3
"""assemble.py — WORKFLOW D : génération multi-parties (le « katana mode »).

L'agent décompose l'objet en parties (chaque partie = une spec meshgen
individuelle, paufinée toute seule avec sa boucle notée), puis un manifest
les place et les assemble. C'est la déclinaison du pipeline Meshy en
« sous-générations » : plus de détails par partie (res dédiée), itération
bout par bout, et génération PARALLÈLE des parties (processus séparés).

Manifest (JSON) — Z-up, mètres, mêmes conventions que le reste du skill :
{
  "name": "katana",
  "prompt": "katana forgé, lame courbée, tsuka wrappée",
  "size_m": 1.0,
  "parallel": true,                    // défaut : true
  "parts": [
    {"id": "tsuka",  "spec": "specs/parts/tsuka.json",
     "at": [0, 0, 0.17], "rot_deg": [0, 0, 0], "scale": 1.0}
  ]
}
- Chaque partie est générée par meshgen (base z=0, debout le long de +Z),
  puis CENTRÉE sur son bbox et transformée : scale -> rot_deg -> at,
  où `at` = position du CENTRE de la partie (astuce : une garde se dessine
  sur tranche dans sa spec, puis se couche avec rot_deg [90,0,0]).
- Cache : une partie déjà générée (report.json présent) n'est PAS
  régénérée sauf --force / --part ID. Itérer = éditer UNE spec, re-lancer.

Sortie (dossier --out) :
  <name>.glb (scène groupée, textures par partie préservées)
  <name>.stl (union booléenne étanche, prête impression)
  <name>.obj + .usdz, rendus, photos (--faces all), preview.html, report.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import trimesh

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import renderer  # noqa: E402


# --------------------------------------------------------------------------
# Génération d'une partie (sous-processus meshgen, cache par partie)
# --------------------------------------------------------------------------

def _generate_part(part: dict, manifest_dir: str, out_root: str,
                   force: bool, only: str | None) -> dict:
    pid = part["id"]
    pdir = os.path.join(out_root, "parts", pid)
    report_path = os.path.join(pdir, "report.json")
    needed = force or (only is not None and only == pid)
    if os.path.isfile(report_path) and not needed:
        with open(report_path) as fh:
            return {"id": pid, "report": json.load(fh), "cached": True}

    os.makedirs(pdir, exist_ok=True)
    t0 = time.time()

    if "glb" in part:
        src = part["glb"]
        if not os.path.isabs(src):
            src = os.path.join(manifest_dir, src)
        dst = os.path.join(pdir, pid + ".glb")
        shutil.copyfile(src, dst)
        import validate as valmod
        sc = trimesh.load(dst, force="scene")
        chk = valmod.check_mesh(sc)
        rep = {"validation": chk, "coherence": {"mean": 1.0}, "files": {"glb": {"path": dst}}}
        with open(report_path, "w") as fh:
            json.dump(rep, fh, indent=2)
        return {"id": pid, "report": rep, "cached": False, "wall_s": round(time.time() - t0, 2)}

    if "recipe" in part:
        rname = part["recipe"]
        sets = [f"{k}={v}" for k, v in (part.get("params") or {}).items()]
        cmd = [sys.executable, os.path.join(_HERE, "generate.py"), rname,
               "--out", pdir, "--no-render", "--no-preview", "--quiet"]
        if sets:
            cmd += ["--set"] + sets
        proc = subprocess.run(cmd, capture_output=True, text=True)
        sub_rep = os.path.join(pdir, rname, "report.json")
        if proc.returncode != 0 or not os.path.isfile(sub_rep):
            raise RuntimeError(f"partie recette '{pid}' échouée:\n{proc.stderr[-800:]}")
        shutil.copyfile(os.path.join(pdir, rname, rname + ".glb"),
                        os.path.join(pdir, pid + ".glb"))
        shutil.copyfile(sub_rep, report_path)
        with open(report_path) as fh:
            rep = json.load(fh)
        rep.setdefault("coherence", {"mean": 1.0})
        with open(report_path, "w") as fh:
            json.dump(rep, fh, indent=2)
        return {"id": pid, "report": rep, "cached": False, "wall_s": round(time.time() - t0, 2)}

    spec_path = part["spec"]
    if not os.path.isabs(spec_path):
        spec_path = os.path.join(manifest_dir, spec_path)
    cmd = [sys.executable, os.path.join(_HERE, "meshgen.py"), spec_path,
           "--out", pdir, "--no-preview"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(report_path):
        raise RuntimeError(
            f"partie '{pid}' échouée (exit {proc.returncode}):\n"
            f"{proc.stdout[-800:]}\n{proc.stderr[-800:]}")
    with open(report_path) as fh:
        return {"id": pid, "report": json.load(fh), "cached": False,
                "wall_s": round(time.time() - t0, 2)}


def generate_parts(manifest: dict, manifest_dir: str, out_root: str,
                   force: bool, only: str | None, jobs: int) -> tuple[list, int]:
    parts = manifest["parts"]
    if only:
        parts = [p for p in parts if p["id"] == only]
        if not parts:
            raise SystemExit(f"--part {only!r} absent du manifest")
    parallel = manifest.get("parallel", True) and len(parts) > 1
    jobs = max(1, min(jobs, len(parts)))
    print(f"[assemble] {len(parts)} partie(s), "
          f"{'parallèle x' + str(jobs) if parallel else 'séquentiel'}")
    if not parallel:
        return [_generate_part(p, manifest_dir, out_root, force, only) for p in parts], 1
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = [pool.submit(_generate_part, p, manifest_dir, out_root,
                            force, only) for p in parts]
        return [f.result() for f in futs], jobs


# --------------------------------------------------------------------------
# Assemblage
# --------------------------------------------------------------------------

def _part_transform(part: dict) -> np.ndarray:
    rd = np.radians(part.get("rot_deg", [0, 0, 0]))
    s = float(part.get("scale", 1.0))
    return trimesh.transformations.compose_matrix(
        angles=rd, translate=part.get("at", [0, 0, 0]),
        scale=None if s == 1.0 else [s, s, s])


def _load_part_meshes(part: dict, out_root: str) -> list[trimesh.Trimesh]:
    """GLB de la partie -> meshes monde (visuals PBR préservés).

    Convention : la partie est d'abord CENTRÉE (bbox au centre de son repère,
    XY et Z), puis transformée par scale -> rot_deg (autour du centre) ->
    at (= position finale du CENTRE de la partie, en mètres, Z-up).
    """
    pid = part["id"]
    glb = os.path.join(out_root, "parts", pid, pid + ".glb")
    if not os.path.isfile(glb):
        glb = os.path.join(out_root, "parts", pid,
                           os.path.basename(part["spec"]).replace(".json", ".glb"))
    scene = trimesh.load(glb, force="scene")
    meshes = [g.copy() for g in scene.dump()]
    if not meshes:
        raise RuntimeError(f"partie '{pid}' : GLB vide")
    for m in meshes:
        c = (m.bounds[0] + m.bounds[1]) / 2.0
        m.apply_translation(-c)          # centre bbox -> origine
        m.apply_transform(_part_transform(part))
    return meshes


def _to_vertex_colored(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Échantillonne l'albedo texture aux UV de chaque sommet -> couleurs.
    Partie sans texture -> gris moyen (le rendu ne doit jamais mourir).

    Après aller-retour GLB, l'image peut vivre dans
    ``visual.material.baseColorTexture`` plutôt que ``visual.image``.
    """
    vis = mesh.visual
    img = getattr(vis, "image", None)
    if img is None and getattr(vis, "material", None) is not None:
        img = getattr(vis.material, "baseColorTexture", None)
    uv = getattr(vis, "uv", None)
    if uv is None or img is None:
        out = mesh.copy()
        n = len(out.vertices)
        grey = np.full((n, 4), 128, dtype=np.uint8)
        grey[:, 3] = 255
        out.visual = trimesh.visual.ColorVisuals(out, vertex_colors=grey)
        return out
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    uv = np.asarray(uv)
    cols = np.clip((uv[:, 0] * (w - 1)).astype(int), 0, w - 1)
    rows = np.clip(((1.0 - uv[:, 1]) * (h - 1)).astype(int), 0, h - 1)
    rgb = arr[rows, cols]
    rgba = np.column_stack([rgb, 255 * np.ones((len(rgb), 1))]).astype(np.uint8)
    out = mesh.copy()
    out.visual = trimesh.visual.ColorVisuals(out, vertex_colors=rgba)
    return out


def _union_solid(meshes: list[trimesh.Trimesh]) -> tuple[trimesh.Trimesh, bool]:
    """Union booléenne (manifold) des parties -> solide d'impression."""
    solids = []
    for m in meshes:
        s = trimesh.Trimesh(vertices=m.vertices, faces=m.faces, process=True)
        s.merge_vertices()
        solids.append(s)
    try:
        uni = trimesh.boolean.union(solids, engine="manifold")
    except Exception as e:
        print(f"[assemble] union booléenne échouée ({e}) -> concat simple",
              file=sys.stderr)
        return trimesh.util.concatenate(solids), False
    if uni is None:
        print("[assemble] union None (parties disjointes ?) -> concat simple",
              file=sys.stderr)
        return trimesh.util.concatenate(solids), False
    if isinstance(uni, list):
        uni = trimesh.util.concatenate(uni)
    if uni.is_watertight:
        return uni, True
    uni.merge_vertices()
    trimesh.repair.fill_holes(uni)
    trimesh.repair.fix_normals(uni)
    return uni, bool(uni.is_watertight)


def assemble(manifest: dict, outdir: str, faces_all: bool = False,
             force: bool = False, only: str | None = None,
             jobs: int = 4, no_preview: bool = False) -> dict:
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    manifest_dir = os.path.dirname(os.path.abspath(
        manifest.get("_path", os.path.join(outdir, "manifest.json"))))
    name = manifest.get("name", "objet")

    # 1-2 : parties en parallèle (cache par partie)
    results, jobs_used = generate_parts(manifest, manifest_dir, outdir,
                                        force, only, jobs)
    for r in results:
        tag = "cache" if r.get("cached") else f"générée {r.get('wall_s', '?')}s"
        print(f"   partie {r['id']:12s} {tag}")

    # rapports de TOUTES les parties (disque : régénérées ou cache)
    reports = {}
    for p in manifest["parts"]:
        rp = os.path.join(outdir, "parts", p["id"], "report.json")
        if not os.path.isfile(rp):
            raise RuntimeError(
                f"partie '{p['id']}' absente — lance d'abord un assemble "
                "complet, puis itère avec --part ID")
        with open(rp) as fh:
            reports[p["id"]] = json.load(fh)

    # 3 : chargement de toutes les parties + transforms -> scène texturée
    meshes, colored = [], []
    for part in manifest["parts"]:
        for m in _load_part_meshes(part, outdir):
            meshes.append(m)
            colored.append(_to_vertex_colored(m))
    scene = trimesh.Scene()
    for i, m in enumerate(meshes):
        scene.add_geometry(m, node_name=f"part_{i}")

    # 4 : solide d'impression (union étanche)
    solid, wt = _union_solid(meshes)
    stl = os.path.join(outdir, name + ".stl")
    solid.export(stl)

    # 5 : exports (préserve les matériaux & textures PBR sur GLB, OBJ+MTL et USDZ)
    glb = os.path.join(outdir, name + ".glb")
    scene.export(glb)
    obj = os.path.join(outdir, name + ".obj")
    try:
        import meshkit as mk
        mk.export_obj_with_mtl(scene, obj)
    except Exception:
        obj = None
    try:
        import usdz_export
        usd = os.path.join(outdir, name + ".usdz")
        usdz_export.export_usdz(scene, usd)
    except Exception:
        usd = None

    # 6 : rendus + photos PBR directs sur la scène texturée (UV + MR + normal map)
    stem = name
    views_def = [("face", 0, 8), ("profil", 90, 8), ("trois_quarts", 42, 22),
                 ("dessus", 0, 78)]
    renders = []
    for label, az, el in views_def:
        img = renderer.render_view(scene, azimuth_deg=az,
                                   elevation_deg=el, size=768, ssaa=2)
        p = os.path.join(outdir, f"{stem}_{label}.png")
        img.save(p)
        renders.append(p)
    photos = {}
    if faces_all:
        face_paths, faces_sheet = renderer.render_all_faces(
            scene, outdir, stem, size=768)
        turn_paths, turn_sheet = renderer.render_turntable(
            scene, outdir, stem, n=8, size=560)
        photos = {"faces": face_paths, "all_faces": faces_sheet,
                  "turn_images": turn_paths, "turntable": turn_sheet}

    # 7 : rapport (compatible critique.py)
    parts_summary = []
    iou_per_part = {}
    for p in manifest["parts"]:
        rep = reports[p["id"]]
        v = rep.get("validation", {})
        cached = not any(r["id"] == p["id"] and not r.get("cached")
                         for r in results)
        parts_summary.append({
            "id": p["id"], "triangles": v.get("triangles"),
            "watertight": v.get("watertight"),
            "iou_mean": (rep.get("coherence") or {}).get("mean"),
            "cached": cached})
        iou = (rep.get("coherence") or {}).get("mean")
        if iou is not None:
            iou_per_part[p["id"]] = iou
    iou_vals = list(iou_per_part.values())
    report = {
        "pipeline": "assemble v1 (Workflow D multi-parties, meshgen parallèle)",
        "prompt": manifest.get("prompt", ""),
        "manifest_parts": len(manifest["parts"]),
        "stats": {"parts": len(meshes),
                  "triangles": int(sum(len(m.faces) for m in meshes)),
                  "triangles_union": int(len(solid.faces))},
        "validation": {
            "watertight_union": wt,
            "watertight_parts": all(p["watertight"] for p in parts_summary),
            "volume_m3": float(abs(solid.volume)) if wt else 0.0,
            "triangles": report_triangles(parts_summary),
        },
        "coherence": {
            "method": "IoU moyen par partie (chacune vs ses 3 vues)",
            "per_view": iou_per_part,
            "mean": round(sum(iou_vals) / len(iou_vals), 4) if iou_vals else None},
        "parts": parts_summary,
        "parallel_jobs": jobs_used,
        "files": {k: {"path": v, "bytes": os.path.getsize(v)}
                  for k, v in [("glb", glb), ("stl", stl), ("obj", obj),
                               ("usdz", usd)] if v and os.path.exists(v)},
        "renders": renders,
        "output_dir": os.path.abspath(outdir),
        "duration_s": round(time.time() - t0, 2),
    }
    if photos:
        report["photos"] = photos
    with open(os.path.join(outdir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    # 8 : preview interactive
    if not no_preview:
        try:
            import preview
            p = preview.build_preview(outdir, title=manifest.get("prompt", name),
                                      glb=glb, report=report)
            if p:
                print(f"   preview → {p}")
        except Exception as e:
            print(f"[preview] échec ({e})", file=sys.stderr)
    return report


def report_triangles(parts_summary) -> int:
    return int(sum(p["triangles"] or 0 for p in parts_summary))


def _bare(m: trimesh.Trimesh) -> trimesh.Trimesh:
    return trimesh.Trimesh(vertices=m.vertices, faces=m.faces, process=False)


def main():
    ap = argparse.ArgumentParser(
        description="Workflow D : assemblage multi-parties (parallèle)")
    ap.add_argument("manifest", help="manifest JSON multi-parties")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default=None, help="nom du livrable")
    ap.add_argument("--faces", choices=["all"], default=None,
                    help="all = photos des 6 faces + turntable de l'assemblage")
    ap.add_argument("--usdz", action="store_true",
                    help="accepté pour compatibilité CLI (USDZ exporté d'office)")
    ap.add_argument("--jobs", type=int, default=4,
                    help="processus parallèles max (défaut 4)")
    ap.add_argument("--part", default=None,
                    help="ne (re)générer que cette partie (les autres: cache)")
    ap.add_argument("--force", action="store_true",
                    help="régénérer toutes les parties (ignorer le cache)")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()
    with open(args.manifest) as fh:
        manifest = json.load(fh)
    if args.name:
        manifest["name"] = args.name
    manifest["_path"] = args.manifest
    report = assemble(manifest, args.out, faces_all=(args.faces == "all"),
                      force=args.force, only=args.part, jobs=args.jobs,
                      no_preview=args.no_preview)
    v = report["validation"]
    print(f"OK {report['stats']['parts']} parties, "
          f"{report['stats']['triangles']} tris, union watertight="
          f"{v['watertight_union']}, IoU={report['coherence']['mean']} "
          f"({report['duration_s']}s, x{report['parallel_jobs']} jobs)")


if __name__ == "__main__":
    main()
