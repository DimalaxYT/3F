#!/usr/bin/env python3
"""
research.py — étape 0 du pipeline 3d-forge : recherche web & détails à respecter.

Zéro API de génération : l'agent utilise SES outils de recherche web pour
trouver de vraies photos de l'objet demandé, télécharge 3 à 6 images de
référence (vues globales + gros plans des détails), puis ce script :

  1. analyse chaque image (palette dominante, luminance, contraste,
     saturation, densité de détails, indices de matériaux) ;
  2. produit `reference_sheet.png` — LA planche qui représente les détails
     à respecter (vignettes + palettes + liste des détails) ;
  3. produit `palette_hints.json` — palette prête à coller dans une spec
     meshgen (couleurs + metallic/roughness déduits des clusters) ;
  4. produit `references.json` — requêtes web exécutées, détails listés,
     analyse complète (traçabilité + checklist de QA).

Usage :
    # 1. l'agent fait ses recherches web, puis télécharge les images trouvées
    python research.py fetch --urls URL1 URL2 ... --dir refs_raw/

    # 2. planche de références + indices de palette
    python research.py build --dir refs_raw/ \
        --title "épée médiévale rouillée avec pommeau en or" \
        --out out/epee/references \
        --queries "medieval arming sword museum photo" \
                  "sword gold pommel close up" \
                  "rust metal texture blade" \
        --notes "pommeau disque doré" "gouttière centrale" "rouille par plaques"

    # analyse d'une seule image (debug) : python research.py analyze img.jpg
"""
from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
THUMB_W, THUMB_H = 320, 240
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# Téléchargement (images publiques trouvées par recherche web de l'agent)
# --------------------------------------------------------------------------- #

def fetch(urls, outdir):
    """Télécharge les URLs d'images dans outdir. Retourne (chemins, erreurs).

    Deux tentatives par URL : urllib (stdlib) puis fallback `curl` (certains
    environnements bloquent urllib mais laissent passer curl). Un round de
    retry espacé absorbe les rate-limits (Wikimedia, hotlinkers...).
    """
    import io
    import subprocess

    os.makedirs(outdir, exist_ok=True)
    saved, errors = [], []
    # index de départ : ne jamais écraser un ref_NN d'un appel précédent
    start = -1
    for fn in os.listdir(outdir):
        if fn.startswith("ref_") and fn[4:6].isdigit():
            start = max(start, int(fn[4:6]))
    rounds = 3
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        if ext not in IMG_EXT:
            ext = ".jpg"
        dst = os.path.join(outdir, f"ref_{start + 1 + i:02d}{ext}")
        data = None
        for attempt in range(rounds):
            if attempt:
                time.sleep(2.5 * attempt)      # politesse anti rate-limit
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
            except Exception:
                data = None
            if data is None:                  # fallback curl
                try:
                    p = subprocess.run(
                        ["curl", "-sL", "-A", UA, "--max-time", "30",
                         "-o", dst + ".part", url],
                        capture_output=True, timeout=40)
                    if p.returncode == 0 and os.path.exists(dst + ".part"):
                        with open(dst + ".part", "rb") as f:
                            data = f.read()
                except Exception:
                    data = None
            if data and len(data) >= 3000:
                break
        time.sleep(1.2)                       # politesse entre URLs
        try:
            if not data or len(data) < 3000:  # < 3 ko : probablement une 404 HTML
                raise ValueError(f"réponse trop petite "
                                 f"({len(data) if data else 0} o)")
            Image.open(io.BytesIO(data)).load()
            with open(dst, "wb") as f:
                f.write(data)
            if os.path.exists(dst + ".part"):
                os.remove(dst + ".part")
            saved.append(dst)
        except Exception as e:               # une URL morte ne bloque pas le lot
            if os.path.exists(dst + ".part"):
                os.remove(dst + ".part")
            errors.append((url, str(e)))
    return saved, errors


# --------------------------------------------------------------------------- #
# Analyse d'image
# --------------------------------------------------------------------------- #

def _rgb_to_hsv_arr(rgb):
    """rgb float 0..1 (N,3) → H (0..360), S, V."""
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    mx, mn = rgb.max(1), rgb.min(1)
    d = mx - mn
    s = np.where(mx > 0, d / np.clip(mx, 1e-9, None), 0)
    v = mx
    h = np.zeros(len(rgb))
    m = (d > 1e-9)
    rm = m & (mx == r); gm = m & (mx == g); bm = m & (mx == b)
    h[rm] = (60 * ((g - b) / np.clip(d, 1e-9, None)) % 360)[rm]
    h[gm] = (60 * ((b - r) / np.clip(d, 1e-9, None)) + 120)[gm]
    h[bm] = (60 * ((r - g) / np.clip(d, 1e-9, None)) + 240)[bm]
    return h, s, v


def _material_guess(h, s, v):
    """Indices de matériau depuis H/S/V d'un cluster."""
    if 30 <= h <= 58 and s >= 0.40 and v >= 0.40:
        return "or", 1.0, 0.28
    if 8 <= h <= 36 and 0.28 <= s <= 0.85 and v <= 0.62:
        return "rouille", 0.15, 0.85
    if s <= 0.16 and v >= 0.42:
        return "metal", 0.9, 0.38
    if 12 <= h <= 42 and s >= 0.25 and v < 0.40:
        return "cuir", 0.0, 0.72
    if 60 <= h <= 160 and s >= 0.25:
        return "vegetation", 0.0, 0.65
    if v <= 0.22:
        return "ombre_metal", 0.6, 0.5
    return "peinture", 0.05, 0.5


def analyze_image(path, max_side=280, n_colors=6):
    """Analyse une image de référence → dict structuré."""
    img = Image.open(path).convert("RGB")
    w0, h0 = img.size
    small = img.copy()
    small.thumbnail((max_side, max_side))
    arr = np.asarray(small, dtype=np.float64) / 255.0

    # palette : quantification médiane
    q = small.quantize(colors=n_colors, method=Image.MEDIANCUT)
    pal = np.asarray(q.getpalette(), dtype=np.float64).reshape(-1, 3)[:n_colors] / 255.0
    counts = np.bincount(np.asarray(q).ravel(), minlength=n_colors).astype(np.float64)
    order = np.argsort(-counts)
    counts, pal = counts[order], pal[order]
    shares = counts / max(counts.sum(), 1.0)

    hdeg, sat, val = _rgb_to_hsv_arr(pal)
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    gx = np.abs(np.diff(lum, axis=1)).mean()
    gy = np.abs(np.diff(lum, axis=0)).mean()

    clusters = []
    for i in range(len(pal)):
        name, met, rough = _material_guess(hdeg[i], sat[i], val[i])
        clusters.append({
            "hex": "#{:02x}{:02x}{:02x}".format(*(pal[i] * 255).astype(int)),
            "share": round(float(shares[i]), 3),
            "hsv": [round(float(hdeg[i]), 1), round(float(sat[i]), 2),
                    round(float(val[i]), 2)],
            "material_hint": name,
            "metallic": met, "roughness": rough,
        })

    aspect = w0 / max(h0, 1)
    hints = {}
    for c in clusters:
        hints[c["material_hint"]] = round(
            hints.get(c["material_hint"], 0.0) + c["share"], 3)

    return {
        "file": os.path.basename(path),
        "path": os.path.abspath(path),
        "size_px": [w0, h0],
        "aspect": round(aspect, 3),
        "orientation": ("paysage" if aspect > 1.15 else
                        "portrait" if aspect < 0.87 else "carré"),
        "luminance": round(float(lum.mean()), 3),
        "contrast": round(float(lum.std()), 3),
        "dark_ratio": round(float((lum < 0.25).mean()), 3),
        "light_ratio": round(float((lum > 0.75).mean()), 3),
        "detail_density": round(float((gx + gy) / 2), 4),
        "palette": clusters,
        "material_shares": hints,
    }


def global_palette(analyses, k=5):
    """Fusionne les palettes de toutes les images → k rôles hiérarchisés."""
    pool = []
    for i, a in enumerate(analyses):
        for c in a["palette"]:
            pool.append({**c, "weight": c["share"] / math.sqrt(i + 1)})
    pool.sort(key=lambda c: -c["weight"])
    merged = []
    for c in pool:                            # fusion par distance couleur
        r1 = int(c["hex"][1:3], 16); g1 = int(c["hex"][3:5], 16); b1 = int(c["hex"][5:7], 16)
        for m in merged:
            r2 = int(m["hex"][1:3], 16); g2 = int(m["hex"][3:5], 16); b2 = int(m["hex"][5:7], 16)
            if abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2) < 90:
                m["weight"] += c["weight"]
                break
        else:
            merged.append({**c})
    roles = ["principal", "secondaire", "tertiaire", "accent", "sombre"]
    out = []
    for i, m in enumerate(merged[:k]):
        out.append({
            "role": roles[i] if i < len(roles) else f"extra_{i}",
            "hex": m["hex"], "share": round(m["weight"], 3),
            "material_hint": m["material_hint"],
            "metallic": m["metallic"], "roughness": m["roughness"],
        })
    return out


# --------------------------------------------------------------------------- #
# Planche « détails à respecter »
# --------------------------------------------------------------------------- #

def _font(px=16, bold=True):
    for name in (("DejaVuSans-Bold.ttf", "DejaVuSans.ttf") if bold
                 else ("DejaVuSans.ttf",)):
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(px)
    except TypeError:
        return ImageFont.load_default()


def build_sheet(analyses, out_path, title, details=None, queries=None):
    """Planche de références : vignettes + palettes + détails + requêtes web."""
    details = details or []
    queries = queries or []
    cols = min(3, max(1, len(analyses)))
    rows = math.ceil(len(analyses) / cols)
    pad, head_h, foot_h = 14, 92, 26
    foot_h += 18 * (len(details) + (1 if details else 0))
    foot_h += 18 * (len(queries) + (1 if queries else 0))
    W = cols * (THUMB_W + pad) + pad
    H = head_h + rows * (THUMB_H + 74 + pad) + foot_h + pad

    sheet = Image.new("RGB", (W, H), (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    f_title, f_sub, f_lab = _font(30), _font(15, False), _font(14)

    d.text((pad, 14), "DÉTAILS À RESPECTER", fill=(240, 200, 80), font=f_title)
    sub = f"{title}  —  {len(analyses)} images de référence (recherche web)"
    while d.textlength(sub, font=f_sub) > W - 2 * pad and len(sub) > 8:
        sub = sub[:-2]
    d.text((pad, 52), sub, fill=(210, 210, 215), font=f_sub)

    for i, a in enumerate(analyses):
        r, c = divmod(i, cols)
        x = pad + c * (THUMB_W + pad)
        y = head_h + r * (THUMB_H + 74 + pad)
        im = Image.open(a["path"]).convert("RGB")
        im.thumbnail((THUMB_W, THUMB_H))
        sheet.paste(im, (x + (THUMB_W - im.width) // 2,
                         y + (THUMB_H - im.height) // 2))
        d.rectangle([x, y, x + THUMB_W - 1, y + THUMB_H - 1], outline=(70, 70, 78))
        info = (f"{a['file']}  {a['size_px'][0]}×{a['size_px'][1]}  "
                f"{a['orientation']}  détail {a['detail_density']:.3f}")
        d.text((x, y + THUMB_H + 6), info[:56], fill=(190, 190, 198), font=f_lab)
        for j, cl in enumerate(a["palette"][:6]):
            sw = 30
            d.rectangle([x + j * (sw + 4), y + THUMB_H + 26,
                         x + j * (sw + 4) + sw, y + THUMB_H + 44],
                        fill=cl["hex"], outline=(50, 50, 55))
        mat = ", ".join(f"{k} {int(v * 100)}%" for k, v in
                        sorted(a["material_shares"].items(),
                               key=lambda kv: -kv[1])[:3])
        d.text((x, y + THUMB_H + 50), mat[:56], fill=(150, 150, 160), font=f_lab)

    fy = head_h + rows * (THUMB_H + 74 + pad) + 6
    f_h = _font(18)
    if details:
        d.text((pad, fy), "DÉTAILS IDENTIFIÉS À RESPECTER", fill=(240, 200, 80), font=f_h)
        fy += 26
        for det in details:
            d.ellipse([pad + 2, fy + 6, pad + 8, fy + 12], fill=(240, 200, 80))
            d.text((pad + 16, fy), det, fill=(225, 225, 230), font=f_lab)
            fy += 18
        fy += 8
    if queries:
        d.text((pad, fy), "RECHERCHES WEB EXÉCUTÉES", fill=(140, 180, 240), font=f_h)
        fy += 26
        for q in queries:
            d.text((pad + 16, fy), f"↳ {q}", fill=(160, 175, 200), font=f_lab)
            fy += 18

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.save(out_path)
    return out_path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_build(args):
    files = list(args.refs or [])
    if args.dir:
        for fn in sorted(os.listdir(args.dir)):
            if fn.lower().endswith(IMG_EXT):
                files.append(os.path.join(args.dir, fn))
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        print("Aucune image de référence trouvée (--refs / --dir). "
              "Fais d'abord ta recherche web puis research.py fetch.", file=sys.stderr)
        return 1

    analyses = [analyze_image(f) for f in files]
    pal = global_palette(analyses)
    sheet_path = os.path.join(args.out, "reference_sheet.png")
    build_sheet(analyses, sheet_path, args.title,
                details=args.notes, queries=args.queries)

    hints_path = os.path.join(args.out, "palette_hints.json")
    with open(hints_path, "w") as f:
        json.dump({"title": args.title, "palette": pal}, f, indent=2,
                  ensure_ascii=False)
    refs_path = os.path.join(args.out, "references.json")
    with open(refs_path, "w") as f:
        json.dump({
            "title": args.title,
            "queries": args.queries,
            "details_to_respect": args.notes,
            "n_images": len(analyses),
            "images": analyses,
            "palette_hints": pal,
            "sheet": os.path.abspath(sheet_path),
        }, f, indent=2, ensure_ascii=False)

    print(f"▶ {len(analyses)} images analysées → {os.path.relpath(args.out)}")
    print(f"  planche (détails à respecter) : {os.path.relpath(sheet_path)}")
    print(f"  palette_hints.json : " + ", ".join(
        f"{c['role']}={c['hex']}({c['material_hint']})" for c in pal))
    print("  → colle ces indices dans la palette de ta spec meshgen "
          "et vérifie chaque détail sur les rendus.")
    return 0


def cmd_fetch(args):
    saved, errors = fetch(args.urls, args.dir)
    for p in saved:
        print(f"  ✓ {p}")
    for u, e in errors:
        print(f"  ✗ {u} ({e})", file=sys.stderr)
    print(f"{len(saved)} image(s) téléchargée(s) → {args.dir} "
          f"({len(errors)} échec(s))")
    return 0 if saved else 1


def cmd_analyze(args):
    print(json.dumps(analyze_image(args.image), indent=2, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Recherche web & références (étape 0)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="télécharger les images trouvées par recherche web")
    f.add_argument("--urls", nargs="+", required=True)
    f.add_argument("--dir", default="refs_raw")
    f.set_defaults(fn=cmd_fetch)

    b = sub.add_parser("build", help="planche de références + palette + JSON")
    b.add_argument("--refs", nargs="*", default=[], help="images (sinon --dir)")
    b.add_argument("--dir", default=None, help="dossier d'images téléchargées")
    b.add_argument("--title", required=True, help="objet demandé (prompt)")
    b.add_argument("--out", required=True, help="dossier de sortie")
    b.add_argument("--queries", nargs="*", default=[], help="requêtes web exécutées")
    b.add_argument("--notes", nargs="*", default=[],
                   help="détails à respecter (1 par --notes)")
    b.set_defaults(fn=cmd_build)

    a = sub.add_parser("analyze", help="analyser une seule image (JSON)")
    a.add_argument("image")
    a.set_defaults(fn=cmd_analyze)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
