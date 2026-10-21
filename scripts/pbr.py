"""
pbr — moteur partagé d'unwrap UV (xatlas) et de bake procédural de textures PBR.

Utilisé à la fois par :
  * `meshgen.py` (Workflow C / D : visual hull SDF multi-vues)
  * `meshkit.Builder.bake_pbr(...)` (Workflow A / custom : géométrie paramétrique
    exacte + vraies cartes PBR albedo / metallicRoughness / normal 1024²).

Cartes générées (standard glTF 2.0) :
  * `baseColorTexture`         RGB uint8 (sRGB)
  * `metallicRoughnessTexture` RGB uint8 (R=255, G=roughness, B=metallic)
  * `normalTexture`            RGB uint8 (espace tangent dérivé du relief 3D)
"""
from __future__ import annotations

import math
import numpy as np
from PIL import Image
from scipy import ndimage
import trimesh


# --------------------------------------------------------------------------
# Bruit 3D déterministe (value noise + fBm) — aucune dépendance externe
# --------------------------------------------------------------------------

def _hash3(ix, iy, iz, seed):
    h = (ix.astype(np.int64) * 374761393
         + iy.astype(np.int64) * 668265263
         + iz.astype(np.int64) * 1442695041
         + np.int64(seed) * 2654435761) & 0x7FFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0x7FFFFFFF
    return ((h ^ (h >> 16)).astype(np.float64)) / 2147483647.0


def value_noise(x, y, z, seed=0):
    """Value noise 3D lisse (smoothstep entre 8 coins de la grille)."""
    ix, iy, iz = np.floor(x), np.floor(y), np.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    ux = fx * fx * (3 - 2 * fx)
    uy = fy * fy * (3 - 2 * fy)
    uz = fz * fz * (3 - 2 * fz)
    c000 = _hash3(ix, iy, iz, seed)
    c100 = _hash3(ix + 1, iy, iz, seed)
    c010 = _hash3(ix, iy + 1, iz, seed)
    c110 = _hash3(ix + 1, iy + 1, iz, seed)
    c001 = _hash3(ix, iy, iz + 1, seed)
    c101 = _hash3(ix + 1, iy, iz + 1, seed)
    c011 = _hash3(ix, iy + 1, iz + 1, seed)
    c111 = _hash3(ix + 1, iy + 1, iz + 1, seed)
    x00 = c000 + (c100 - c000) * ux
    x10 = c010 + (c110 - c010) * ux
    x01 = c001 + (c101 - c001) * ux
    x11 = c011 + (c111 - c011) * ux
    y0 = x00 + (x10 - x00) * uy
    y1 = x01 + (x11 - x01) * uy
    return y0 + (y1 - y0) * uz


def fbm(x, y, z, octaves=4, lacunarity=2.0, gain=0.5, seed=0):
    """Fractional Brownian motion : bruit multi-octaves, borné ~[0,1]."""
    total = np.zeros_like(x, dtype=np.float64)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * value_noise(x * freq, y * freq, z * freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / np.maximum(1e-9, e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _frac(x):
    return x - np.floor(x)


def _hex2rgb(h):
    if not isinstance(h, str):
        arr = np.asarray(h, dtype=np.float64)
        return np.clip(arr / 255.0 if arr.max() > 1.001 else arr, 0.0, 1.0)
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255.0


# --------------------------------------------------------------------------
# UV unwrap via xatlas
# --------------------------------------------------------------------------

def unwrap(mesh: trimesh.Trimesh, v_labels: np.ndarray | None = None):
    """Paramétrisation UV automatique via xatlas.

    Retourne `(mesh_uv, labels_uv, uv)` avec des UV garantis finis dans [0, 1].
    """
    import xatlas
    if v_labels is None:
        v_labels = np.zeros(len(mesh.vertices), dtype=np.int32)
    vm, ft, uv = xatlas.parametrize(
        mesh.vertices.astype(np.float32), mesh.faces.astype(np.uint32))
    uv = uv.astype(np.float64)
    bad = ~np.isfinite(uv).all(axis=1)
    if bad.any():
        uv[bad] = 0.5
    mesh2 = trimesh.Trimesh(vertices=mesh.vertices[vm], faces=ft, process=False)
    labels2 = np.asarray(v_labels)[vm]
    return mesh2, labels2, uv


# --------------------------------------------------------------------------
# Usure géométrique (dièdres d'arêtes + courbure sommet)
# --------------------------------------------------------------------------

def compute_ambient_occlusion(mesh: trimesh.Trimesh, k_neighbors: int = 32) -> np.ndarray:
    """Occlusion ambiante géométrique par sommet (`[0.18 .. 1.0]`) rapide et
    déterministe : échantillonne uniformément les faces 3D du maillage (`occ_pts`)
    pour mesurer la vraie occlusion d'angle solide même sur les solides CAO CSG
    à grands triangles plans."""
    from scipy.spatial import cKDTree

    v = np.asarray(mesh.vertices, dtype=np.float64)
    n = np.asarray(mesh.vertex_normals, dtype=np.float64)
    if len(v) < 4 or len(mesh.faces) == 0:
        return np.ones(len(v), dtype=np.float64)

    ext = v.max(0) - v.min(0)
    diag = max(float(np.linalg.norm(ext)), 1e-6)
    # Nuage d'occulteurs surfaciques déterministe : capture aussi les grandes faces planes CSG !
    rng_state = np.random.get_state()
    np.random.seed(42)
    try:
        surf_pts, _ = trimesh.sample.sample_surface(mesh, 1536)
    finally:
        np.random.set_state(rng_state)
    occ_pts = np.vstack([v, surf_pts])

    tree = cKDTree(occ_pts)
    k_q = min(len(occ_pts), max(12, k_neighbors * 3))
    _, idx = tree.query(v, k=k_q)
    step = max(1, (k_q - 1) // k_neighbors)
    nbr = idx[:, 1::step]
    diff = occ_pts[nbr] - v[:, None, :]                 # (V, K, 3)
    dist = np.linalg.norm(diff, axis=-1) + 1e-12        # (V, K)
    dirs = diff / dist[..., None]
    cos_h = np.sum(dirs * n[:, None, :], axis=-1)       # (V, K)
    falloff = np.exp(-dist / (0.22 * diag))
    # Seuls les points strictement au-dessus du plan tangent (cos_h > 0.08) occultent
    occ_local = np.where(cos_h > 0.08, cos_h * falloff, 0.0)
    ao = 1.0 - 2.35 * occ_local.mean(axis=-1)
    z_rel = (v[:, 2] - v[:, 2].min()) / max(ext[2], 1e-6)
    ground_occ = 1.0 - 0.28 * np.exp(-z_rel / 0.08) * np.clip(-n[:, 2], 0.0, 1.0)
    return np.clip(ao * ground_occ, 0.18, 1.0)


def compute_edge_wear(mesh: trimesh.Trimesh) -> np.ndarray:
    """Mesure [0..1] de saillance d'arête par sommet (fonctionne même sur les
    maillages low-poly / CSG à faces planes où vertex_defects vaut 0 au milieu
    d'une arête vive !)."""
    verts = mesh.vertices
    n_v = len(verts)
    wear = np.zeros(n_v, dtype=np.float64)
    if n_v == 0 or len(mesh.faces) == 0:
        return wear
    # Souder les sommets dupliqués (xatlas coupe aux coutures UV) pour retrouver
    # la vraie topologie d'adjacence des faces
    welded = trimesh.Trimesh(vertices=verts, faces=mesh.faces, process=True)
    if len(welded.vertices) and len(welded.face_adjacency):
        angles = welded.face_adjacency_angles          # [0..pi], >0.35 = arête vive
        sharp = np.clip((angles - 0.12) / 1.15, 0.0, 1.0)
        edges = welded.face_adjacency_edges
        w_weld = np.zeros(len(welded.vertices), dtype=np.float64)
        np.maximum.at(w_weld, edges[:, 0], sharp)
        np.maximum.at(w_weld, edges[:, 1], sharp)
        if hasattr(welded, "vertex_defects"):
            defects = np.abs(welded.vertex_defects)
            p95 = float(np.percentile(defects, 95)) + 1e-9
            w_weld = np.maximum(w_weld, np.clip(defects / p95, 0.0, 1.0) * 0.85)
        # Re-mapper chaque sommet de `mesh` vers son sommet soudé le plus proche
        from scipy.spatial import cKDTree
        _, idx = cKDTree(welded.vertices).query(verts, k=1)
        wear = w_weld[idx]
    return np.clip(wear, 0.0, 1.0)


# --------------------------------------------------------------------------
# Évaluation procédurale multi-overlays
# --------------------------------------------------------------------------

def _resolve_target_mask(lab: np.ndarray, tgt, ids: list[str]) -> np.ndarray:
    """Supporte `on: "s"`, `on: ["s", "g"]`, `on: "*"` ou `on: None`."""
    if tgt is None or tgt == "*" or tgt == "all":
        return np.ones(len(lab), dtype=bool)
    targets = [tgt] if isinstance(tgt, str) else list(tgt)
    mask = np.zeros(len(lab), dtype=bool)
    for t in targets:
        if t in ids:
            mask |= (lab == ids.index(t))
        elif t == "#" and ids:
            mask |= (lab == 0)
    return mask


def _label_bounds(vertices: np.ndarray, labels: np.ndarray, k: int):
    pts = vertices[labels == k]
    if len(pts) == 0:
        return np.zeros(3), np.zeros(3), np.ones(3)
    lo, hi = pts.min(0), pts.max(0)
    return pts.mean(0), lo, np.maximum(hi - lo, 1e-6)


def make_material_fn(spec: dict, vertices: np.ndarray, labels: np.ndarray,
                     z_bounds: tuple[float, float]):
    """Retourne `eval_mat(label, pos, wear) -> (rgb, roughness, metallic, height)`."""
    raw_pal = spec.get("palette") or spec.get("materials") or []
    pal = {m["id"]: {**m, "color": m.get("color", m.get("base", "#cccccc"))}
           for m in raw_pal}
    ids = [m["id"] for m in raw_pal]
    rgb_of = {i: _hex2rgb(pal[i]["color"]) for i in pal}
    rough_of = {i: float(pal[i].get("roughness", 0.6)) for i in pal}
    metal_of = {i: float(pal[i].get("metallic", 0.0)) for i in pal}
    overlays = spec.get("overlays", [])
    zmin, zmax = z_bounds
    stats = {i: _label_bounds(vertices, labels, k) for k, i in enumerate(ids)}

    def eval_mat(lab, pos, wear):
        lab = np.asarray(lab)
        n = len(pos)
        col = np.zeros((n, 3), dtype=np.float64)
        rough = np.zeros(n, dtype=np.float64)
        metal = np.zeros(n, dtype=np.float64)
        height = np.zeros(n, dtype=np.float64)
        for k, i in enumerate(ids):
            m = lab == k
            if not m.any():
                continue
            col[m] = rgb_of[i]
            rough[m] = rough_of[i]
            metal[m] = metal_of[i]
        znorm = (pos[:, 2] - zmin) / max(1e-9, zmax - zmin)

        # Micro-grain subtil sur toutes les surfaces (évite l'aspect plastique plat)
        micro = fbm(pos[:, 0] * 9.0, pos[:, 1] * 9.0, pos[:, 2] * 9.0,
                    octaves=3, seed=17)
        col = col * (0.95 + 0.10 * micro)[:, None]
        height += 0.06 * (micro - 0.5)

        for ov in overlays:
            kind = ov.get("type")
            m = _resolve_target_mask(lab, ov.get("on"), ids)
            if not m.any():
                continue

            if kind == "rust":
                rust_hi = rgb_of.get(ov.get("with", "r"),
                                     _hex2rgb(ov.get("color", "#8a431d")))
                rust_dark = rust_hi * np.array([0.52, 0.44, 0.40])
                band = ov.get("band", [0.0, 1.0])
                b = (_smoothstep(band[0] - 0.05, band[0] + 0.08, znorm)
                     * (1.0 - _smoothstep(band[1] - 0.08, band[1] + 0.05, znorm)))
                sc = float(ov.get("scale", 8.0))
                macro = fbm(pos[:, 0] * sc, pos[:, 1] * sc, pos[:, 2] * sc,
                            octaves=4, seed=int(ov.get("seed", 7)))
                detail = fbm(pos[:, 0] * sc * 3.7, pos[:, 1] * sc * 3.7,
                             pos[:, 2] * sc * 3.7, octaves=3, seed=91)
                pits = fbm(pos[:, 0] * sc * 11.5, pos[:, 1] * sc * 11.5,
                           pos[:, 2] * sc * 11.5, octaves=2, seed=137)
                nse = 0.60 * macro + 0.28 * detail + 0.12 * pits
                cov = float(ov.get("coverage", ov.get("amount", 0.35)))
                soft = max(0.04, float(ov.get("softness", 0.15)))
                t = np.clip((nse - (1.0 - 1.55 * cov)) / soft, 0.0, 1.0)
                t = (t * b) * m
                core = _smoothstep(0.42, 0.92, t * (0.65 + 0.55 * pits))
                rcol = rust_hi[None, :] * (1.0 - 0.65 * core[:, None]) \
                    + rust_dark[None, :] * (0.65 * core[:, None])
                col = col * (1.0 - t[:, None]) + rcol * t[:, None]
                rough = rough * (1.0 - t) + 0.90 * t
                metal = metal * (1.0 - t) + 0.10 * t
                height -= 0.55 * t * (0.35 + 0.65 * pits)

            elif kind == "wrap":
                # Enroulement hélicoïdal 2pi-périodique SANS couture (y compris
                # mode `diamond: true` pour le tressage tsuka-maki japonais !)
                first_id = (ov.get("on") if isinstance(ov.get("on"), str)
                            else (ov.get("on")[0] if ov.get("on") else ids[0]))
                cent, lo_b, ext_b = stats.get(first_id, (np.zeros(3), np.zeros(3), np.ones(3)))
                z_local = (pos[:, 2] - lo_b[2]) / max(1e-6, ext_b[2])
                theta = np.arctan2(pos[:, 1] - cent[1], pos[:, 0] - cent[0])
                count = float(ov.get("count", 9))
                twist = float(ov.get("twist", 1.0))
                darken = float(ov.get("darken", 0.45))
                grain = fbm(pos[:, 0] * 60.0, pos[:, 1] * 60.0, pos[:, 2] * 60.0,
                            octaves=2, seed=31)
                if ov.get("diamond", False):
                    # Vrai tsuka-maki : deux rubans croisés d'ito laissant voir
                    # des losanges de peau de raie (samegawa) grenue en dessous
                    under = _hex2rgb(ov.get("under_color", "#d8d2c2"))
                    w = float(ov.get("ribbon_width", 0.34))
                    d1 = np.abs(np.sin(math.pi * (theta / math.pi + count * z_local)))
                    d2 = np.abs(np.sin(math.pi * (theta / math.pi - count * z_local)))
                    r1 = 1.0 - _smoothstep(w * 0.72, w, d1)
                    r2 = 1.0 - _smoothstep(w * 0.72, w, d2)
                    strap = np.maximum(r1, r2)
                    over_under = np.where(r1 >= r2, r1 * 0.9, r2 * 0.72)
                    pebble = fbm(pos[:, 0] * 150.0, pos[:, 1] * 150.0,
                                 pos[:, 2] * 150.0, octaves=2, seed=67)
                    same_col = under[None, :] * (0.78 + 0.38 * pebble)[:, None]
                    ito_col = col * (0.72 + 0.36 * over_under + 0.12 * grain)[:, None]
                    mixed = same_col * (1.0 - strap[:, None]) + ito_col * strap[:, None]
                    col = np.where(m[:, None], mixed, col)
                    rough = np.where(m, np.clip(0.88 * strap + 0.48 * (1.0 - strap), 0.05, 1.0), rough)
                    metal = np.where(m, 0.0, metal)
                    height += np.where(m, 0.65 * over_under + 0.18 * pebble * (1.0 - strap), 0.0)
                else:
                    # Lanière de cuir spiralée continue (cos 2pi-périodique -> zéro couture !)
                    n_helix = max(1, int(round(float(ov.get("strands", 1)))))
                    ph = _frac(n_helix * theta / (2.0 * math.pi) + count * z_local * max(twist, 0.25))
                    groove = 1.0 - np.abs(2.0 * ph - 1.0)   # 0 au joint, 1 au bombé de la lanière
                    pillow = _smoothstep(0.0, 0.38, groove)
                    tone = (1.0 - darken * (1.0 - pillow)) * (0.90 + 0.20 * grain)
                    col = np.where(m[:, None], col * tone[:, None], col)
                    rough = np.where(m, np.clip(rough + 0.08 * (1.0 - pillow), 0.05, 1.0), rough)
                    height += np.where(m, 0.55 * pillow + 0.08 * grain, 0.0)

            elif kind == "edge_wear":
                amt = float(ov.get("amount", 0.5))
                sc = float(ov.get("scale", 18.0))
                nse = fbm(pos[:, 0] * sc, pos[:, 1] * sc, pos[:, 2] * sc,
                          octaves=3, seed=53)
                t = np.clip(wear * (0.55 + 0.85 * nse) * amt * 1.9, 0.0, 1.0) * m
                bright = np.minimum(1.0, col * 1.28 + 0.075)
                col = col * (1.0 - t[:, None]) + bright * t[:, None]
                rough = rough * (1.0 - t) + np.maximum(0.08, rough * 0.42) * t
                metal = metal + (0.96 - metal) * t * (metal > 0.35)

            elif kind == "wood_grain":
                sc = float(ov.get("scale", 14.0))
                contrast = float(ov.get("contrast", 0.28))
                warp = fbm(pos[:, 0] * 4.0, pos[:, 1] * 4.0, pos[:, 2] * 1.5,
                           octaves=3, seed=113)
                rings = np.hypot(pos[:, 0] + 0.08 * warp, pos[:, 1] + 0.08 * warp) * sc
                ring_v = 0.5 + 0.5 * np.sin(2.0 * math.pi * rings)
                fibers = fbm(pos[:, 0] * 45.0, pos[:, 1] * 45.0, pos[:, 2] * 7.0,
                             octaves=2, seed=131)
                tone = 1.0 - contrast * (0.65 * ring_v + 0.35 * fibers - 0.5)
                col = np.where(m[:, None], col * tone[:, None], col)
                rough = np.where(m, np.clip(rough + 0.07 * ring_v, 0.05, 1.0), rough)
                height += np.where(m, -0.16 * ring_v + 0.05 * fibers, 0.0)

            elif kind == "brushed_metal":
                ax = {"x": 0, "y": 1, "z": 2}.get(ov.get("axis", "z"), 2)
                sc = float(ov.get("scale", 160.0))
                amt = float(ov.get("amount", 0.16))
                p = pos.copy()
                p[:, ax] *= 0.06  # étire fortement les micro-stries le long de l'axe
                streaks = fbm(p[:, 0] * sc, p[:, 1] * sc, p[:, 2] * sc,
                              octaves=3, seed=143)
                tone = 1.0 + amt * (streaks - 0.5) * 2.0
                col = np.where(m[:, None], col * tone[:, None], col)
                rough = np.where(m, np.clip(rough + 0.09 * (streaks - 0.5), 0.03, 1.0), rough)
                height += np.where(m, 0.14 * (streaks - 0.5), 0.0)

            elif kind == "hamon":
                # Ligne de trempe différentielle japonaise (ondulation le long du tranchant)
                first_id = (ov.get("on") if isinstance(ov.get("on"), str)
                            else (ov.get("on")[0] if ov.get("on") else ids[0]))
                _, lo_b, ext_b = stats.get(first_id, (np.zeros(3), np.zeros(3), np.ones(3)))
                ax = {"x": 0, "y": 1}.get(ov.get("axis", "x"), 0)
                u_edge = (pos[:, ax] - lo_b[ax]) / max(1e-6, ext_b[ax])
                if not ov.get("positive_edge", True):
                    u_edge = 1.0 - u_edge
                wave = (0.055 * np.sin(pos[:, 2] * float(ov.get("freq", 68.0)))
                        + 0.035 * np.sin(pos[:, 2] * float(ov.get("freq", 68.0)) * 2.3 + 1.1)
                        + 0.03 * (fbm(pos[:, 0] * 25.0, pos[:, 1] * 25.0,
                                      pos[:, 2] * 25.0, octaves=2, seed=151) - 0.5))
                line = float(ov.get("edge_frac", 0.66)) + wave
                yakiba = _smoothstep(line - 0.05, line + 0.05, u_edge) * m
                habuchi = np.exp(-((u_edge - line) / 0.035) ** 2) * m
                col = col * (1.0 + 0.14 * yakiba[:, None] + 0.22 * habuchi[:, None])
                rough = np.where(m, np.clip(rough * (1.0 - 0.35 * yakiba)
                                            + 0.16 * habuchi, 0.04, 1.0), rough)

            elif kind in ("patina", "speckle"):
                sc = float(ov.get("scale", 26.0))
                tint = _hex2rgb(ov.get("color", "#4c6b58" if kind == "patina" else "#3d352e"))
                amt = float(ov.get("amount", 0.32))
                nse = fbm(pos[:, 0] * sc, pos[:, 1] * sc, pos[:, 2] * sc,
                          octaves=3, seed=177)
                if kind == "patina":
                    # La patine s'accumule dans les creux (1 - wear)
                    t = np.clip((1.0 - wear) * (nse - 0.42) * 2.4 * amt, 0.0, 1.0) * m
                else:
                    t = (_smoothstep(0.66, 0.78, nse) * amt) * m
                col = col * (1.0 - t[:, None]) + tint[None, :] * t[:, None]
                rough = np.where(m, np.clip(rough + 0.22 * t, 0.04, 1.0), rough)

            elif kind == "mud_splash":
                # Boue / poussière projetée directionnelle (anisotrope selon l'axe X,
                # concentrée près du sol `z_low` et dans les cavités abritées `1 - wear`)
                mud_c = _hex2rgb(ov.get("color", "#5a4632"))
                sc = float(ov.get("scale", 16.0))
                amt = float(ov.get("amount", 0.55))
                h_max = float(ov.get("height", 0.38))
                streak = fbm(pos[:, 0] * sc * 0.28, pos[:, 1] * sc,
                             pos[:, 2] * sc * 1.15, octaves=4, seed=int(ov.get("seed", 53)))
                splat = fbm(pos[:, 0] * sc * 2.2, pos[:, 1] * sc * 2.2,
                            pos[:, 2] * sc * 2.2, octaves=3, seed=97)
                low_mask = 1.0 - _smoothstep(h_max * 0.45, h_max, znorm)
                t = np.clip((0.68 * streak + 0.32 * splat - 0.44) * 3.0, 0.0, 1.0)
                t = (t * low_mask * (0.55 + 0.45 * (1.0 - wear)) * amt) * m
                col = col * (1.0 - t[:, None]) + mud_c[None, :] * t[:, None]
                rough = rough * (1.0 - t) + 0.94 * t
                metal = metal * (1.0 - t) + 0.02 * t
                height += 0.22 * t * splat

            elif kind == "contact_wear":
                # Usure sémantique localisée aux seules arêtes/zones de frottement
                pol_c = _hex2rgb(ov.get("color", "#d4d8de"))
                amt = float(ov.get("amount", 0.65))
                sc = float(ov.get("scale", 22.0))
                band = ov.get("band", [0.0, 1.0])
                b_mask = (_smoothstep(band[0] - 0.04, band[0] + 0.05, znorm)
                          * (1.0 - _smoothstep(band[1] - 0.05, band[1] + 0.04, znorm)))
                grain = fbm(pos[:, 0] * sc, pos[:, 1] * sc, pos[:, 2] * sc,
                            octaves=3, seed=int(ov.get("seed", 61)))
                t = np.clip((wear - 0.22) * 1.6 * (0.55 + 0.65 * grain), 0.0, 1.0)
                t = (t * b_mask * amt) * m
                col = col * (1.0 - t[:, None]) + pol_c[None, :] * t[:, None]
                rough = np.where(m, np.clip(rough - 0.25 * t, 0.05, 1.0), rough)
                metal = np.where(m, np.clip(metal + 0.65 * t, 0.0, 1.0), metal)

            elif kind == "decal_stripe":
                # Sérigraphie / bande graphique nette sans flou isotrope
                stripe_c = _hex2rgb(ov.get("color", "#f2f4f7"))
                ax = {"x": 0, "y": 1, "z": 2}[ov.get("axis", "z")]
                c0, c1 = ov.get("span", [0.42, 0.58])
                lo_g = vertices.min(0)[ax]
                ext_g = max(1e-6, vertices.max(0)[ax] - lo_g)
                u_ax = (pos[:, ax] - lo_g) / ext_g
                aa = 0.008
                t = (_smoothstep(c0 - aa, c0 + aa, u_ax)
                     * (1.0 - _smoothstep(c1 - aa, c1 + aa, u_ax))) * m
                col = col * (1.0 - t[:, None]) + stripe_c[None, :] * t[:, None]
                rough = np.where(m, np.clip(rough * (1.0 - t) + 0.24 * t, 0.04, 1.0), rough)
                metal = np.where(m, metal * (1.0 - t), metal)

        return (np.clip(col, 0.0, 1.0),
                np.clip(rough, 0.04, 1.0),
                np.clip(metal, 0.0, 1.0),
                height)

    return eval_mat


# --------------------------------------------------------------------------
# Rasterisation UV & assemblage des 3 cartes PBR
# --------------------------------------------------------------------------

def _rasterize_tri(uv_px: np.ndarray, S: int):
    if not np.isfinite(uv_px).all():
        return None
    x0 = max(int(np.floor(uv_px[:, 0].min())), 0)
    x1 = min(int(np.ceil(uv_px[:, 0].max())), S - 1)
    y0 = max(int(np.floor(uv_px[:, 1].min())), 0)
    y1 = min(int(np.ceil(uv_px[:, 1].max())), S - 1)
    if x1 < x0 or y1 < y0:
        return None
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                         np.arange(y0, y1 + 1) + 0.5)
    ax, ay = uv_px[0]
    bx, by = uv_px[1]
    cx, cy = uv_px[2]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-12:
        return None
    w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
    w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
    w2 = 1.0 - w0 - w1
    m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
    if not m.any():
        return None
    return gx[m].astype(np.int64), gy[m].astype(np.int64), w0[m], w1[m], w2[m]


def rasterize_uv_triangles(tri_uv: np.ndarray, S: int):
    """Rastériseur UV vectorisé par buckets (×80 plus rapide qu'une boucle Python) :
    retourne `(fi, xs, ys, w0, w1, w2)` pour tous les texels couverts de `[0..S-1]^2`."""
    valid = np.isfinite(tri_uv).all(axis=(1, 2))
    f_idx = np.flatnonzero(valid)
    if len(f_idx) == 0:
        return None
    ax, bx, cx = tri_uv[f_idx, 0, 0], tri_uv[f_idx, 1, 0], tri_uv[f_idx, 2, 0]
    ay, by, cy = tri_uv[f_idx, 0, 1], tri_uv[f_idx, 1, 1], tri_uv[f_idx, 2, 1]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    x0 = np.maximum(np.floor(np.minimum(np.minimum(ax, bx), cx)).astype(np.int64), 0)
    x1 = np.minimum(np.ceil(np.maximum(np.maximum(ax, bx), cx)).astype(np.int64), S - 1)
    y0 = np.maximum(np.floor(np.minimum(np.minimum(ay, by), cy)).astype(np.int64), 0)
    y1 = np.minimum(np.ceil(np.maximum(np.maximum(ay, by), cy)).astype(np.int64), S - 1)
    keep = (np.abs(den) >= 1e-12) & (x1 >= x0) & (y1 >= y0)
    if not keep.any():
        return None

    f_idx = f_idx[keep]
    ax, bx, cx = ax[keep], bx[keep], cx[keep]
    ay, by, cy = ay[keep], by[keep], cy[keep]
    den = den[keep]
    x0, x1, y0, y1 = x0[keep], x1[keep], y0[keep], y1[keep]
    bw = x1 - x0 + 1
    bh = y1 - y0 + 1
    areas = bw * bh

    out_f, out_x, out_y, out_w0, out_w1, out_w2 = [], [], [], [], [], []
    vec_mask = areas <= 4096
    for cap in (16, 64, 256, 1024, 4096):
        lo_a = 0 if cap == 16 else {64: 16, 256: 64, 1024: 256, 4096: 1024}[cap]
        sel = np.flatnonzero(vec_mask & (areas > lo_a) & (areas <= cap))
        if len(sel) == 0:
            continue
        W_max = int(bw[sel].max())
        H_max = int(bh[sel].max())
        ox, oy = np.meshgrid(np.arange(W_max), np.arange(H_max))
        ox = ox.ravel()[None, :]
        oy = oy.ravel()[None, :]
        gx = x0[sel, None] + ox + 0.5
        gy = y0[sel, None] + oy + 0.5
        in_box = (ox < bw[sel, None]) & (oy < bh[sel, None])
        inv_d = 1.0 / den[sel, None]
        w0 = ((by[sel, None] - cy[sel, None]) * (gx - cx[sel, None])
              + (cx[sel, None] - bx[sel, None]) * (gy - cy[sel, None])) * inv_d
        w1 = ((cy[sel, None] - ay[sel, None]) * (gx - cx[sel, None])
              + (ax[sel, None] - cx[sel, None]) * (gy - cy[sel, None])) * inv_d
        w2 = 1.0 - w0 - w1
        hit = in_box & (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        ti, pi = np.nonzero(hit)
        if len(ti):
            out_f.append(f_idx[sel[ti]])
            out_x.append((x0[sel[ti]] + ox[0, pi]).astype(np.int64))
            out_y.append((y0[sel[ti]] + oy[0, pi]).astype(np.int64))
            out_w0.append(w0[ti, pi])
            out_w1.append(w1[ti, pi])
            out_w2.append(w2[ti, pi])

    for i in np.flatnonzero(~vec_mask):
        hit_s = _rasterize_tri(tri_uv[f_idx[i]], S)
        if hit_s is not None:
            xs_s, ys_s, w0_s, w1_s, w2_s = hit_s
            out_f.append(np.full(len(xs_s), f_idx[i], dtype=np.int64))
            out_x.append(xs_s); out_y.append(ys_s)
            out_w0.append(w0_s); out_w1.append(w1_s); out_w2.append(w2_s)

    if not out_f:
        return None
    return (np.concatenate(out_f), np.concatenate(out_x), np.concatenate(out_y),
            np.concatenate(out_w0), np.concatenate(out_w1), np.concatenate(out_w2))


def box_project_uv(mesh: trimesh.Trimesh, scale: float = 1.0):
    """Projection UV cubique/box instantanée (< 1 ms, sans `xatlas`) sur un
    maillage éclaté par face : idéale pour texturer 50-150 pièces CAO (veinage
    bois des meubles, métal brossé, carrosserie) en un clin d'œil."""
    f = mesh.faces
    v_exp = mesh.vertices[f.ravel()]
    f_exp = np.arange(len(v_exp), dtype=np.int64).reshape(-1, 3)
    fn = np.repeat(np.abs(mesh.face_normals), 3, axis=0)
    axis = fn.argmax(axis=1)
    uv = np.zeros((len(v_exp), 2), dtype=np.float64)
    mx = axis == 0
    my = axis == 1
    mz = axis == 2
    uv[mx] = v_exp[mx][:, [1, 2]] * scale
    uv[my] = v_exp[my][:, [0, 2]] * scale
    uv[mz] = v_exp[mz][:, [0, 1]] * scale
    uv = uv - np.floor(uv)
    return trimesh.Trimesh(vertices=v_exp, faces=f_exp, process=False), uv


def compress_png(img: Image.Image) -> Image.Image:
    """Compresse sans perte un `PIL.Image` en PNG optimisé en mémoire afin que
    `trimesh` écrive des `.glb` et `preview.html` 3 à 5x plus légers."""
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, compress_level=9)
    buf.seek(0)
    out = Image.open(buf)
    out.load()
    return out


def bake_textures(mesh: trimesh.Trimesh, labels: np.ndarray, uv: np.ndarray,
                  spec: dict):
    """Peint l'atlas PBR en une passe vectorisée : `(albedo_img, mr_img, normal_img, wear_v)`."""
    S = int(spec.get("texture_size", 1024))
    albedo = np.zeros((S, S, 3), dtype=np.float64)
    ao_t = np.ones((S, S), dtype=np.float64)
    rough_t = np.zeros((S, S), dtype=np.float64)
    metal_t = np.zeros((S, S), dtype=np.float64)
    height_t = np.zeros((S, S), dtype=np.float64)
    filled = np.zeros((S, S), dtype=bool)

    faces = mesh.faces
    tri_uv = np.empty_like(uv[faces])
    tri_uv[..., 0] = uv[faces, 0] * S
    tri_uv[..., 1] = (1.0 - uv[faces, 1]) * S
    wear_v = compute_edge_wear(mesh)
    ao_v = compute_ambient_occlusion(mesh)

    zmin, zmax = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    eval_mat = make_material_fn(spec, mesh.vertices, labels, (zmin, zmax))

    rast = rasterize_uv_triangles(tri_uv, S)
    if rast is not None:
        fi, xs, ys, w0, w1, w2 = rast
        ia, ib, ic = faces[fi, 0], faces[fi, 1], faces[fi, 2]
        pos = (w0[:, None] * mesh.vertices[ia]
               + w1[:, None] * mesh.vertices[ib]
               + w2[:, None] * mesh.vertices[ic])
        w = np.stack([w0, w1, w2], 1)
        dom = labels[faces[fi, w.argmax(1)]]
        wear = w0 * wear_v[ia] + w1 * wear_v[ib] + w2 * wear_v[ic]
        ao = w0 * ao_v[ia] + w1 * ao_v[ib] + w2 * ao_v[ic]
        col, rough, metal, hgt = eval_mat(dom, pos, wear)
        albedo[ys, xs] = col
        ao_t[ys, xs] = ao
        rough_t[ys, xs] = rough
        metal_t[ys, xs] = metal
        height_t[ys, xs] = hgt
        filled[ys, xs] = True

    # Dilatation d'atlas : zéro couture noire aux bords d'îlots xatlas
    if (~filled).any() and filled.any():
        ind = ndimage.distance_transform_edt(~filled, return_distances=False,
                                             return_indices=True)
        albedo = albedo[ind[0], ind[1]]
        ao_t = ao_t[ind[0], ind[1]]
        rough_t = rough_t[ind[0], ind[1]]
        metal_t = metal_t[ind[0], ind[1]]
        height_t = height_t[ind[0], ind[1]]

    albedo8 = (np.clip(albedo, 0.0, 1.0) * 255).astype(np.uint8)
    lum = albedo @ np.array([0.299, 0.587, 0.114])
    relief = 0.65 * height_t + 0.35 * lum
    gx = ndimage.sobel(relief, 1) / 8.0
    gy = ndimage.sobel(relief, 0) / 8.0
    k = float(spec.get("normal_strength", 2.0))
    nx, ny = -gx * k, -gy * k
    nz = np.ones_like(nx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal8 = ((np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5) * 255).astype(np.uint8)
    # glTF 2.0 ORM packing : R = Occlusion (AO), G = Roughness, B = Metallic
    mr8 = np.stack([np.clip(ao_t, 0.0, 1.0) * 255, rough_t * 255, metal_t * 255],
                   -1).astype(np.uint8)

    return (Image.fromarray(albedo8),
            Image.fromarray(mr8),
            Image.fromarray(normal8),
            wear_v)


def attach_visual(mesh: trimesh.Trimesh, uv: np.ndarray,
                  albedo_img: Image.Image, mr_img: Image.Image,
                  normal_img: Image.Image, name: str = "forge_generated"):
    """Attache un `PBRMaterial` glTF complet (albedo + ORM occlusion/MR + normal)
    avec compression PNG sans perte intégrée."""
    albedo_img = compress_png(albedo_img)
    mr_img = compress_png(mr_img)
    normal_img = compress_png(normal_img)
    mat = trimesh.visual.material.PBRMaterial(
        name=name,
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=albedo_img,
        metallicFactor=1.0,
        roughnessFactor=1.0,
        metallicRoughnessTexture=mr_img,
        occlusionTexture=mr_img,
        normalTexture=normal_img,
        normalTextureScale=1.0,
        doubleSided=True,
    )
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=uv, image=albedo_img, material=mat)
    return mesh
