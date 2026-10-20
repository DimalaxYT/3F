"""
renderer — rendu PNG multi-angles par rasterisation logicielle (numpy), sans GPU.

Caractéristiques :
  * z-buffer, anti-aliasing par sur-échantillonnage (SSAA 2x)
  * ombrage Blinn-Phong à 3 lumières (key / fill / rim) suivant la caméra
  * séparation diffuse/spéculaire pilotée par metallic & roughness (PBR-ish)
  * ombre de contact douce projetée au sol, fond dégradé "studio"
  * transparence pour le verre (alpha blend après les parties opaques)
  * normales interpolées sur les faces douces, facettage conservé sur les arêtes vives
"""
from __future__ import annotations

import math
import os
import numpy as np
import trimesh
from PIL import Image, ImageFilter, ImageDraw, ImageFont

DEFAULT_VIEWS = {
    "front":         (0.0, 14.0),
    "three_quarter": (42.0, 22.0),
    "side":          (90.0, 14.0),
    "top":           (0.0, 70.0),
    "back":          (180.0, 14.0),
    "left":          (270.0, 14.0),
    "bottom":        (0.0, -70.0),
    "back_three_quarter": (137.0, 22.0),
}

# les 6 faces canoniques d'un objet (photos obligatoires avant livraison)
ALL_FACES = [
    ("face",    0.0,   8.0),
    ("dos",     180.0, 8.0),
    ("gauche",  270.0, 8.0),
    ("droite",  90.0,  8.0),
    ("dessus",  0.0,   78.0),
    ("dessous", 0.0,  -78.0),
]

BG_TOP = np.array([0.93, 0.94, 0.96])
BG_BOTTOM = np.array([0.99, 0.99, 0.995])
AMBIENT = 0.33
EXPOSURE = 1.12
ENV_SKY = np.array([1.00, 1.02, 1.06])   # environnement hémisphérique (approx studio)
ENV_GND = np.array([0.30, 0.28, 0.27])


# --------------------------------------------------------------------------- #

def _material_params(mesh: trimesh.Trimesh) -> dict:
    m = getattr(mesh.visual, "material", None)
    col = getattr(m, "baseColorFactor", None)
    col = np.asarray(col, dtype=float) if col is not None else np.array([0.75, 0.75, 0.75, 1.0])
    if col.max() > 1.001:
        col = col / 255.0
    emis = getattr(m, "emissiveFactor", None)
    emis = np.asarray(emis, dtype=float) if emis is not None else np.zeros(3)
    opacity = float(col[3]) if len(col) > 3 else 1.0
    return {
        "color": col[:3].copy(),
        "metallic": float(getattr(m, "metallicFactor", 0.0) or 0.0),
        "roughness": float(getattr(m, "roughnessFactor", 0.5) or 0.5),
        "opacity": opacity,
        "emissive": emis,
    }


def _gather(scene: trimesh.Scene):
    """Liste les parties en coordonnées monde : (verts, vnormals, faces, fnormals, params)."""
    scene = scene.copy()
    parts = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        geom = scene.geometry[gname]
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        g = geom.copy()
        g.apply_transform(T)
        fn = g.face_normals
        vn = g.vertex_normals
        # face "douce" si ses 3 normales sommet pointent comme la normale de face
        dots = np.einsum("fkc,fc->fk", vn[g.faces], fn)
        smooth_mask = (dots > 0.72).all(axis=1)
        mp = _material_params(g)
        # couleurs par sommet (rendu de meshes texturés générés) : albedo = vc
        vc = None
        if getattr(g.visual, "kind", None) == "vertex":
            vca = np.asarray(g.visual.vertex_colors, dtype=float)
            if vca.size:
                if vca.max() > 1.001:
                    vca = vca / 255.0
                vc = vca[:, :3].copy()
                mp["color"] = np.ones(3)
        mp["vcolors"] = vc
        parts.append((g.vertices.copy(), vn.copy(), g.faces.copy(),
                      fn, smooth_mask, mp))
    return parts


def _look_at(eye, target, up=np.array([0.0, 0.0, 1.0])):
    fwd = target - eye
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    if np.linalg.norm(right) < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    right = right / np.linalg.norm(right)
    true_up = np.cross(right, fwd)
    R = np.vstack([right, true_up, -fwd])          # caméra regarde vers -Z
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = -R @ eye
    return M


def _perspective(fov_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fov_deg) / 2)
    M = np.zeros((4, 4))
    M[0, 0] = f / aspect
    M[1, 1] = f
    M[2, 2] = (far + near) / (near - far)
    M[2, 3] = 2 * far * near / (near - far)
    M[3, 2] = -1
    return M


def _bary_fill(px, py, W, H):
    """Pixels du triangle + coordonnées barycentriques. Retourne (xs, ys, b0, b1, b2) ou None."""
    x0 = max(int(np.floor(px.min())), 0)
    x1 = min(int(np.ceil(px.max())), W - 1)
    y0 = max(int(np.floor(py.min())), 0)
    y1 = min(int(np.ceil(py.max())), H - 1)
    if x1 < x0 or y1 < y0:
        return None
    xs = np.arange(x0, x1 + 1) + 0.5
    ys = np.arange(y0, y1 + 1) + 0.5
    gx, gy = np.meshgrid(xs, ys)
    ax, ay = px[0], py[0]
    bx, by = px[1], py[1]
    cx, cy = px[2], py[2]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-12:
        return None
    w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
    w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
    w2 = 1.0 - w0 - w1
    mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
    if not mask.any():
        return None
    return gx[mask].astype(np.int64), gy[mask].astype(np.int64), \
        w0[mask], w1[mask], w2[mask]


def _tone(c):
    """Tone mapping ACES approx (évite les blancs cramés)."""
    return np.clip((c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14), 0.0, 1.0)


def render_view(scene: trimesh.Scene, azimuth_deg=42.0, elevation_deg=22.0,
                size=1024, fov=38.0, ssaa=2, shadow=True) -> Image.Image:
    parts = _gather(scene)
    if not parts:
        raise ValueError("scène vide")

    W = H = int(size * ssaa)
    all_v = np.vstack([p[0] for p in parts])
    lo, hi = all_v.min(0), all_v.max(0)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo) / 2) + 1e-6

    eye = center + radius * 3.1 * np.array([
        np.sin(np.radians(azimuth_deg)) * np.cos(np.radians(elevation_deg)),
        -np.cos(np.radians(azimuth_deg)) * np.cos(np.radians(elevation_deg)),
        np.sin(np.radians(elevation_deg))])
    near, far = radius * 0.1, radius * 12
    V = _look_at(eye, center)
    P = _perspective(fov, W / H, near, far)
    PV = P @ V

    # lumières en espace caméra (suivent la caméra → rendu constant)
    L_key = np.array([0.35, 0.45, 0.83]); L_key /= np.linalg.norm(L_key)
    L_fill = np.array([-0.62, 0.18, 0.55]); L_fill /= np.linalg.norm(L_fill)
    L_rim = np.array([0.05, -0.72, 0.25]); L_rim /= np.linalg.norm(L_rim)
    I = np.array([1.05, 0.38, 0.50])

    img = np.zeros((H, W, 3))
    zbuf = np.full((H, W), np.inf)
    alpha_buf = np.ones((H, W))  # 1 = opaque

    # ---- fond dégradé studio ----
    grad = np.linspace(0, 1, H)[:, None, None]
    bg = (BG_TOP * (1 - grad) + BG_BOTTOM * grad) * np.ones((1, W, 1))
    img[:] = bg

    # ---- ombre de contact : triangles projetés sur le sol (même caméra), floutés ----
    if shadow:
        floor_z = lo[2]
        sh = np.zeros((H, W))
        for verts, _, faces, _, _, _p in parts:
            vf = verts.copy()
            vf[:, 2] = floor_z
            clip_s = (PV @ np.hstack([vf, np.ones((len(vf), 1))]).T).T
            ws = np.clip(clip_s[:, 3:4], 1e-9, None)
            ndc_s = clip_s[:, :3] / ws
            sx = (ndc_s[:, 0] * 0.5 + 0.5) * W
            sy = (1.0 - (ndc_s[:, 1] * 0.5 + 0.5)) * H
            tri_px = np.stack([sx[faces[:, i]] for i in range(3)], axis=1)
            tri_py = np.stack([sy[faces[:, i]] for i in range(3)], axis=1)
            for t in range(len(faces)):
                filled = _bary_fill(tri_px[t], tri_py[t], W, H)
                if filled is not None:
                    xs, ys, *_ = filled
                    sh[ys, xs] = 1.0
        sh_img = Image.fromarray((sh * 255).astype(np.uint8))
        sh_img = sh_img.filter(ImageFilter.GaussianBlur(radius=max(2, W // 70)))
        sh = np.asarray(sh_img, dtype=float) / 255.0
        img *= (1.0 - 0.42 * sh[..., None])

    # ---- passe opaque, puis verre (tri par opacité) ----
    order = sorted(range(len(parts)), key=lambda i: parts[i][5]["opacity"] < 0.999)
    for pi in order:
        verts, vn, faces, fn, smooth_mask, mp = parts[pi]
        glass = mp["opacity"] < 0.999
        N = len(faces)
        vw = np.hstack([verts, np.ones((len(verts), 1))])
        clip = (PV @ vw.T).T
        w_clip = clip[:, 3]
        ok = w_clip > 1e-6                       # frustum : rejette derrière caméra
        ndc = clip[:, :3] / np.clip(w_clip[:, None], 1e-9, None)
        px = (ndc[:, 0] * 0.5 + 0.5) * W
        py = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * H
        depth = w_clip.copy()                    # distance caméra > 0, monotone

        # normales en espace caméra
        Rv = V[:3, :3]
        vn_cam = vn @ Rv.T
        fn_cam = fn @ Rv.T

        vdir_w = eye - verts                     # vecteur sommet → caméra (monde)
        vdir_w = vdir_w / np.clip(np.linalg.norm(vdir_w, axis=1, keepdims=True), 1e-9, None)

        for t in range(N):
            ia, ib, ic = faces[t]
            if not (ok[ia] and ok[ib] and ok[ic]):
                continue
            filled = _bary_fill(np.array([px[ia], px[ib], px[ic]]),
                                np.array([py[ia], py[ib], py[ic]]), W, H)
            if filled is None:
                continue
            xs, ys, w0, w1, w2 = filled
            d = w0 * depth[ia] + w1 * depth[ib] + w2 * depth[ic]
            if glass:
                vis = d < zbuf[ys, xs] + 1e-5
                xs, ys, w0, w1, w2, d = xs[vis], ys[vis], w0[vis], w1[vis], w2[vis], d[vis]
                if len(xs) == 0:
                    continue
                zb_new = zbuf[ys, xs]
            else:
                vis = d < zbuf[ys, xs]
                if not vis.any():
                    continue
                xs, ys, w0, w1, w2, d = xs[vis], ys[vis], w0[vis], w1[vis], w2[vis], d[vis]
                zb_new = d

            if smooth_mask[t]:
                n = (w0[:, None] * vn_cam[ia] + w1[:, None] * vn_cam[ib]
                     + w2[:, None] * vn_cam[ic])
            else:
                n = np.tile(fn_cam[t], (len(xs), 1))
            n /= np.clip(np.linalg.norm(n, axis=1, keepdims=True), 1e-9, None)

            albedo = mp["color"]
            vcols = mp.get("vcolors")
            if vcols is not None:
                albedo = (w0[:, None] * vcols[ia] + w1[:, None] * vcols[ib]
                          + w2[:, None] * vcols[ic])
            metal = mp["metallic"]
            rough = mp["roughness"]
            emis = mp["emissive"]

            # Blinn-Phong : H = normalize(L + V) par lumière
            spec_pow = 2.0 / (rough ** 4 + 1e-3)
            spec_pow = min(512.0, max(8.0, spec_pow))
            vcam = np.array([0.0, 0.0, 1.0])          # caméra vers -Z : V = +Z en espace caméra
            spec_acc = np.zeros((len(xs), 3))
            diff_acc = np.zeros((len(xs), 3))
            for L, inten in zip((L_key, L_fill, L_rim), I):
                ndl = np.clip((n * L).sum(1), 0, None)[:, None]
                hv = L + vcam
                hv /= np.clip(np.linalg.norm(hv), 1e-9, None)
                ndh = np.clip((n * hv).sum(1), 0, None)[:, None]
                diff_acc += inten * ndl
                spec_acc += inten * (ndh ** spec_pow)
            F0 = 0.05 + albedo * metal                 # réflexion de Fresnel approx
            gloss = 0.6 + 2.4 * (1.0 - rough) ** 1.5   # lobe spéculaire renforcé
            # environnement hémisphérique : les métaux réfléchissent le "studio"
            env = ENV_GND + (ENV_SKY - ENV_GND) * (0.5 * (n[:, 2:3] + 1.0))
            spec_pow_broad = max(6.0, spec_pow / 12.0)
            spec_broad = 0.0
            for L in (L_key, L_fill, L_rim):
                hb = L + vcam
                hb /= np.clip(np.linalg.norm(hb), 1e-9, None)
                spec_broad += (np.clip((n * hb).sum(1), 0, None) ** spec_pow_broad)[:, None]
            base = AMBIENT * albedo * (1 - 0.6 * metal)
            col = (base
                   + albedo * (1 - metal) * diff_acc
                   + albedo * metal * env * 0.55
                   + F0 * (gloss * spec_acc + (1 - rough) * 0.35 * spec_broad)
                   + emis)
            col = _tone(col * EXPOSURE)
            if glass:
                col = col * 0.75 + albedo * 0.25       # teinte verre (sans blanchir)
                a = mp["opacity"]
                img[ys, xs] = img[ys, xs] * (1 - a) + col * a
                alpha_buf[ys, xs] *= a
            else:
                img[ys, xs] = col
                zbuf[ys, xs] = zb_new

    # les pixels vides gardent déjà le fond + ombre (img initialisé au bg)

    out = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    out = out.resize((int(size), int(size)), Image.LANCZOS)
    return out


def render_views(scene, outdir, stem, views=None, size=1024, prefix="") -> list:
    """Rend les vues demandées (noms de DEFAULT_VIEWS) → PNG. Retourne les chemins."""
    os.makedirs(outdir, exist_ok=True)
    views = views or ["front", "three_quarter", "top"]
    paths = []
    for v in views:
        if v not in DEFAULT_VIEWS:
            raise ValueError(f"vue inconnue: {v}. disponibles: {list(DEFAULT_VIEWS)}")
        az, el = DEFAULT_VIEWS[v]
        img = render_view(scene, az, el, size=size)
        path = os.path.join(outdir, f"{prefix}{stem}_{v}.png")
        img.save(path)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# Photos de toutes les faces + turntable (livraison "Meshy-like" complète)
# --------------------------------------------------------------------------- #

def contact_sheet(cells, cols=3, pad=10, bg=(24, 24, 28), out_path=None,
                  title=None, title_h=46):
    """Assemble une planche contact : cells = [(PIL.Image, label), ...].

    Retourne l'image de la planche (et l'écrit si out_path est fourni).
    """
    if not cells:
        raise ValueError("aucune cellule pour la planche contact")
    cw = max(im.width for im, _ in cells)
    ch = max(im.height for im, _ in cells) + 26   # bandeau label
    n = len(cells)
    rows = math.ceil(n / cols)
    W = cols * cw + (cols + 1) * pad
    H = rows * ch + (rows + 1) * pad + (title_h if title else 0)

    sheet = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(sheet)
    if title:
        f_t = _font(int(title_h * 0.5))
        tw = draw.textlength(title, font=f_t)
        draw.text(((W - tw) / 2, (title_h - title_h * 0.5) / 2), title,
                  fill=(235, 235, 240), font=f_t)

    for i, (im, label) in enumerate(cells):
        r, c = divmod(i, cols)
        x = pad + c * (cw + pad) + (cw - im.width) // 2
        y = pad + (title_h if title else 0) + r * (ch + pad)
        sheet.paste(im, (x, y))
        f_l = _font(16)
        lw = draw.textlength(label, font=f_l)
        draw.text((x + (im.width - lw) / 2, y + im.height + 4), label,
                  fill=(200, 200, 210), font=f_l)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        sheet.save(out_path)
    return sheet


def _font(px=16):
    """Police truetype si disponible, sinon défaut PIL."""
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(px)
    except TypeError:
        return ImageFont.load_default()


def render_all_faces(scene, outdir, stem, size=768, prefix="",
                     make_sheet=True):
    """Photos des 6 faces canoniques (face/dos/gauche/droite/dessus/dessous).

    Retourne (paths, sheet_path) — sheet_path est None si make_sheet=False.
    """
    os.makedirs(outdir, exist_ok=True)
    paths, cells = [], []
    for label, az, el in ALL_FACES:
        img = render_view(scene, az, el, size=size)
        p = os.path.join(outdir, f"{prefix}{stem}_face_{label}.png")
        img.save(p)
        paths.append(p)
        if make_sheet:
            cells.append((img, label))
    sheet = None
    if make_sheet:
        sheet = os.path.join(outdir, f"{prefix}{stem}_all_faces.png")
        contact_sheet(cells, cols=3, out_path=sheet,
                      title=f"3d-forge — toutes les faces : {stem}")
    return paths, sheet


def render_turntable(scene, outdir, stem, n=8, size=640, elevation=22.0,
                     prefix="", make_sheet=True):
    """Turntable : n rendus équirépartis en azimuth (+ planche contact).

    Retourne (paths, sheet_path).
    """
    os.makedirs(outdir, exist_ok=True)
    paths, cells = [], []
    for i in range(n):
        az = 360.0 * i / n
        img = render_view(scene, az, elevation, size=size)
        p = os.path.join(outdir, f"{prefix}{stem}_turn_{i:02d}.png")
        img.save(p)
        paths.append(p)
        if make_sheet:
            cells.append((img, f"az {az:.0f}°"))
    sheet = None
    if make_sheet:
        sheet = os.path.join(outdir, f"{prefix}{stem}_turntable.png")
        contact_sheet(cells, cols=min(4, n), out_path=sheet,
                      title=f"turntable {n} vues — {stem}")
    return paths, sheet
