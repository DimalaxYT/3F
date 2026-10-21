#!/usr/bin/env python3
"""
evals/run.py — harnais d'évaluation HEADLESS du skill `3d-forge`.

    python3 evals/run.py                # tous les evals avec un bloc `harness`
    python3 evals/run.py --ids 1,5,8    # sous-ensemble
    python3 evals/run.py --keep         # conserve les dossiers out/ pour inspection

Exécute `harness.cmd` (substitution `{out}` = dossier temporaire, `{outN}` = dossier
du eval N déjà joué) puis vérifie `harness.checks` sur les fichiers produits,
`game_manifest.json` et `gates.json`. Imprime un tableau PASS/FAIL + score et sort
en 1 si un eval échoue : c'est la métrique de progression du skill (CI-able).
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _glb_mimes(path: Path) -> list:
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        return []
    j_len, _ = struct.unpack_from("<II", raw, 12)
    g = json.loads(raw[20:20 + j_len].decode("utf-8"))
    return [im.get("mimeType") for im in g.get("images", [])]


def run_check(check: str, out: Path) -> tuple[bool, str]:
    man_p = out / "game_manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8")) if man_p.is_file() else {}
    if check == "gates_all_pass":
        gp = out / "gates.json"
        if not gp.is_file():
            return False, "gates.json absent"
        g = json.loads(gp.read_text(encoding="utf-8"))
        return bool(g.get("all_pass")), f"{g.get('n_pass')}/{g.get('n_total')}"
    if check == "qa_summary":
        return (out / "qa_summary.md").is_file(), "qa_summary.md"
    if check.startswith("gates_target:"):
        gp = out / "gates.json"
        g = json.loads(gp.read_text(encoding="utf-8")) if gp.is_file() else {}
        return g.get("target") == check.split(":", 1)[1], str(g.get("target"))
    if check == "stl_watertight_manifest":
        return bool(man.get("stl_watertight")), f"stl_watertight={man.get('stl_watertight')}"
    if check == "roblox_png":
        glb = man.get("engine_exports", {}).get("roblox", {}).get("studio_ready_glb_png")
        mimes = _glb_mimes(Path(glb)) if glb else []
        ok = bool(mimes) and all(m == "image/png" for m in mimes)
        return ok, str(sorted(set(mimes)))
    if check.startswith("max_part_tris<="):
        lim = int(check.split("<=")[1])
        val = int(man.get("engine_exports", {}).get("roblox", {}).get("max_part_tris", -1))
        return 0 < val <= lim, f"{val} <= {lim}"
    if check.startswith("preview_size_mb<="):
        lim = float(check.split("<=")[1])
        p = out / "preview.html"
        mb = p.stat().st_size / 1e6 if p.is_file() else -1.0
        return 0 < mb <= lim, f"{mb:.2f} Mo <= {lim}"
    if check.startswith("stl_watertight:"):
        import trimesh
        p = out / check.split(":", 1)[1]
        if not p.is_file():
            return False, f"{p} absent"
        m = trimesh.load(p)
        return bool(m.is_watertight), f"watertight={m.is_watertight}"
    if check.startswith("file:"):
        p = out / check.split(":", 1)[1]
        return p.is_file(), str(check.split(":", 1)[1])
    return False, f"check inconnu : {check}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids", default=None, help="liste d'ids séparés par des virgules")
    ap.add_argument("--keep", action="store_true", help="conserve les out/ temporaires")
    args = ap.parse_args(argv)

    data = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
    evals = [e for e in data["evals"] if e.get("harness")]
    if args.ids:
        want = {int(x) for x in args.ids.split(",")}
        evals = [e for e in evals if e["id"] in want]

    tmp = Path(tempfile.mkdtemp(prefix="3f_evals_"))
    outs: dict[int, Path] = {}
    results = []
    try:
        for e in evals:
            out = tmp / f"eval_{e['id']}"
            out.mkdir(parents=True, exist_ok=True)
            outs[e["id"]] = out
            cmd = []
            for tok in e["harness"]["cmd"]:
                tok = tok.replace("{out}", str(out))
                for pid, pout in outs.items():
                    tok = tok.replace("{out%d}" % pid, str(pout))
                cmd.append(tok)
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            # un eval « audit » (depends_on) vérifie ses checks dans le dossier
            # du eval dont il audite la sortie, pas dans le sien
            dep = e["harness"].get("depends_on")
            checks_dir = outs.get(dep, out) if dep else out
            checks = []
            for chk in e["harness"]["checks"]:
                ok, detail = run_check(chk, checks_dir)
                checks.append((chk, ok, detail))
            ok_cmd = proc.returncode == 0
            all_ok = ok_cmd and all(c[1] for c in checks)
            results.append((e["id"], all_ok, ok_cmd, checks))
            mark = "PASS" if all_ok else "FAIL"
            print(f"[{mark}] eval {e['id']} : cmd exit {proc.returncode}")
            for chk, ok, detail in checks:
                print(f"        {'ok  ' if ok else 'FAIL'} {chk} ({detail})")
            if not ok_cmd:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
                for ln in tail:
                    print(f"        stderr| {ln}")
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"dossiers conservés : {tmp}")

    n_ok = sum(1 for _, ok, _, _ in results if ok)
    print(f"\n== evals : {n_ok}/{len(results)} PASS ==")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
