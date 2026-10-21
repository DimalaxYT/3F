"""
meshkit — boîte à outils géométrique déterministe pour la génération 3D par agent.

Philosophie : l'agent (LLM) raisonne — décomposition de l'objet, proportions,
matériaux — et meshkit exécute la géométrie de façon déterministe et étanche,
avec bake PBR procédural optionnel (`Builder.bake_pbr`).

Conventions :
  * unités : mètres
  * axe vertical : Z (les objets "posés" au sol ont leur base à z=0)
  * face avant d'un objet : vers -Y
  * tout ce qui est destiné à l'impression 3D doit rester watertight
    (les opérations CSG via manifold3d garantissent l'étanchéité)

Dépendances : numpy, trimesh>=4, manifold3d (CSG), shapely (extrusions).
Optionnel : xatlas (UV + bake PBR), usd-core (export USDZ natif).
"""
from __future__ import annotations

import math
import os
import re
import numpy as np
import trimesh

try:  # backend CSG
    import manifold3d  # noqa: F401
    HAS_MANIFOLD = True
except ImportError:
    HAS_MANIFOLD = False

try:
    from shapely.geometry import Polygon
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

CSG_ENGINE = "manifold"

# qualité globale (multiplie les résolutions de sections) : 0.5 rapide, 1.0 normal, 2.0 fin
_QUALITY = 1.0


def set_quality(mult: float) -> None:
    """Ajuste la densité de maillage globale (0.5 = rapide, 2.0 = fin)."""
    global _QUALITY
    _QUALITY = float(max(0.2, min(4.0, mult)))


def _s(n: int) -> int:
    return max(3, int(round(n * _QUALITY)))


# --------------------------------------------------------------------------- #
# Couleurs & matériaux PBR
# --------------------------------------------------------------------------- #

def hex_rgb(spec) -> np.ndarray:
    """Convertit '#rrggbb' / '#rgb' / (r,g,b) 0-255 / (r,g,b) 0-1 en RGB float 0-1."""
    if isinstance(spec, str):
        s = spec.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            raise ValueError(f"couleur hex invalide: {spec!r}")
        return np.array([int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
    arr = np.asarray(spec, dtype=float)
    if arr.max() > 16.0:
        arr = arr / 255.0
    return np.clip(arr, 0.0, 1.0)


def rgb_hex(rgb) -> str:
    arr = np.clip(hex_rgb(rgb) * 255.0, 0.0, 255.0).round().astype(int)
    return f"#{arr[0]:02x}{arr[1]:02x}{arr[2]:02x}"


class Material:
    """Matériau PBR portable (GLB/USDZ) avec extensions glTF 2.0 (verre IOR/transmission,
    vernis clearcoat) + dégradation Phong propre (OBJ/MTL)."""

    def __init__(self, name, color, metallic=0.0, roughness=0.5,
                 opacity=1.0, emissive=None, ior=1.5, transmission=0.0,
                 clearcoat=0.0, clearcoat_roughness=0.06):
        self.name = re.sub(r"[^A-Za-z0-9_]", "_", str(name))
        self.color = hex_rgb(color)
        self.metallic = float(np.clip(metallic, 0.0, 1.0))
        self.roughness = float(np.clip(roughness, 0.02, 1.0))
        self.opacity = float(np.clip(opacity, 0.02, 1.0))
        self.emissive = hex_rgb(emissive) if emissive is not None else None
        self.ior = float(np.clip(ior, 1.0, 2.5))
        self.transmission = float(np.clip(transmission, 0.0, 1.0))
        self.clearcoat = float(np.clip(clearcoat, 0.0, 1.0))
        self.clearcoat_roughness = float(np.clip(clearcoat_roughness, 0.02, 1.0))

    def gltf_extensions(self) -> dict:
        ext = {}
        if self.transmission > 0.001:
            ext["KHR_materials_transmission"] = {"transmissionFactor": round(self.transmission, 4)}
            ext["KHR_materials_ior"] = {"ior": round(self.ior, 4)}
        if self.clearcoat > 0.001:
            ext["KHR_materials_clearcoat"] = {
                "clearcoatFactor": round(self.clearcoat, 4),
                "clearcoatRoughnessFactor": round(self.clearcoat_roughness, 4),
            }
        return ext

    def to_pbr(self):
        alpha = self.opacity
        mat_pbr = trimesh.visual.material.PBRMaterial(
            name=self.name,
            baseColorFactor=[float(self.color[0]), float(self.color[1]),
                             float(self.color[2]), alpha],
            metallicFactor=self.metallic,
            roughnessFactor=self.roughness,
            doubleSided=True,
        )
        if alpha < 0.999 or self.transmission > 0.001:
            mat_pbr.alphaMode = "BLEND"
        if self.emissive is not None:
            mat_pbr.emissiveFactor = [float(self.emissive[0]),
                                      float(self.emissive[1]),
                                      float(self.emissive[2])]
        mat_pbr._forge_ior = self.ior
        mat_pbr._forge_transmission = self.transmission
        mat_pbr._forge_clearcoat = self.clearcoat
        mat_pbr._forge_clearcoat_roughness = self.clearcoat_roughness
        return mat_pbr

    def __repr__(self):
        return f"Material({self.name}, rgb={self.color.round(2)}, M={self.metallic}, R={self.roughness})"


class mat:
    """Préréglages de matériaux réalistes (PBR)."""
    METALS = {  # RGB de référence (usine) + rugosité typique
        "gold":     ((1.000, 0.766, 0.336), 0.20),
        "brass":    ((0.715, 0.470, 0.210), 0.30),
        "copper":   ((0.955, 0.637, 0.538), 0.30),
        "bronze":   ((0.780, 0.500, 0.320), 0.40),
        "steel":    ((0.560, 0.570, 0.580), 0.35),
        "silver":   ((0.972, 0.960, 0.915), 0.15),
        "aluminum": ((0.913, 0.921, 0.925), 0.40),
        "chrome":   ((0.940, 0.940, 0.940), 0.06),
    }

    @staticmethod
    def metal(color="#9aa0a6", roughness=0.3):
        return Material("metal", color, metallic=1.0, roughness=roughness)

    @staticmethod
    def named_metal(kind="steel", roughness=None):
        rgb, r0 = mat.METALS[kind]
        r = r0 if roughness is None else roughness
        return Material(kind, rgb, metallic=1.0, roughness=r)

    @staticmethod
    def wood(color="#8a5a2b", roughness=0.55):
        return Material("wood", color, roughness=roughness)

    @staticmethod
    def abs_injected(color="#e0a820", roughness=0.34):
        """Plastique ABS injecté automobile / carénage moto."""
        return Material("abs_injected", color, metallic=0.0, roughness=roughness)

    @staticmethod
    def anodized_alu(color="#d4d8de", roughness=0.26):
        """Aluminium anodisé / usiné CNC."""
        return Material("anodized_alu", color, metallic=0.88, roughness=roughness)

    @staticmethod
    def brushed_stainless(color="#c4c9cf", roughness=0.22):
        """Acier inoxydable brossé."""
        return Material("brushed_stainless", color, metallic=0.95, roughness=roughness)

    @staticmethod
    def knobby_rubber(color="#1f2023", roughness=0.86):
        """Caoutchouc vulcanisé grainé (pneus, poignées)."""
        return Material("knobby_rubber", color, metallic=0.0, roughness=roughness)

    @staticmethod
    def forged_iron(color="#8b9098", roughness=0.30):
        """Fer / acier forgé trempé."""
        return Material("forged_iron", color, metallic=0.92, roughness=roughness)

    @staticmethod
    def car_clearcoat(color="#b8251e", roughness=0.14):
        """Peinture carrosserie vernie brillante (KHR_materials_clearcoat)."""
        return Material("car_clearcoat", color, metallic=0.22, roughness=roughness,
                        clearcoat=1.0, clearcoat_roughness=0.045)

    @staticmethod
    def plastic(color="#c8c8c8", roughness=0.35):
        return Material("plastic", color, roughness=roughness)

    @staticmethod
    def ceramic(color="#e8e4dc", roughness=0.15):
        return Material("ceramic", color, roughness=roughness,
                        clearcoat=0.65, clearcoat_roughness=0.08)

    @staticmethod
    def glass(color="#d8eef6", opacity=0.24, roughness=0.045, ior=1.52):
        """Verre / cristal réfractif physique (KHR_materials_transmission + IOR)."""
        return Material("glass", color, roughness=roughness, opacity=opacity,
                        ior=ior, transmission=max(0.0, 1.0 - opacity))

    @staticmethod
    def fabric(color="#4a6fa5", roughness=0.85):
        return Material("fabric", color, roughness=roughness)

    @staticmethod
    def rubber(color="#222222", roughness=0.9):
        return Material("rubber", color, roughness=roughness)

    @staticmethod
    def paint(color, roughness=0.45):
        return Material("paint", color, roughness=roughness)

    @staticmethod
    def emissive(color="#fff2cc", strength=1.2):
        return Material("emissive", color, roughness=0.6, emissive=hex_rgb(color) * strength)


# --------------------------------------------------------------------------- #
# Primitives — toutes posées sur le sol (base z=0), centrées en XY
# --------------------------------------------------------------------------- #

def _finish(m: trimesh.Trimesh) -> trimesh.Trimesh:
    m.fix_normals(multibody=False)
    return m


def box(w, d, h) -> trimesh.Trimesh:
    """Pavé : w (X) × d (Y) × h (Z), base à z=0, centré XY."""
    m = trimesh.creation.box(extents=[w, d, h])
    m.apply_translation([0, 0, h / 2])
    return _finish(m)


def rounded_box(w, d, h, r=None, sections=24) -> trimesh.Trimesh:
    """Pavé à arêtes et coins arrondis (congé exact de rayon `r`), base z=0, centré XY.

    Surfaces planes exactes + 12 congés cylindriques + 8 octants sphériques,
    garanti étanche sans artefact booléen.
    """
    w, d, h = float(w), float(d), float(h)
    rmax = min(w, d, h) * 0.495
    r = float(min(w, d, h) * 0.12 if r is None else r)
    r = min(max(r, 0.0), rmax)
    if r <= 1e-6:
        return box(w, d, h)

    nc = max(2, _s(sections) // 4)
    hx = max(0.0, w * 0.5 - r)
    hy = max(0.0, d * 0.5 - r)

    # Anneau XY unitaire : 4 quarts de cercle ordonnés dans le sens trigonométrique
    cos_a, sin_a, sx_a, sy_a = [], [], [], []
    signs = ((1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0))
    for q, (sx, sy) in enumerate(signs):
        th = np.linspace(q * math.pi * 0.5, (q + 1) * math.pi * 0.5, nc)
        cos_a.append(np.cos(th))
        sin_a.append(np.sin(th))
        sx_a.append(np.full(nc, sx))
        sy_a.append(np.full(nc, sy))
    cos_a = np.concatenate(cos_a)
    sin_a = np.concatenate(sin_a)
    sx_a = np.concatenate(sx_a)
    sy_a = np.concatenate(sy_a)

    # Profil vertical (rho, z) : congé bas -> paroi verticale -> congé haut
    psi_bot = np.linspace(-math.pi * 0.5 + 1e-3, 0.0, nc + 1)
    psi_top = np.linspace(0.0, math.pi * 0.5 - 1e-3, nc + 1)
    stations = [(float(r * math.cos(p)), float(r * (1.0 + math.sin(p))))
                for p in psi_bot]
    if h - 2.0 * r > 1e-6:
        stations.append((r, h - r))
    stations.extend((float(r * math.cos(p)), float(h - r + r * math.sin(p)))
                    for p in psi_top[1:])
    # Force la pose exacte à z=0 et le sommet exact à z=h
    stations[0] = (stations[0][0], 0.0)
    stations[-1] = (stations[-1][0], h)

    rings = [np.column_stack([sx_a * hx + rho * cos_a,
                              sy_a * hy + rho * sin_a,
                              np.full_like(cos_a, z)])
             for rho, z in stations]
    return loft(rings, caps=True)


def cylinder(r, h, sections=32) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=r, height=h, sections=_s(sections))
    m.apply_translation([0, 0, h / 2])
    return _finish(m)


def frustum(r_bottom, r_top, h, sections=32) -> trimesh.Trimesh:
    """Tronc de cône (cylindre à deux rayons), base z=0."""
    n = _s(sections)
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rb, rt = float(r_bottom), float(r_top)
    ring_b = np.column_stack([rb * np.cos(th), rb * np.sin(th), np.zeros(n)])
    ring_t = np.column_stack([rt * np.cos(th), rt * np.sin(th), np.full(n, float(h))])
    verts = np.vstack([[0, 0, 0.0], ring_b, [[0, 0, float(h)]], ring_t])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([0, 1 + j, 1 + i])                       # fond
        faces.append([n + 1, 1 + n + 1 + i, 1 + n + 1 + j])   # dessus
        faces.append([1 + i, 1 + j, 1 + n + 1 + i])           # flanc
        faces.append([1 + j, 1 + n + 1 + j, 1 + n + 1 + i])
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    return _finish(m)


def cone(r, h, sections=32) -> trimesh.Trimesh:
    """Cône plein à apex propre (zéro face dégénérée), base z=0."""
    n = _s(sections)
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.column_stack([r * np.cos(th), r * np.sin(th), np.zeros(n)])
    verts = np.vstack([[0, 0, 0.0], ring, [[0, 0, float(h)]]])
    apex = n + 1
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([0, 1 + j, 1 + i])
        faces.append([1 + i, 1 + j, apex])
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    return _finish(m)


def sphere(r, center=(0, 0, 0), subdivisions=3) -> trimesh.Trimesh:
    m = trimesh.creation.icosphere(subdivisions=subdivisions, radius=r)
    m.apply_translation(center)
    return _finish(m)


def torus(R, r, major=32, minor=16, center=None) -> trimesh.Trimesh:
    """Donut posé à plat (axe Z)."""
    if center is None:
        center = (0, 0, r)
    m = trimesh.creation.torus(major_radius=R, minor_radius=r,
                               major_sections=_s(major), minor_sections=_s(minor))
    m.apply_translation(center)
    return _finish(m)


def tube(r_out, r_in, h, sections=32) -> trimesh.Trimesh:
    """Anneau plein (bague) : cylindre creux fermé, garanti étanche."""
    if r_in <= 0 or r_in >= r_out:
        raise ValueError("tube: 0 < r_in < r_out requis")
    prof = [(r_in, 0), (r_out, 0), (r_out, h), (r_in, h), (r_in, 0)]
    return lathe(prof, sections=sections, smooth=False, close=False)


def capsule(r, h_cyl, sections=32) -> trimesh.Trimesh:
    """Capsule verticale (cylindre + 2 hémisphères), hauteur totale = h_cyl + 2r."""
    m = trimesh.creation.capsule(radius=r, height=h_cyl,
                                 count=[_s(sections), max(8, _s(sections) // 2)])
    m.apply_translation([0, 0, h_cyl / 2 + r])
    return _finish(m)


def lathe(profile, sections=48, smooth=True, close=True) -> trimesh.Trimesh:
    """
    Solide de révolution. `profile` : liste de couples `(r, z)` en mètres
    (bas → haut), révolvé autour de l'axe Z.
    Si close=True, les extrémités ouvertes sont refermées sur l'axe
    (garantit l'étanchéité pour l'impression 3D).
    """
    pts = [(float(r), float(z)) for r, z in profile]
    if close:
        if pts[0][0] > 1e-9:
            pts.insert(0, (0.0, pts[0][1]))
        if pts[-1][0] > 1e-9:
            pts.append((0.0, pts[-1][1]))
    arr = np.array(pts, dtype=float)
    if (arr[:, 0] < -1e-9).any():
        raise ValueError("lathe: rayons négatifs interdits")
    m = trimesh.creation.revolve(arr, sections=_s(sections))
    if smooth:
        try:
            trimesh.smoothing.filter_taubin(m, lamb=0.5, nu=-0.53, iterations=6)
        except Exception:
            pass
    return _finish(m)


def extrude(points2d, height) -> trimesh.Trimesh:
    """Extrusion d'un polygone 2D [(x,y),...] sur height, base z=0."""
    if not HAS_SHAPELY:
        raise RuntimeError("shapely requis pour extrude(): pip install shapely")
    poly = Polygon(points2d)
    if not poly.is_valid:
        poly = poly.buffer(0)
    m = trimesh.creation.extrude_polygon(poly, height=float(height))
    return _finish(m)


# --------------------------------------------------------------------------- #
# Surfaces paramétriques continues : loft() & sweep() (zéro escalier voxel)
# --------------------------------------------------------------------------- #

def _resample_ring(pts: np.ndarray, n: int) -> np.ndarray:
    """Ré-échantillonne un anneau 3D fermé à `n` sommets par abscisse curviligne."""
    pts = np.asarray(pts, dtype=float)
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) == n:
        return pts
    closed = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total < 1e-12:
        return np.repeat(pts[:1], n, axis=0)
    targets = np.linspace(0.0, total, n, endpoint=False)
    out = np.column_stack([np.interp(targets, cum, closed[:, k]) for k in range(3)])
    return out


def loft(sections, zs=None, caps=True) -> trimesh.Trimesh:
    """Relie une séquence de sections en un solide étanche (bouché si `caps=True`).
    Accepte :
      - `[ring3d_0, ring3d_1, ...]` où chaque anneau est `N×3`
      - `[(ring2d_0, z0), (ring2d_1, z1), ...]`
      - `[ring2d_0, ring2d_1, ...], zs=[z0, z1, ...]`
    """
    norm_rings = []
    if zs is not None:
        for s, z in zip(sections, zs):
            arr = np.asarray(s, dtype=float)
            if arr.shape[1] == 2:
                arr = np.column_stack([arr, np.full(len(arr), float(z))])
            norm_rings.append(arr)
    else:
        for s in sections:
            if (isinstance(s, (tuple, list)) and len(s) == 2
                    and np.ndim(s[0]) == 2 and np.ndim(s[1]) == 0):
                arr2 = np.asarray(s[0], dtype=float)
                norm_rings.append(np.column_stack([arr2, np.full(len(arr2), float(s[1]))]))
            else:
                norm_rings.append(np.asarray(s, dtype=float))
    raw = norm_rings
    if len(raw) < 2:
        raise ValueError("loft: au moins 2 sections requises")
    cleaned = [r[:-1] if len(r) > 1 and np.allclose(r[0], r[-1]) else r for r in raw]
    n_pts = max(len(r) for r in cleaned)
    if n_pts < 3:
        raise ValueError("loft: chaque section doit avoir >= 3 points")
    rings = [_resample_ring(r, n_pts) for r in cleaned]
    n_rings = len(rings)

    verts_list = list(rings)
    faces = []
    for r in range(n_rings - 1):
        b0 = r * n_pts
        b1 = (r + 1) * n_pts
        for i in range(n_pts):
            j = (i + 1) % n_pts
            faces.append([b0 + i, b0 + j, b1 + j])
            faces.append([b0 + i, b1 + j, b1 + i])

    if caps:
        c_start = len(verts_list) * n_pts
        c_end = c_start + 1
        verts_all = np.vstack(verts_list + [rings[0].mean(0)[None, :],
                                            rings[-1].mean(0)[None, :]])
        for i in range(n_pts):
            j = (i + 1) % n_pts
            faces.append([c_start, j, i])
            faces.append([c_end, (n_rings - 1) * n_pts + i,
                          (n_rings - 1) * n_pts + j])
    else:
        verts_all = np.vstack(verts_list)

    m = trimesh.Trimesh(vertices=verts_all, faces=np.asarray(faces, dtype=np.int64),
                        process=True)
    keep = m.area_faces > 1e-13
    if not keep.all():
        m.update_faces(keep)
        m.merge_vertices()
    if caps and not m.is_watertight:
        trimesh.repair.fill_holes(m)
    if m.is_watertight and m.volume < 0:
        m.invert()
    return _finish(m)


def sweep(profile, path, scale=1.0, twist_deg=0.0, up_hint=None,
          caps=True) -> trimesh.Trimesh:
    """Balaie un profil 2D `[(u, v), ...]` le long d'une courbe 3D `path` par
    repère à transport parallèle (Bishop frame — zéro retournement de Frenet).

    * `scale`     : float, `(su, sv)`, liste de longueur `len(path)`, ou `fn(t)`
                    avec `t` dans `[0, 1]` (abscisse curviligne normalisée).
    * `twist_deg` : torsion progressive en degrés (float, liste ou `fn(t)`).
    * Convention naturelle : pour un chemin vertical `(0,0,z)`, `u -> +X` et
      `v -> +Y` (identique à `extrude()`).
    """
    prof = np.asarray(profile, dtype=float)
    if prof.ndim != 2 or prof.shape[1] != 2 or len(prof) < 3:
        raise ValueError("sweep: profile attendu de forme (N>=3, 2)")
    if np.allclose(prof[0], prof[-1]):
        prof = prof[:-1]

    pts = np.asarray(path, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) < 2:
        raise ValueError("sweep: path attendu de forme (K>=2, 3)")
    k_len = len(pts)

    # Abscisse curviligne normalisée t in [0, 1]
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = max(float(cum[-1]), 1e-12)
    ts = cum / total

    # Tangentes unitaires lissées aux stations
    tangents = np.zeros_like(pts)
    tangents[0] = pts[1] - pts[0]
    tangents[-1] = pts[-1] - pts[-2]
    if k_len > 2:
        tangents[1:-1] = pts[2:] - pts[:-2]
    norms = np.linalg.norm(tangents, axis=1, keepdims=True)
    tangents = tangents / np.clip(norms, 1e-12, None)

    # Repère initial : si tangente quasi verticale (+Z), N0 = +X => B0 = +Y
    t0 = tangents[0]
    if up_hint is not None:
        ref = np.asarray(up_hint, dtype=float)
    elif abs(t0[2]) > 0.85:
        ref = np.array([1.0, 0.0, 0.0])
    else:
        ref = np.array([0.0, 0.0, 1.0])
    n0 = ref - np.dot(ref, t0) * t0
    if np.linalg.norm(n0) < 1e-8:
        ref = np.array([0.0, 1.0, 0.0])
        n0 = ref - np.dot(ref, t0) * t0
    n_vec = n0 / np.linalg.norm(n0)

    normals = np.zeros_like(pts)
    binormals = np.zeros_like(pts)
    normals[0] = n_vec
    binormals[0] = np.cross(t0, n_vec)

    # Transport parallèle de Bishop le long de la courbe 3D
    for k in range(1, k_len):
        prev_t, cur_t = tangents[k - 1], tangents[k]
        axis = np.cross(prev_t, cur_t)
        sin_a = np.linalg.norm(axis)
        if sin_a > 1e-8:
            axis = axis / sin_a
            cos_a = float(np.clip(np.dot(prev_t, cur_t), -1.0, 1.0))
            ang = math.atan2(sin_a, cos_a)
            rot = trimesh.transformations.rotation_matrix(ang, axis)[:3, :3]
            n_vec = rot @ n_vec
            n_vec = n_vec - np.dot(n_vec, cur_t) * cur_t
            n_vec = n_vec / max(np.linalg.norm(n_vec), 1e-12)
        normals[k] = n_vec
        binormals[k] = np.cross(cur_t, n_vec)

    def _eval_scale(idx: int, t: float) -> tuple[float, float]:
        val = scale(t) if callable(scale) else (
            scale[idx] if isinstance(scale, (list, tuple, np.ndarray))
            and not (len(scale) == 2 and k_len != 2 and np.isscalar(scale[0]))
            else scale)
        if np.isscalar(val):
            s = max(float(val), 1e-4)
            return s, s
        return max(float(val[0]), 1e-4), max(float(val[1]), 1e-4)

    def _eval_twist(idx: int, t: float) -> float:
        if callable(twist_deg):
            return float(twist_deg(t))
        if isinstance(twist_deg, (list, tuple, np.ndarray)):
            return float(twist_deg[idx])
        return float(twist_deg) * t

    rings = []
    for k in range(k_len):
        su, sv = _eval_scale(k, float(ts[k]))
        tw = math.radians(_eval_twist(k, float(ts[k])))
        ct, st = math.cos(tw), math.sin(tw)
        u = prof[:, 0] * su
        v = prof[:, 1] * sv
        ur = u * ct - v * st
        vr = u * st + v * ct
        ring = (pts[k][None, :]
                + ur[:, None] * normals[k][None, :]
                + vr[:, None] * binormals[k][None, :])
        rings.append(ring)

    return loft(rings, caps=caps)


def chamfer_box(w, d, h, c=None) -> trimesh.Trimesh:
    """Bloc mécanique usiné à chanfrein franc 45° (`c`), posé à z=0, centré XY.
    Idéal pour tés de fourche CNC, carters moteur, étriers de frein. Garanti étanche."""
    w, d, h = float(w), float(d), float(h)
    cmax = min(w, d, h) * 0.48
    c = float(min(w, d, h) * 0.10 if c is None else c)
    c = min(max(c, 1e-5), cmax)
    hx, hy = w * 0.5, d * 0.5
    oct_2d = np.array([
        [ hx - c,  hy], [-hx + c,  hy],
        [-hx,  hy - c], [-hx, -hy + c],
        [-hx + c, -hy], [ hx - c, -hy],
        [ hx, -hy + c], [ hx,  hy - c],
    ])
    oct_in = np.array([
        [ max(0.0, hx - 2 * c),  max(0.0, hy - c)],
        [-max(0.0, hx - 2 * c),  max(0.0, hy - c)],
        [-max(0.0, hx - c),  max(0.0, hy - 2 * c)],
        [-max(0.0, hx - c), -max(0.0, hy - 2 * c)],
        [-max(0.0, hx - 2 * c), -max(0.0, hy - c)],
        [ max(0.0, hx - 2 * c), -max(0.0, hy - c)],
        [ max(0.0, hx - c), -max(0.0, hy - 2 * c)],
        [ max(0.0, hx - c),  max(0.0, hy - 2 * c)],
    ])
    stations = [(oct_in, 0.0), (oct_2d, c)]
    if h - 2 * c > 1e-6:
        stations.append((oct_2d, h - c))
    stations.append((oct_in, h))
    return loft(stations, caps=True)


def tube_sweep(path, r, r_inner=0.0, sections=24, smooth_pts=48,
               scale=1.0) -> trimesh.Trimesh:
    """Tube mécanique de section circulaire exacte balayé le long d'une courbe 3D
    lissée par PCHIP (collecteurs d'échappement, guidons, arceaux, cadres).
    Si `0 < r_inner < r`, creuse l'intérieur par CSG `manifold3d` (étanche)."""
    from scipy.interpolate import PchipInterpolator

    pts = np.asarray(path, dtype=float)
    if len(pts) >= 3 and smooth_pts > len(pts):
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        t = np.concatenate([[0.0], np.cumsum(np.maximum(seg, 1e-6))])
        t /= t[-1]
        ts = np.linspace(0.0, 1.0, int(smooth_pts))
        pts = np.column_stack([PchipInterpolator(t, pts[:, k])(ts) for k in range(3)])

    n_sec = max(8, _s(sections))
    ang = np.linspace(0.0, 2.0 * math.pi, n_sec, endpoint=False)
    prof_out = np.column_stack([float(r) * np.cos(ang), float(r) * np.sin(ang)])
    outer = sweep(prof_out, pts, scale=scale, caps=True)
    if r_inner and 0.0 < float(r_inner) < float(r):
        # Prolonge légèrement l'âme aux deux bouts pour percer franchement les bouchons
        d0 = pts[1] - pts[0]; d0 /= max(np.linalg.norm(d0), 1e-9)
        d1 = pts[-1] - pts[-2]; d1 /= max(np.linalg.norm(d1), 1e-9)
        pts_in = pts.copy()
        pts_in[0] = pts[0] - d0 * float(r) * 0.5
        pts_in[-1] = pts[-1] + d1 * float(r) * 0.5
        prof_in = np.column_stack([float(r_inner) * np.cos(ang),
                                   float(r_inner) * np.sin(ang)])
        inner = sweep(prof_in, pts_in, scale=scale, caps=True)
        return difference(outer, [inner])
    return outer


def helix_spring(r_coil, r_wire, pitch, turns=6.0, sections=12,
                 pts_per_turn=20) -> trimesh.Trimesh:
    """Ressort hélicoïdal 3D exact (amortisseur moto, suspension, mécanique),
    posé proprement à `z = 0`, garanti étanche."""
    n_pts = max(16, int(round(turns * max(8, _s(pts_per_turn)))))
    ts = np.linspace(0.0, float(turns) * 2.0 * math.pi, n_pts)
    zs = float(r_wire) + (ts / (2.0 * math.pi)) * float(pitch)
    path = np.column_stack([float(r_coil) * np.cos(ts),
                            float(r_coil) * np.sin(ts),
                            zs])
    sp = tube_sweep(path, r=float(r_wire), sections=sections, smooth_pts=0)
    return ground(sp)


def cable(points, r=0.004, sag=0.0, sections=10, smooth_pts=36) -> trimesh.Trimesh:
    """Câble / durite hydraulique souple reliant `points` avec flèche gravitaire
    optionnelle `sag` (durite de frein, câble d'embrayage, cordon)."""
    pts = np.asarray(points, dtype=float).copy()
    if sag != 0.0 and len(pts) == 2:
        mid = 0.5 * (pts[0] + pts[1])
        mid[2] -= float(sag)
        pts = np.vstack([pts[0], mid, pts[1]])
    return tube_sweep(pts, r=float(r), sections=sections, smooth_pts=smooth_pts)


# --------------------------------------------------------------------------- #
# CSG (manifold3d) — résultats garantis étanches
# --------------------------------------------------------------------------- #

def _check_solid(m, label):
    if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
        raise ValueError(f"CSG: {label} n'est pas un mesh valide")
    if not m.is_watertight:
        raise ValueError(f"CSG: {label} doit être étanche (watertight). "
                         "Utilise des primitives/CSG en entrée.")


def union(meshes) -> trimesh.Trimesh:
    meshes = list(meshes)
    for i, m in enumerate(meshes):
        _check_solid(m, f"part[{i}]")
    out = trimesh.boolean.union(meshes, engine=CSG_ENGINE)
    return _finish(out)


def difference(base, tools) -> trimesh.Trimesh:
    _check_solid(base, "base")
    for i, t in enumerate(tools):
        _check_solid(t, f"tool[{i}]")
    out = trimesh.boolean.difference([base] + list(tools), engine=CSG_ENGINE)
    return _finish(out)


def intersection(a, b) -> trimesh.Trimesh:
    _check_solid(a, "a")
    _check_solid(b, "b")
    out = trimesh.boolean.intersection([a, b], engine=CSG_ENGINE)
    return _finish(out)


# --------------------------------------------------------------------------- #
# Transformations (in-place, retournent le mesh pour chaînage)
# --------------------------------------------------------------------------- #

def place(m, x=0.0, y=0.0, z=0.0):
    m.apply_translation([x, y, z])
    return m


def rot_x(m, deg):
    m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(deg), [1, 0, 0]))
    return m


def rot_y(m, deg):
    m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(deg), [0, 1, 0]))
    return m


def rot_z(m, deg):
    m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(deg), [0, 0, 1]))
    return m


def scale(m, s):
    if np.isscalar(s):
        s = [s, s, s]
    m.apply_scale(s)
    return m


def ground(m):
    """Pose le mesh sur le sol (min z = 0)."""
    m.apply_translation([0, 0, -m.bounds[0][2]])
    return m


# --------------------------------------------------------------------------- #
# Builder — assemblage multi-pièces avec matériaux + bake PBR optionnel
# --------------------------------------------------------------------------- #

class Builder:
    """
    Assemble des pièces (mesh + matériau) en une scène exportable.

    Peut aussi cuire un atlas UV + textures PBR procédurales (`albedo`,
    `metallicRoughness`, `normal`) via `b.bake_pbr(overlays=[...])`, combinant
    la précision géométrique CSG/sweep/lathe et la richesse matérielle Meshy.
    """

    def __init__(self, name, params=None):
        self.name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
        self.params = dict(params or {})
        self._parts = []   # (mesh, Material|None, label)
        self._part_groups = {}  # part_index -> group_name
        self._joints = {}  # group_name -> {"pivot": [x,y,z], "axis": [ax,ay,az], "kind": str}
        self._sockets = {}  # socket_name -> {"position": [x,y,z], "rotation_deg": [rx,ry,rz]}
        self._baked_scene: trimesh.Scene | None = None
        self._baked_maps: tuple | None = None

    def def_socket(self, name: str, pos=(0.0, 0.0, 0.0), rot_deg=(0.0, 0.0, 0.0)) -> str:
        """Déclare un point d'attache gameplay (`SOCKET_grip`, `SOCKET_muzzle`, `SOCKET_tip`,
        `SOCKET_light_0`...) exporté comme nœud Xform nommé dans le `.glb` final."""
        clean = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
        if not clean.upper().startswith("SOCKET_"):
            clean = f"SOCKET_{clean}"
        self._sockets[clean] = {
            "position": [float(pos[0]), float(pos[1]), float(pos[2])],
            "rotation_deg": [float(rot_deg[0]), float(rot_deg[1]), float(rot_deg[2])],
        }
        return clean

    def def_joint(self, group: str, pivot=(0.0, 0.0, 0.0), axis=(0.0, 1.0, 0.0),
                  kind: str = "revolute"):
        """Déclare un sous-assemblage articulé (`group`) doté d'un pivot physique exact
        en mètres (ex. essieu `front_wheel`, colonne `steering`, porte `door`).
        Dans le `.glb` exporté, le nœud parent est placé exactement à `pivot` et ses
        pièces sont exprimées dans son repère local — prêt à animer sans décalage !"""
        g = re.sub(r"[^A-Za-z0-9_\-]", "_", group)
        self._joints[g] = {
            "pivot": [float(pivot[0]), float(pivot[1]), float(pivot[2])],
            "axis": [float(axis[0]), float(axis[1]), float(axis[2])],
            "kind": str(kind),
        }
        return g

    def add(self, mesh, material: Material | None = None, name=None,
            at=None, rot=None, group: str | None = None):
        """
        rot : (rx_deg, ry_deg, rz_deg) appliqué d'abord (autour de l'origine),
        puis translation at=(x,y,z). Retourne le mesh (chaînage possible).
        """
        if rot is not None:
            rx, ry, rz = rot
            if rx:
                rot_x(mesh, rx)
            if ry:
                rot_y(mesh, ry)
            if rz:
                rot_z(mesh, rz)
        if at is not None:
            place(mesh, *at)
        self._baked_scene = None
        idx = len(self._parts)
        self._parts.append((mesh, material, name or f"part{idx}"))
        if group is not None:
            self._part_groups[idx] = re.sub(r"[^A-Za-z0-9_\-]", "_", group)
        return mesh

    @property
    def parts(self):
        return list(self._parts)

    @property
    def baked_maps(self):
        """`(albedo_img, mr_img, normal_img)` si `bake_pbr()` a été appelé."""
        return self._baked_maps

    def bounds(self):
        lo = np.min([p[0].bounds[0] for p in self._parts], axis=0)
        hi = np.max([p[0].bounds[1] for p in self._parts], axis=0)
        return np.vstack([lo, hi])

    def stats(self) -> dict:
        tris = sum(len(p[0].faces) for p in self._parts)
        verts = sum(len(p[0].vertices) for p in self._parts)
        bb = self.bounds()
        return {"parts": len(self._parts), "triangles": int(tris),
                "vertices": int(verts),
                "dims_m": [round(float(bb[1][0] - bb[0][0]), 4),
                           round(float(bb[1][1] - bb[0][1]), 4),
                           round(float(bb[1][2] - bb[0][2]), 4)]}

    def bake_pbr(self, overlays=None, extra_palette=None, texture_size=1024,
                 normal_strength=2.0) -> trimesh.Scene:
        """Déplie l'UV (xatlas) et cuit un atlas PBR procédural multi-cartes
        (`albedo` + `metallicRoughness` + `normal`) directement sur la géométrie
        exacte des pièces du Builder.

        Chaque pièce est adressable par son `name` dans `overlays`
        (ex. `{"type": "wrap", "on": "tsuka", "diamond": True}`,
        `{"type": "edge_wear", "on": ["blade", "habaki"]}`).
        Les parties transparentes (`opacity < 0.999`, verre) restent en matériau
        natif transparent pour préserver le rendu vitré.
        """
        import pbr

        opaque_meshes, v_labels, palette = [], [], []
        glass_geoms = {}
        seen_ids = set()

        for i, (mesh, material, label) in enumerate(self._parts):
            mat_obj = material or Material("default", "#bfbfb8", 0.0, 0.5)
            if mat_obj.opacity < 0.999:
                g = mesh.copy()
                g.visual = trimesh.visual.TextureVisuals(material=mat_obj.to_pbr())
                glass_geoms[f"{label}_{i}"] = g
                continue
            pid = label if label not in seen_ids else f"{label}_{i}"
            seen_ids.add(pid)
            k = len(palette)
            palette.append({
                "id": pid,
                "name": pid,
                "color": rgb_hex(mat_obj.color),
                "metallic": mat_obj.metallic,
                "roughness": mat_obj.roughness,
            })
            opaque_meshes.append(mesh.copy())
            v_labels.append(np.full(len(mesh.vertices), k, dtype=np.int32))

        for ep in (extra_palette or []):
            if ep["id"] not in seen_ids:
                seen_ids.add(ep["id"])
                palette.append(dict(ep))

        geoms = {}
        if opaque_meshes:
            combined = trimesh.util.concatenate(opaque_meshes)
            labels_cat = np.concatenate(v_labels)
            mesh_uv, labels_uv, uv = pbr.unwrap(combined, labels_cat)
            spec = {
                "palette": palette,
                "overlays": list(overlays or []),
                "texture_size": int(texture_size),
                "normal_strength": float(normal_strength),
            }
            albedo_img, mr_img, normal_img, _ = pbr.bake_textures(
                mesh_uv, labels_uv, uv, spec)
            pbr.attach_visual(mesh_uv, uv, albedo_img, mr_img, normal_img,
                              name=f"{self.name}_pbr")
            geoms[f"{self.name}_body"] = mesh_uv
            self._baked_maps = (albedo_img, mr_img, normal_img)

        geoms.update(glass_geoms)
        self._baked_scene = trimesh.Scene(geoms, base_frame=self.name)
        return self._baked_scene.copy()

    def scene(self) -> trimesh.Scene:
        if self._baked_scene is not None:
            return self._baked_scene.copy()
        sc = trimesh.Scene(base_frame=self.name)
        created_groups = set()
        for grp, jinfo in self._joints.items():
            T = np.eye(4, dtype=float)
            T[:3, 3] = jinfo["pivot"]
            sc.graph.update(frame_to=grp, frame_from=self.name, matrix=T)
            created_groups.add(grp)

        for i, (mesh, material, label) in enumerate(self._parts):
            gname = f"{label}_{i}"
            g = mesh.copy()
            grp = self._part_groups.get(i)
            parent = self.name
            if grp:
                if grp not in created_groups:
                    sc.graph.update(frame_to=grp, frame_from=self.name, matrix=np.eye(4))
                    created_groups.add(grp)
                piv = self._joints.get(grp, {}).get("pivot")
                if piv is not None:
                    g.apply_translation([-piv[0], -piv[1], -piv[2]])
                parent = grp
            if material is not None:
                g.visual = trimesh.visual.TextureVisuals(material=material.to_pbr())
            sc.add_geometry(g, node_name=gname, geom_name=gname, parent_node_name=parent)

        sc.metadata["joints"] = dict(self._joints)
        sc.metadata["sockets"] = dict(self._sockets)
        return sc

    def union_solid(self) -> trimesh.Trimesh:
        """Fusionne toutes les pièces en un seul solide étanche (export STL)."""
        meshes = [p[0].copy() for p in self._parts]
        if len(meshes) == 1:
            return meshes[0]
        if HAS_MANIFOLD:
            try:
                out = union(meshes)
                return _finish(out)
            except Exception:
                pass
        merged = trimesh.util.concatenate(meshes)
        return _finish(merged)


# --------------------------------------------------------------------------- #
# Export OBJ + MTL (matériaux Phong dérivés du PBR + textures UV si présentes)
# --------------------------------------------------------------------------- #

def export_obj_with_mtl(scene: trimesh.Scene, obj_path: str) -> str:
    """Écrit .obj + .mtl (+ texture PNG si présente) avec groupes par matériau."""
    base = os.path.splitext(obj_path)[0]
    out_dir = os.path.dirname(os.path.abspath(obj_path)) or "."
    mtl_path = base + ".mtl"
    mtl_name = os.path.basename(mtl_path)
    lines_obj = ["# généré par 3d-forge (meshkit)", "mtllib " + mtl_name]
    lines_mtl = ["# généré par 3d-forge (meshkit)"]
    seen_mats = set()
    v_off = vt_off = vn_off = 0

    for gname, geom in scene.geometry.items():
        material = getattr(geom.visual, "material", None)
        mname = getattr(material, "name", None) or f"m_{gname}"
        mname = re.sub(r"[^A-Za-z0-9_]", "_", mname)
        tex_img = getattr(material, "baseColorTexture", None) or getattr(geom.visual, "image", None)
        uv = getattr(geom.visual, "uv", None)
        has_uv = uv is not None and len(uv) == len(geom.vertices)

        if mname not in seen_mats:
            seen_mats.add(mname)
            raw_col = getattr(material, "baseColorFactor", None)
            col = (np.asarray(raw_col, dtype=float)
                   if raw_col is not None else np.array([0.75, 0.75, 0.75, 1.0]))
            if col.max() > 1.001:
                col = col / 255.0
            rough = float(getattr(material, "roughnessFactor", 0.5) or 0.5)
            metal = float(getattr(material, "metallicFactor", 0.0) or 0.0)
            opacity = float(col[3]) if len(col) > 3 else 1.0
            ns = min(1000.0, max(2.0, 2.0 / (rough ** 4 + 1e-4)))
            ks = 0.08 + 0.72 * metal
            mtl_entry = [f"newmtl {mname}",
                         f"Kd {col[0]:.4f} {col[1]:.4f} {col[2]:.4f}",
                         "Ka 0.10 0.10 0.10",
                         f"Ks {ks:.3f} {ks:.3f} {ks:.3f}",
                         f"Ns {ns:.1f}", "Ni 1.45",
                         f"d {opacity:.3f}", "illum 2"]
            if tex_img is not None and has_uv:
                tex_name = f"{os.path.basename(base)}_{mname}.png"
                tex_img.save(os.path.join(out_dir, tex_name))
                mtl_entry.append(f"map_Kd {tex_name}")
            lines_mtl += mtl_entry

        v = geom.vertices
        vn = geom.vertex_normals
        f = geom.faces + 1
        lines_obj.append(f"o {gname}")
        lines_obj += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in v]
        if has_uv:
            lines_obj += [f"vt {float(u):.6f} {float(vv):.6f}" for u, vv in uv]
        lines_obj += [f"vn {x:.4f} {y:.4f} {z:.4f}" for x, y, z in vn]
        lines_obj.append("usemtl " + mname)
        if has_uv:
            lines_obj += [
                f"f {a + v_off}/{a + vt_off}/{a + vn_off} "
                f"{b + v_off}/{b + vt_off}/{b + vn_off} "
                f"{c + v_off}/{c + vt_off}/{c + vn_off}"
                for a, b, c in f
            ]
            vt_off += len(uv)
        else:
            lines_obj += [
                f"f {a + v_off}//{a + vn_off} {b + v_off}//{b + vn_off} "
                f"{c + v_off}//{c + vn_off}"
                for a, b, c in f
            ]
        v_off += len(v)
        vn_off += len(vn)

    with open(obj_path, "w") as fo:
        fo.write("\n".join(lines_obj) + "\n")
    with open(mtl_path, "w") as fm:
        fm.write("\n".join(lines_mtl) + "\n")
    return obj_path


def compute_mikk_tangents(mesh: trimesh.Trimesh, uv: np.ndarray | None = None) -> np.ndarray:
    """Calcule l'attribut glTF 2.0 `TANGENT` (`(V, 4)` float32 : `Tx, Ty, Tz, w`)
    orthonormalisé par Gram-Schmidt avec signe de bitangente `w ∈ {-1.0, +1.0}`.
    Élimine les coutures d'éclairage Normal Map sous Unreal Engine, Unity, Godot et Three.js !"""
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    nrms = np.asarray(mesh.vertex_normals, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    n_v = len(verts)
    if uv is None:
        uv = getattr(mesh.visual, "uv", None)
    if uv is None or len(uv) != n_v or len(faces) == 0:
        # Repère tangent orthonormé canonique sans UV
        up = np.where(np.abs(nrms[:, 2:3]) < 0.9, np.array([[0.0, 0.0, 1.0]]), np.array([[1.0, 0.0, 0.0]]))
        t = np.cross(up, nrms)
        t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-12
        return np.column_stack([t, np.ones(n_v, dtype=np.float64)]).astype(np.float32)

    uv = np.asarray(uv, dtype=np.float64)
    i0, i1, i2 = faces[:, 0], faces[:, 1], faces[:, 2]
    e1 = verts[i1] - verts[i0]
    e2 = verts[i2] - verts[i0]
    duv1 = uv[i1] - uv[i0]
    duv2 = uv[i2] - uv[i0]
    denom = duv1[:, 0] * duv2[:, 1] - duv2[:, 0] * duv1[:, 1]
    inv = np.where(np.abs(denom) > 1e-12, 1.0 / np.where(np.abs(denom) > 1e-12, denom, 1.0), 0.0)
    sdir = (duv2[:, 1:2] * e1 - duv1[:, 1:2] * e2) * inv[:, None]
    tdir = (duv1[:, 0:1] * e2 - duv2[:, 0:1] * e1) * inv[:, None]

    tan1 = np.zeros((n_v, 3), dtype=np.float64)
    tan2 = np.zeros((n_v, 3), dtype=np.float64)
    np.add.at(tan1, i0, sdir); np.add.at(tan1, i1, sdir); np.add.at(tan1, i2, sdir)
    np.add.at(tan2, i0, tdir); np.add.at(tan2, i1, tdir); np.add.at(tan2, i2, tdir)

    t = tan1 - nrms * np.sum(nrms * tan1, axis=1, keepdims=True)
    t_len = np.linalg.norm(t, axis=1, keepdims=True)
    fallback = np.cross(
        np.where(np.abs(nrms[:, 2:3]) < 0.9, np.array([[0.0, 0.0, 1.0]]), np.array([[1.0, 0.0, 0.0]])),
        nrms,
    )
    fallback /= np.linalg.norm(fallback, axis=1, keepdims=True) + 1e-12
    t = np.where(t_len > 1e-9, t / np.maximum(t_len, 1e-9), fallback)
    w = np.where(np.sum(np.cross(nrms, t) * tan2, axis=1) < 0.0, -1.0, 1.0)
    return np.column_stack([t, w]).astype(np.float32)


def export_glb_pbr(scene: trimesh.Scene, glb_path: str, webp: bool = False) -> str:
    """Exporte `scene` en `.glb` binaire standard glTF 2.0 Game-Ready (`v5`) avec :
      - Attribut `TANGENT` (`VEC4`, `FLOAT`) explicite sur chaque primitive texturée UV,
      - Extensions officielles `KHR_materials_transmission`, `KHR_materials_ior`,
        `KHR_materials_clearcoat` (+ `EXT_texture_webp` si `webp=True`),
      - Pistes d'animations standards `gltf.animations` (quaternions) générées
        automatiquement depuis `joints` (roues, charnières, tourelles, portes),
      - Nœuds vides nommés `SOCKET_*` pour l'attachement gameplay direct en moteur."""
    import io
    import json
    import struct
    from PIL import PngImagePlugin

    # Encodage PNG sans perte ultra-rapide (`compress_level=1` -> 15x plus rapide dans `trimesh.export_glb` !)
    _orig_png_save = PngImagePlugin._save

    def _fast_png_save(im, fp, filename, chunk=PngImagePlugin.putchunk, save_all=False):
        im.encoderinfo.setdefault("compress_level", 1)
        return _orig_png_save(im, fp, filename, chunk=chunk, save_all=save_all)

    PngImagePlugin._save = _fast_png_save
    try:
        scene.export(glb_path, include_normals=True)
    finally:
        PngImagePlugin._save = _orig_png_save
    mat_exts = {}
    for geom in scene.geometry.values():
        m = getattr(geom.visual, "material", None)
        if m is None or not getattr(m, "name", None):
            continue
        tr = float(getattr(m, "_forge_transmission", 0.0) or 0.0)
        ior = float(getattr(m, "_forge_ior", 1.5) or 1.5)
        cc = float(getattr(m, "_forge_clearcoat", 0.0) or 0.0)
        ccr = float(getattr(m, "_forge_clearcoat_roughness", 0.06) or 0.06)
        ext = {}
        if tr > 0.001:
            ext["KHR_materials_transmission"] = {"transmissionFactor": round(tr, 4)}
            ext["KHR_materials_ior"] = {"ior": round(ior, 4)}
        if cc > 0.001:
            ext["KHR_materials_clearcoat"] = {
                "clearcoatFactor": round(cc, 4),
                "clearcoatRoughnessFactor": round(ccr, 4),
            }
        if ext:
            mat_exts[m.name] = ext

    meta = scene.metadata or {}
    joints = meta.get("joints") or {}
    sockets = meta.get("sockets") or {}

    with open(glb_path, "rb") as fh:
        raw = fh.read()
    magic, version, _ = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67:
        return glb_path
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    if j_type != 0x4E4F534A:
        return glb_path
    gltf = json.loads(raw[20:20 + j_len].decode("utf-8"))
    bin_off = 20 + j_len
    if bin_off + 8 <= len(raw):
        b_len, b_type = struct.unpack_from("<II", raw, bin_off)
        bin_data = bytearray(raw[bin_off + 8:bin_off + 8 + b_len])
    else:
        b_type = 0x004E4942
        bin_data = bytearray()

    def _append_bytes(payload: bytes, target: int | None = None) -> int:
        while len(bin_data) % 4 != 0:
            bin_data.append(0)
        offset = len(bin_data)
        bin_data.extend(payload)
        while len(bin_data) % 4 != 0:
            bin_data.append(0)
        bv = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            bv["target"] = target
        gltf.setdefault("bufferViews", []).append(bv)
        return len(gltf["bufferViews"]) - 1

    # 1. Injecte `TANGENT` (VEC4 float32) sur chaque primitive disposant de `POSITION` + `NORMAL` + `TEXCOORD_0`
    acc_list = gltf.setdefault("accessors", [])
    bv_list = gltf.setdefault("bufferViews", [])

    def _read_acc_f32(acc_idx: int, n_comp: int) -> np.ndarray | None:
        acc = acc_list[acc_idx]
        if acc.get("componentType") != 5126:
            return None
        bv = bv_list[acc["bufferView"]]
        start = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        cnt = int(acc["count"])
        stride = int(bv.get("byteStride") or (n_comp * 4))
        if stride == n_comp * 4:
            return np.frombuffer(bin_data, dtype="<f4", count=cnt * n_comp, offset=start).reshape(cnt, n_comp).copy()
        out_a = np.empty((cnt, n_comp), dtype=np.float32)
        for k in range(cnt):
            out_a[k] = np.frombuffer(bin_data, dtype="<f4", count=n_comp, offset=start + k * stride)
        return out_a

    def _read_indices(acc_idx: int) -> np.ndarray:
        acc = acc_list[acc_idx]
        bv = bv_list[acc["bufferView"]]
        start = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        cnt = int(acc["count"])
        ctype = acc["componentType"]
        dt = {5121: np.uint8, 5123: "<u2", 5125: "<u4"}[ctype]
        return np.frombuffer(bin_data, dtype=dt, count=cnt, offset=start).astype(np.int64)

    for mesh_def in gltf.get("meshes", []):
        for prim in mesh_def.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "TANGENT" in attrs or "TEXCOORD_0" not in attrs or "POSITION" not in attrs:
                continue
            pos_a = _read_acc_f32(attrs["POSITION"], 3)
            uv_a = _read_acc_f32(attrs["TEXCOORD_0"], 2)
            if pos_a is None or uv_a is None:
                continue
            if "indices" in prim:
                f_idx = _read_indices(prim["indices"]).reshape(-1, 3)
            else:
                f_idx = np.arange(len(pos_a), dtype=np.int64).reshape(-1, 3)
            if "NORMAL" in attrs:
                nrm_a = _read_acc_f32(attrs["NORMAL"], 3)
            else:
                tmp_n = trimesh.Trimesh(vertices=pos_a, faces=f_idx, process=False)
                nrm_a = np.asarray(tmp_n.vertex_normals, dtype=np.float32)
                bv_n = _append_bytes(nrm_a.astype("<f4").tobytes(), target=34962)
                acc_list.append({
                    "bufferView": bv_n,
                    "byteOffset": 0,
                    "componentType": 5126,
                    "count": int(len(nrm_a)),
                    "type": "VEC3",
                    "min": [float(x) for x in nrm_a.min(axis=0)],
                    "max": [float(x) for x in nrm_a.max(axis=0)],
                })
                attrs["NORMAL"] = len(acc_list) - 1
            if nrm_a is None:
                continue
            tmp_m = trimesh.Trimesh(vertices=pos_a, faces=f_idx, vertex_normals=nrm_a, process=False)
            tang = compute_mikk_tangents(tmp_m, uv_a)
            bv_i = _append_bytes(tang.astype("<f4").tobytes(), target=34962)
            acc_list.append({
                "bufferView": bv_i,
                "byteOffset": 0,
                "componentType": 5126,
                "count": int(len(tang)),
                "type": "VEC4",
                "min": [float(x) for x in tang.min(axis=0)],
                "max": [float(x) for x in tang.max(axis=0)],
            })
            attrs["TANGENT"] = len(acc_list) - 1

    # 2. Compression WebP sans coutures (`EXT_texture_webp`) optionnelle sur les images embarquées
    used = set(gltf.get("extensionsUsed", []))
    if webp and gltf.get("images") and gltf.get("textures"):
        from PIL import Image as _PILImage
        for img_def in gltf.get("images", []):
            if "bufferView" not in img_def:
                continue
            bv = bv_list[img_def["bufferView"]]
            s0 = int(bv.get("byteOffset", 0))
            s1 = s0 + int(bv["byteLength"])
            try:
                pil_im = _PILImage.open(io.BytesIO(bytes(bin_data[s0:s1])))
                wbuf = io.BytesIO()
                pil_im.save(wbuf, format="WEBP", quality=90, method=4)
                wbytes = wbuf.getvalue()
                new_bv = _append_bytes(wbytes)
                img_def["bufferView"] = new_bv
                img_def["mimeType"] = "image/webp"
            except Exception:
                continue
        for tex_def in gltf.get("textures", []):
            src_i = tex_def.get("source")
            if src_i is not None and gltf["images"][src_i].get("mimeType") == "image/webp":
                tex_def.setdefault("extensions", {})["EXT_texture_webp"] = {"source": src_i}
                used.add("EXT_texture_webp")

    # 3. Extensions matériaux PBR avancées
    for m_def in gltf.get("materials", []):
        nm = m_def.get("name")
        if nm in mat_exts:
            m_def.setdefault("extensions", {}).update(mat_exts[nm])
            used.update(mat_exts[nm].keys())
    if used:
        gltf["extensionsUsed"] = sorted(used)

    # 4. Nœuds `SOCKET_*` gameplay + pistes `gltf.animations` standards sur `joints` !
    nodes = gltf.setdefault("nodes", [])
    scenes = gltf.setdefault("scenes", [{"nodes": []}])
    root_children = scenes[0].setdefault("nodes", [])
    existing_names = {n.get("name") for n in nodes}

    for sname, sinfo in sockets.items():
        if sname in existing_names:
            continue
        p = sinfo["position"]
        rx, ry, rz = [math.radians(a) * 0.5 for a in sinfo.get("rotation_deg", [0, 0, 0])]
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        quat = [
            sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz,
        ]
        nodes.append({
            "name": sname,
            "translation": [float(p[0]), float(p[1]), float(p[2])],
            "rotation": [round(float(q), 6) for q in quat],
            "extras": {"socket": True},
        })
        root_children.append(len(nodes) - 1)

    if joints:
        anim_channels = []
        anim_samplers = []
        for idx_n, n_def in enumerate(nodes):
            nm = n_def.get("name")
            if nm not in joints:
                continue
            jinfo = joints[nm]
            n_def.setdefault("extras", {})["joint"] = jinfo
            ax = np.asarray(jinfo.get("axis", [0.0, 1.0, 0.0]), dtype=np.float64)
            ax /= np.linalg.norm(ax) + 1e-12
            is_spin = any(k in nm.lower() for k in ("wheel", "axle", "prop", "rotor", "fan", "turret"))
            if is_spin:
                times = np.array([0.0, 0.5, 1.0, 1.5, 2.0], dtype=np.float32)
                angs = [0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi, 2.0 * math.pi]
            else:
                times = np.array([0.0, 0.8, 1.6, 2.4], dtype=np.float32)
                angs = [0.0, math.radians(65.0), math.radians(65.0), 0.0]
            quats = np.array(
                [[ax[0] * math.sin(a / 2), ax[1] * math.sin(a / 2), ax[2] * math.sin(a / 2), math.cos(a / 2)]
                 for a in angs],
                dtype=np.float32,
            )
            bv_t = _append_bytes(times.astype("<f4").tobytes())
            acc_list.append({
                "bufferView": bv_t, "componentType": 5126, "count": len(times), "type": "SCALAR",
                "min": [float(times.min())], "max": [float(times.max())],
            })
            t_acc = len(acc_list) - 1
            bv_q = _append_bytes(quats.astype("<f4").tobytes())
            acc_list.append({
                "bufferView": bv_q, "componentType": 5126, "count": len(quats), "type": "VEC4",
                "min": [float(x) for x in quats.min(axis=0)], "max": [float(x) for x in quats.max(axis=0)],
            })
            q_acc = len(acc_list) - 1
            anim_samplers.append({"input": t_acc, "interpolation": "LINEAR", "output": q_acc})
            anim_channels.append({"sampler": len(anim_samplers) - 1,
                                  "target": {"node": idx_n, "path": "rotation"}})
        if anim_channels:
            gltf.setdefault("animations", []).append({
                "name": "Idle_Action",
                "samplers": anim_samplers,
                "channels": anim_channels,
            })

    # Compacte le chunk binaire `BIN` pour purger tout ancien buffer PNG remplacé par WebP !
    referenced_bvs: set[int] = set()
    for acc_d in gltf.get("accessors", []):
        if "bufferView" in acc_d:
            referenced_bvs.add(int(acc_d["bufferView"]))
    for img_d in gltf.get("images", []):
        if "bufferView" in img_d:
            referenced_bvs.add(int(img_d["bufferView"]))

    compact_bin = bytearray()
    new_bvs = []
    old_to_new: dict[int, int] = {}
    for old_i, bv_d in enumerate(gltf.get("bufferViews", [])):
        if old_i not in referenced_bvs:
            continue
        s0 = int(bv_d.get("byteOffset", 0))
        ln = int(bv_d["byteLength"])
        while len(compact_bin) % 4 != 0:
            compact_bin.append(0)
        nbv = dict(bv_d)
        nbv["byteOffset"] = len(compact_bin)
        compact_bin.extend(bin_data[s0:s0 + ln])
        old_to_new[old_i] = len(new_bvs)
        new_bvs.append(nbv)
    while len(compact_bin) % 4 != 0:
        compact_bin.append(0)
    gltf["bufferViews"] = new_bvs
    for acc_d in gltf.get("accessors", []):
        if "bufferView" in acc_d:
            acc_d["bufferView"] = old_to_new[int(acc_d["bufferView"])]
    for img_d in gltf.get("images", []):
        if "bufferView" in img_d:
            img_d["bufferView"] = old_to_new[int(img_d["bufferView"])]
    bin_data = compact_bin

    if gltf.get("buffers"):
        gltf["buffers"][0]["byteLength"] = len(bin_data)
    j_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    pad = (4 - (len(j_bytes) % 4)) % 4
    j_bytes += b" " * pad
    total_len = 12 + 8 + len(j_bytes) + 8 + len(bin_data)
    out = struct.pack("<III", magic, version, total_len)
    out += struct.pack("<II", len(j_bytes), 0x4E4F534A) + j_bytes
    out += struct.pack("<II", len(bin_data), b_type) + bytes(bin_data)
    with open(glb_path, "wb") as fh:
        fh.write(out)
    return glb_path


def capability_report() -> dict:
    """État des dépendances (utilisé par detect_env)."""
    return {
        "numpy": np.__version__,
        "trimesh": trimesh.__version__,
        "manifold3d": HAS_MANIFOLD,
        "shapely": HAS_SHAPELY,
        "csg_engine": CSG_ENGINE if HAS_MANIFOLD else None,
    }
