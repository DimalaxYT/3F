#!/usr/bin/env python3
"""
detect_env.py — auto-détection des capacités de l'environnement.

Décide du pipeline : procédural (toujours dispo) + option neuronale si GPU.
    python detect_env.py [--json] [--fix]

`--fix` imprime la commande pip exacte pour les modules manquants : un agent
peut diagnostiquer ET réparer sans lire le code (toutes les dépendances réelles
des pipelines v4/v5 sont listées, pas seulement le noyau CAO).
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# module importé -> nom PyPI de requirements.txt
DEPS = [
    ("numpy", "numpy"),
    ("trimesh", "trimesh"),
    ("manifold3d", "manifold3d"),
    ("shapely", "shapely"),
    ("PIL", "pillow"),
    ("scipy", "scipy"),
    ("skimage", "scikit-image"),
    ("xatlas", "xatlas"),
    ("fast_simplification", "fast-simplification"),
    ("matplotlib", "matplotlib"),
    ("networkx", "networkx"),
    ("pxr", "usd-core"),
]


def _dep_versions() -> dict:
    out = {}
    for mod, pypi in DEPS:
        try:
            m = __import__(mod)
            out[pypi] = getattr(m, "__version__", True)
            if out[pypi] is True:
                out[pypi] = "ok"
        except ImportError:
            out[pypi] = None
    return out


def detect() -> dict:
    caps: dict = {}
    try:
        import meshkit
        caps = meshkit.capability_report()
    except Exception as exc:  # conteneur vierge : on rapporte au lieu de crasher
        caps = {"meshkit_error": str(exc)}

    deps = _dep_versions()
    caps["deps"] = deps
    missing = [pypi for pypi, v in deps.items() if v is None and pypi != "usd-core"]
    caps["missing"] = missing
    caps["usd_core"] = deps.get("usd-core") is not None

    gpu = {"cuda_available": False, "device": None, "vram_gb": None}
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run([
                "nvidia-smi", "--query-gpu=name,memory.total",
                "--format=csv,noheader"], capture_output=True,
                text=True, timeout=5).stdout.strip()
            if out:
                name, mem = out.splitlines()[0].split(", ")[:2]
                gpu = {"cuda_available": True, "device": name,
                       "vram_gb": float(mem.replace(" MiB", "")) / 1024}
        except Exception:
            pass
    try:
        import torch
        gpu["cuda_available"] = gpu["cuda_available"] or torch.cuda.is_available()
        if torch.cuda.is_available() and gpu["device"] is None:
            gpu["device"] = torch.cuda.get_device_name(0)
            gpu["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1)
    except ImportError:
        pass

    neural_ready = gpu["cuda_available"] and (gpu["vram_gb"] or 0) >= 6
    caps["gpu"] = gpu
    caps["python"] = sys.version.split()[0]
    caps["pipeline"] = {
        "primary": "procedural",
        "neural_fallback": "available" if neural_ready else "disabled",
    }
    if missing:
        caps["pipeline"]["suggestion"] = (
            f"Modules manquants : {', '.join(missing)} — lance "
            "`python3 scripts/detect_env.py --fix`")
    elif neural_ready:
        caps["pipeline"]["suggestion"] = (
            f"GPU détecté ({gpu['device']}, {gpu['vram_gb']} Go) : le fallback neuronal "
            "(TripoSR / Hunyuan3D) peut être activé — voir neural/README.md")
    else:
        caps["pipeline"]["suggestion"] = (
            "Pas de GPU exploitable : pipeline 100% procédural (rapide, étanche, "
            "déterministe). Le catalogue + CSG couvre la majorité des besoins.")
    return caps


def fix_command(missing: list) -> str:
    req = os.path.join(HERE, os.pardir, "requirements.txt")
    if not missing:
        return "# aucune dépendance manquante"
    if len(missing) >= 4:
        return f"python3 -m pip install --break-system-packages -r {os.path.normpath(req)}"
    return "python3 -m pip install --break-system-packages " + " ".join(missing)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="sortie JSON (défaut : déjà JSON)")
    ap.add_argument("--fix", action="store_true",
                    help="imprime la commande pip des modules manquants")
    args = ap.parse_args(argv)

    caps = detect()
    if args.fix:
        print(fix_command(caps.get("missing", [])))
        return 0
    print(json.dumps(caps, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
