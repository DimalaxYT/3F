#!/usr/bin/env python3
"""
research.py — étape 0 du pipeline 3d-forge : recherche web & détails à respecter.

Zéro API de génération : l'agent utilise SES outils de recherche web pour
trouver de vraies photos de l'objet demandé, télécharge 3 à 6 images de
référence (vues globales + gros plans des détails), puis ce script :

  1. détourne automatiquement les fonds unis / studio (blanc, noir, gris de musée,
     canal alpha) avant de quantifier la palette pour ne JAMAIS polluer les
     couleurs dominantes avec l'arrière-plan ;
  2. analyse chaque image (palette du sujet, luminance, contraste, densité de
     détails, indices de matériaux PBR) ;
  3. produit `reference_sheet.png` — LA planche qui représente les détails à
     respecter (mise en page propre sans débordement de texte entre colonnes) ;
  4. produit `palette_hints.json` & `references.json` (contrat QA Stage 0).
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
THUMB_W, THUMB_H = 340, 240
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# Téléchargement (images publiques trouvées par recherche web de l'agent)
# --------------------------------------------------------------------------- #

def fetch(urls, outdir):
    """Télécharge les URLs d'images dans outdir. Retourne (chemins, erreurs)."""
    os.makedirs(outdir, exist_ok=True)
    saved, errors = [], []
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
                time.sleep(2.5 * attempt)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
            except Exception:
                data = None
            if data is None:
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
        time.sleep(1.2)
        try:
            if not data or len(data) < 3000:
                raise ValueError(f"réponse trop petite ({len(data) if data else 0} o)")
            Image.open(io.BytesIO(data)).load()
            with open(dst, "wb") as f:
                f.write(data)
            if os.path.exists(dst + ".part"):
                os.remove(dst + ".part")
            saved.append(dst)
        except Exception as e:
            if os.path.exists(dst + ".part"):
                os.remove(dst + ".part")
            errors.append((url, str(e)))
    return saved, errors


# --------------------------------------------------------------------------- #
# Détourage automatique des fonds de studio / musée + analyse couleur
# --------------------------------------------------------------------------- #

def foreground_mask(rgba_arr: np.ndarray, tol: float = 0.11) -> tuple[np.ndarray, bool]:
    """Détecte si l'image a un fond uni/transparent (photo studio/catalogue/musée)
    et renvoie `(mask_sujet, bg_filtered)`.

    Sur une texture plein cadre (ex. photo gros plan de rouille ou bois), les
    bords ont une forte variance : on garde alors 100 % des pixels (`False`).
    """
    rgb = rgba_arr[..., :3].astype(np.float64) / 255.0
    alpha = rgba_arr[..., 3].astype(np.float64) / 255.0
    border_a = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    if border_a.mean() < 0.6:
        fg = alpha > 0.5
        if fg.sum() >= 64:
            return fg, True

    border_rgb = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]], axis=0)
    valid_b = border_rgb[border_a > 0.8]
    if len(valid_b) < 16:
        return np.ones(rgb.shape[:2], dtype=bool), False

    bg = np.median(valid_b, axis=0)
    border_spread = np.sqrt(((valid_b - bg) ** 2).sum(-1))
    # Un vrai fond studio a au moins 55 % du cadre très proche de la médiane
    if float((border_spread < tol).mean()) < 0.55:
        return np.ones(rgb.shape[:2], dtype=bool), False

    dist = np.sqrt(((rgb - bg) ** 2).sum(-1))
    is_bg = ndimage.binary_fill_holes(False * dist.astype(bool))  # dummy shape
    # Flood-fill depuis les bords uniquement : ne supprime jamais un reflet interne !
    bg_seed = dist <= tol
    labeled, _ = ndimage.label(bg_seed)
    edge_labels = np.unique(np.concatenate([
        labeled[0, :], labeled[-1, :], labeled[:, 0], labeled[:, -1]
    ]))
    edge_labels = edge_labels[edge_labels > 0]
    is_bg = np.isin(labeled, edge_labels)
    fg = ~is_bg
    # Sécurité : si le flood-fill a mangé presque toute l'image (>97%), on annule
    if fg.sum() < max(64, int(0.025 * fg.size)):
        return np.ones(rgb.shape[:2], dtype=bool), False
    return fg, True


def _kmeans_palette(pixels_rgb01: np.ndarray, k: int = 6):
    """K-means déterministe sur les seuls pixels du premier plan."""
    px = pixels_rgb01
    if len(px) > 16000:
        rs = np.random.RandomState(42)
        px = px[rs.choice(len(px), 16000, replace=False)]
    k = min(k, len(px))
    # Initialisation déterministe étalée par quantiles de luminance (k-means++)
    lum = 0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]
    order_l = np.argsort(lum)
    picks = np.linspace(0, len(px) - 1, k + 2, dtype=int)[1:-1]
    centers = px[order_l[picks]].copy()
    labels = np.zeros(len(px), dtype=np.int64)
    for _ in range(14):
        d2 = ((px[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
        labels = d2.argmin(1)
        for j in range(k):
            m = labels == j
            if m.any():
                centers[j] = px[m].mean(0)
    counts = np.array([(labels == j).sum() for j in range(k)], dtype=np.float64)
    keep = counts > 0
    centers, counts = centers[keep], counts[keep]
    order = np.argsort(-counts)
    return centers[order], counts[order] / max(counts.sum(), 1.0)


def _rgb_to_hsv_arr(rgb):
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    mx, mn = rgb.max(1), rgb.min(1)
    d = mx - mn
    s = np.where(mx > 0, d / np.clip(mx, 1e-9, None), 0)
    v = mx
    h = np.zeros(len(rgb))
    m = d > 1e-9
    rm = m & (mx == r); gm = m & (mx == g); bm = m & (mx == b)
    h[rm] = (60 * ((g - b) / np.clip(d, 1e-9, None)) % 360)[rm]
    h[gm] = (60 * ((b - r) / np.clip(d, 1e-9, None)) + 120)[gm]
    h[bm] = (60 * ((r - g) / np.clip(d, 1e-9, None)) + 240)[bm]
    return h, s, v


def _material_guess(h, s, v):
    if 28 <= h <= 60 and s >= 0.34 and v >= 0.36:
        return "or", 1.0, 0.28
    if 8 <= h <= 36 and 0.28 <= s <= 0.88 and v <= 0.68:
        return "rouille", 0.15, 0.86
    if 12 <= h <= 44 and s >= 0.22 and v < 0.42:
        return "cuir", 0.0, 0.72
    if s <= 0.16 and 0.24 < v < 0.88:
        return "metal", 0.9, 0.38
    if 60 <= h <= 165 and s >= 0.25:
        return "vegetation", 0.0, 0.65
    if v <= 0.24:
        return "ombre_metal", 0.6, 0.5
    return "peinture", 0.05, 0.5


def analyze_image(path, max_side=280, n_colors=6):
    """Analyse une image de référence (avec filtrage du fond studio) → dict."""
    img_rgba = (path.convert("RGBA") if isinstance(path, Image.Image)
                else Image.open(path).convert("RGBA"))
    w0, h0 = img_rgba.size
    small = img_rgba.copy()
    small.thumbnail((max_side, max_side))
    rgba_arr = np.asarray(small)
    arr = rgba_arr[..., :3].astype(np.float64) / 255.0

    fg_mask, bg_removed = foreground_mask(rgba_arr)
    fg_px = arr[fg_mask]
    pal, shares = _kmeans_palette(fg_px, k=n_colors)

    hdeg, sat, val = _rgb_to_hsv_arr(pal)
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    fg_lum = lum[fg_mask]
    gx = np.abs(np.diff(lum, axis=1)).mean()
    gy = np.abs(np.diff(lum, axis=0)).mean()

    clusters = []
    for i in range(len(pal)):
        name, met, rough = _material_guess(hdeg[i], sat[i], val[i])
        clusters.append({
            "hex": "#{:02x}{:02x}{:02x}".format(*(np.round(pal[i] * 255).astype(int))),
            "share": round(float(shares[i]), 3),
            "hsv": [round(float(hdeg[i]), 1), round(float(sat[i]), 2),
                    round(float(val[i]), 2)],
            "material_hint": name,
            "metallic": met,
            "roughness": rough,
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
        "background_filtered": bg_removed,
        "foreground_ratio": round(float(fg_mask.mean()), 3),
        "luminance": round(float(fg_lum.mean()), 3),
        "contrast": round(float(fg_lum.std()), 3),
        "dark_ratio": round(float((fg_lum < 0.25).mean()), 3),
        "light_ratio": round(float((fg_lum > 0.75).mean()), 3),
        "detail_density": round(float((gx + gy) / 2), 4),
        "palette": clusters,
        "material_shares": hints,
    }


def global_palette(analyses, k=5):
    """Fusionne les palettes détourées de toutes les images → k rôles."""
    pool = []
    for i, a in enumerate(analyses):
        for c in a["palette"]:
            # Pénalise les quasi-blancs/noirs extrêmes résiduels d'éclairage studio
            v = c["hsv"][2]
            sat = c["hsv"][1]
            penalty = 0.25 if (v > 0.93 and sat < 0.06) else 1.0
            pool.append({**c, "weight": penalty * c["share"] / math.sqrt(i + 1)})
    pool.sort(key=lambda c: -c["weight"])
    merged = []
    for c in pool:
        r1 = int(c["hex"][1:3], 16); g1 = int(c["hex"][3:5], 16); b1 = int(c["hex"][5:7], 16)
        for m in merged:
            r2 = int(m["hex"][1:3], 16); g2 = int(m["hex"][3:5], 16); b2 = int(m["hex"][5:7], 16)
            if abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2) < 82:
                m["weight"] += c["weight"]
                break
        else:
            merged.append({**c})
    roles = ["principal", "secondaire", "tertiaire", "accent", "sombre"]
    return [
        {
            "role": roles[i] if i < len(roles) else f"extra_{i}",
            "hex": m["hex"],
            "share": round(m["weight"], 3),
            "material_hint": m["material_hint"],
            "metallic": m["metallic"],
            "roughness": m["roughness"],
        }
        for i, m in enumerate(merged[:k])
    ]


# --------------------------------------------------------------------------- #
# Planche « détails à respecter » (sans débordement inter-colonnes)
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


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_px: float) -> str:
    """Tronque proprement avec '…' pour ne jamais déborder sur la colonne voisine."""
    if draw.textlength(text, font=font) <= max_px:
        return text
    s = text
    while len(s) > 3 and draw.textlength(s + "…", font=font) > max_px:
        s = s[:-1]
    return s + "…"


def build_sheet(analyses, out_path, title, details=None, queries=None):
    """Planche de références : vignettes + palettes + détails + requêtes web."""
    details = details or []
    queries = queries or []
    cols = min(3, max(1, len(analyses)))
    rows = math.ceil(len(analyses) / cols)
    pad, head_h, foot_h = 16, 94, 30
    foot_h += 20 * (len(details) + (2 if details else 0))
    foot_h += 20 * (len(queries) + (2 if queries else 0))
    cell_h = THUMB_H + 80
    W = cols * (THUMB_W + pad) + pad
    H = head_h + rows * (cell_h + pad) + foot_h + pad

    sheet = Image.new("RGB", (W, H), (20, 20, 25))
    d = ImageDraw.Draw(sheet)
    f_title = _font(28, bold=True)
    f_sub = _font(14, bold=False)
    f_lab = _font(12, bold=True)
    f_meta = _font(12, bold=False)

    d.text((pad, 14), "DÉTAILS À RESPECTER", fill=(242, 202, 82), font=f_title)
    sub = _fit_text(d, f"{title}  —  {len(analyses)} images de référence (fond studio filtré)",
                    f_sub, W - 2 * pad)
    d.text((pad, 52), sub, fill=(210, 210, 216), font=f_sub)

    for i, a in enumerate(analyses):
        r, c = divmod(i, cols)
        x = pad + c * (THUMB_W + pad)
        y = head_h + r * (cell_h + pad)
        d.rectangle([x, y, x + THUMB_W - 1, y + THUMB_H - 1],
                    fill=(30, 30, 36), outline=(68, 68, 78))
        im = Image.open(a["path"]).convert("RGB")
        im.thumbnail((THUMB_W - 4, THUMB_H - 4))
        sheet.paste(im, (x + (THUMB_W - im.width) // 2,
                         y + (THUMB_H - im.height) // 2))
        tag = " [détouré]" if a.get("background_filtered") else ""
        info = f"{a['file']} · {a['size_px'][0]}×{a['size_px'][1]} · {a['orientation']}{tag}"
        d.text((x, y + THUMB_H + 6),
               _fit_text(d, info, f_lab, THUMB_W - 4),
               fill=(198, 198, 206), font=f_lab)
        for j, cl in enumerate(a["palette"][:6]):
            sw = 34
            sx0 = x + j * (sw + 5)
            d.rectangle([sx0, y + THUMB_H + 26, sx0 + sw, y + THUMB_H + 45],
                        fill=cl["hex"], outline=(58, 58, 64))
        mat = ", ".join(f"{k} {int(round(v * 100))}%"
                        for k, v in sorted(a["material_shares"].items(),
                                           key=lambda kv: -kv[1])[:3])
        d.text((x, y + THUMB_H + 51),
               _fit_text(d, mat, f_meta, THUMB_W - 4),
               fill=(152, 152, 164), font=f_meta)

    fy = head_h + rows * (cell_h + pad) + 8
    f_h = _font(17, bold=True)
    if details:
        d.text((pad, fy), "DÉTAILS IDENTIFIÉS À RESPECTER", fill=(242, 202, 82), font=f_h)
        fy += 26
        for det in details:
            d.ellipse([pad + 2, fy + 5, pad + 8, fy + 11], fill=(242, 202, 82))
            d.text((pad + 16, fy),
                   _fit_text(d, det, f_sub, W - 2 * pad - 20),
                   fill=(228, 228, 234), font=f_sub)
            fy += 20
        fy += 10
    if queries:
        d.text((pad, fy), "RECHERCHES WEB EXÉCUTÉES", fill=(140, 182, 242), font=f_h)
        fy += 26
        for q in queries:
            d.text((pad + 16, fy),
                   _fit_text(d, f"↳ {q}", f_sub, W - 2 * pad - 20),
                   fill=(162, 178, 204), font=f_sub)
            fy += 20

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
    print("  palette_hints.json : " + ", ".join(
        f"{c['role']}={c['hex']}({c['material_hint']})" for c in pal))
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
