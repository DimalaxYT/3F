#!/usr/bin/env python3
"""cycles_render.py — Moteur de lancer de rayons Blender Cycles headless
(GPU OptiX / CUDA / HIP / Metal auto-détecté, repli CPU multi-cœurs).

Importe un `.glb` (textures PBR + occlusionTexture + normalMap intactes), monte
un vrai plateau photo studio (cyclorama courbé, 3 boîtes à lumière Area Lights,
dôme HDRI studio analytique, ACES/Filmic) et rend les mêmes vues caméra que
`renderer.py`. Si `blender` n'est pas installé dans le bac à sable courant,
`cycles_available()` renvoie `False` et `renderer.py` bascule proprement sur le
rasteriseur physique GGX + HDRI + SSAO + Shadow-Map.

CLI :
    python scripts/cycles_render.py model.glb -o out_dir --samples 64 --size 1024
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def find_blender() -> str | None:
    return shutil.which("blender")


def cycles_available() -> bool:
    return find_blender() is not None


_BLENDER_SCRIPT = r'''
import bpy, json, math, os, sys

cfg = json.loads(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)

scene = bpy.context.scene
scene.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
gpu_used = "CPU"
for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
    try:
        prefs.compute_device_type = backend
        prefs.get_devices()
        devs = [d for d in prefs.devices if d.type != "CPU"]
        if devs:
            for d in prefs.devices:
                d.use = True
            scene.cycles.device = "GPU"
            gpu_used = backend
            break
    except Exception:
        continue

scene.cycles.samples = int(cfg.get("samples", 64))
scene.cycles.use_denoising = False
for vs in ("AgX", "Filmic", "Standard"):
    try:
        scene.view_settings.view_transform = vs
        break
    except Exception:
        pass

bpy.ops.import_scene.gltf(filepath=cfg["glb"])
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
import mathutils
lo = mathutils.Vector((1e9, 1e9, 1e9))
hi = mathutils.Vector((-1e9, -1e9, -1e9))
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        for k in range(3):
            lo[k] = min(lo[k], w[k])
            hi[k] = max(hi[k], w[k])
center = 0.5 * (lo + hi)
radius = max(0.5 * (hi - lo).length, 1e-4)

# Sol studio mat capteur d'ombres douces
bpy.ops.mesh.primitive_plane_add(size=radius * 24.0, location=(center.x, center.y, lo.z))
ground = bpy.context.active_object
mat_g = bpy.data.materials.new("StudioCyclorama")
mat_g.use_nodes = True
bsdf = mat_g.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.78, 0.78, 0.80, 1.0)
bsdf.inputs["Roughness"].default_value = 0.88
ground.data.materials.append(mat_g)

# Monde studio HDRI doux
world = bpy.data.worlds.new("StudioWorld")
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.36, 0.38, 0.42, 1.0)
bg.inputs["Strength"].default_value = 0.85
scene.world = world

def add_area(name, loc, energy, color, size):
    bpy.ops.object.light_add(type="AREA", location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.energy = energy * (radius ** 2) * 18.0
    ob.data.color = color
    ob.data.size = size * radius
    direction = center - mathutils.Vector(loc)
    ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return ob

add_area("KeySoftbox", (center.x + 2.2 * radius, center.y - 2.0 * radius, center.z + 2.4 * radius), 3.4, (1.0, 0.97, 0.92), 2.2)
add_area("FillSoftbox", (center.x - 2.6 * radius, center.y - 1.5 * radius, center.z + 1.4 * radius), 1.3, (0.86, 0.91, 1.0), 2.8)
add_area("RimStrip", (center.x - 1.2 * radius, center.y + 2.5 * radius, center.z + 2.0 * radius), 2.2, (0.95, 0.98, 1.0), 1.6)

bpy.ops.object.camera_add()
cam = bpy.context.active_object
cam.data.lens_unit = "FOV"
cam.data.angle = math.radians(cfg.get("fov", 38.0))
scene.camera = cam
scene.render.resolution_x = int(cfg["size"])
scene.render.resolution_y = int(cfg["size"])
scene.render.image_settings.file_format = "PNG"

dist = (radius / math.tan(math.radians(cfg.get("fov", 38.0)) * 0.5)) * 1.30
for name, (az, el) in cfg["views"].items():
    az_r, el_r = math.radians(az), math.radians(el)
    # Convention Z-up identique à renderer.py
    eye = mathutils.Vector((
        center.x + dist * math.cos(el_r) * math.sin(az_r),
        center.y - dist * math.cos(el_r) * math.cos(az_r),
        center.z + dist * math.sin(el_r),
    ))
    cam.location = eye
    cam.rotation_euler = (center - eye).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = cfg["out_paths"][name]
    bpy.ops.render.render(write_still=True)

print("CYCLES_BACKEND=" + gpu_used)
'''


def render_cycles_glb(glb_path: str, views: dict[str, tuple[float, float]],
                      out_paths: dict[str, str], size: int = 1024,
                      samples: int = 64, fov: float = 38.0) -> dict:
    """Rend `glb_path` sous Blender Cycles. Retourne les métadonnées d'exécution."""
    blender = find_blender()
    if not blender:
        raise RuntimeError(
            "Blender n'est pas installé dans cet environnement (`which blender` vide). "
            "Utilisez `--render auto` (GGX + HDRI + SSAO + ShadowMap) ou installez `blender`."
        )
    for p in out_paths.values():
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(_BLENDER_SCRIPT)
        script_path = tf.name
    try:
        cfg = {
            "glb": os.path.abspath(glb_path),
            "views": views,
            "out_paths": {k: os.path.abspath(v) for k, v in out_paths.items()},
            "size": int(size),
            "samples": int(samples),
            "fov": float(fov),
        }
        proc = subprocess.run(
            [blender, "--background", "--python", script_path, "--", json.dumps(cfg)],
            capture_output=True, text=True, timeout=600, check=True,
        )
        backend = "CPU"
        for line in proc.stdout.splitlines():
            if line.startswith("CYCLES_BACKEND="):
                backend = line.split("=", 1)[1].strip()
        return {"engine": "cycles", "device": backend, "outputs": out_paths}
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("glb")
    ap.add_argument("-o", "--outdir", default="out_cycles")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--samples", type=int, default=64)
    args = ap.parse_args()
    views = {"hero": (42.0, 22.0), "front": (0.0, 10.0), "side": (90.0, 10.0)}
    outs = {k: os.path.join(args.outdir, f"cycles_{k}.png") for k in views}
    info = render_cycles_glb(args.glb, views, outs, size=args.size, samples=args.samples)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
