#!/usr/bin/env python3
"""
detect_env.py — auto-détection des capacités de l'environnement.

Décide du pipeline : procédural (toujours dispo) + option neuronale si GPU.
    python detect_env.py [--json]
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import meshkit  # noqa: E402


def detect() -> dict:
    caps = meshkit.capability_report()
    try:
        import PIL
        caps["pillow"] = PIL.__version__
    except ImportError:
        caps["pillow"] = None
    try:
        import scipy
        caps["scipy"] = scipy.__version__
    except ImportError:
        caps["scipy"] = None
    try:
        from pxr import Usd  # noqa: F401
        caps["usd_core"] = True
    except ImportError:
        caps["usd_core"] = False

    gpu = {"cuda_available": False, "device": None, "vram_gb": None}
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
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
    if neural_ready:
        caps["pipeline"]["suggestion"] = (
            f"GPU détecté ({gpu['device']}, {gpu['vram_gb']} Go) : le fallback neuronal "
            "(TripoSR / Hunyuan3D) peut être activé — voir neural/README.md")
    else:
        caps["pipeline"]["suggestion"] = (
            "Pas de GPU exploitable : pipeline 100% procédural (rapide, étanche, "
            "déterministe). Le catalogue + CSG couvre la majorité des besoins.")
    return caps


def main():
    caps = detect()
    print(json.dumps(caps, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
