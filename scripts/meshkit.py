"""
meshkit — boîte à outils géométrique déterministe pour la génération 3D par agent.

Philosophie : l'agent (LLM) raisonne — décomposition de l'objet, proportions,
matériaux — et meshkit exécute la géométrie de façon déterministe et étanche.

Conventions :
  * unités : mètres
  * axe vertical : Z (les objets "posés" au sol ont leur base à z=0)
  * face avant d'un objet : vers -Y
  * tout ce qui est destiné à l'impression 3D doit rester watertight
    (les opérations CSG via manifold3d garantissent l'étanchéité)

Dépendances : numpy, trimesh>=4, manifold3d (CSG), shapely (extrusions).
Optionnel : usd-core (export USDZ natif).
"""
from __future__ import annotations

import math
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
    if arr.max() > 1.001:
        arr = arr / 255.0
    return np.clip(arr, 0.0, 1.0)


class Material:
    """Matériau PBR simplifié (baseColor, metallic, roughness, opacity, emissive)."""

    def __init__(self, name, color, metallic=0.0, roughness=0.5,
                 opacity=1.0, emissive=None):
        self.name = re.sub(r"[^A-Za-z0-9_]", "_", str(name))
        self.color = hex_rgb(color)
        self.metallic = float(np.clip(metallic, 0.0, 1.0))
        self.roughness = float(np.clip(roughness, 0.02, 1.0))
        self.opacity = float(np.clip(opacity, 0.02, 1.0))
        self.emissive = hex_rgb(emissive) if emissive is not None else None

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
        if alpha < 0.999:
            mat_pbr.alphaMode = "BLEND"
        if self.emissive is not None:
            mat_pbr.emissiveFactor = [float(self.emissive[0]),
                                      float(self.emissive[1]),
                                      float(self.emissive[2])]
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
    def plastic(color="#c8c8c8", roughness=0.35):
        return Material("plastic", color, roughness=roughness)

    @staticmethod
    def ceramic(color="#e8e4dc", roughness=0.15):
        return Material("ceramic", color, roughness=roughness)

    @staticmethod
    def glass(color="#cfe8ef", opacity=0.35, roughness=0.05):
        return Material("glass", color, roughness=roughness, opacity=opacity)

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
    """Cône plein (anneau + apex, sans faces dégénérées), base z=0."""
    n = _s(sections)
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rr = float(r)
    ring = np.column_stack([rr * np.cos(th), rr * np.sin(th), np.zeros(n)])
    verts = np.vstack([[0, 0, 0.0], ring, [[0, 0, float(h)]]])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([0, 1 + j, 1 + i])        # fond
        faces.append([1 + i, 1 + j, n + 1])    # flanc vers l'apex
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
    """Anneau plein (bague) : cylindre creux, étanche."""
    prof = [(r_in, 0), (r_out, 0), (r_out, h), (r_in, h)]
    return lathe(prof, sections=sections, smooth=False)


def capsule(r, h_cyl, sections=32) -> trimesh.Trimesh:
    """Capsule verticale (cylindre + 2 hémisphères), hauteur totale = h_cyl + 2r."""
    m = trimesh.creation.capsule(radius=r, height=h_cyl,
                                 count=[_s(sections), max(8, _s(sections) // 2)])
    m.apply_translation([0, 0, h_cyl / 2 + r])
    return _finish(m)


def lathe(profile, sections=48, smooth=True, close=True) -> trimesh.Trimesh:
    """
    Solide de révolution : profile = [(r, z), ...] en ordre z croissant
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
# Builder — assemblage multi-pièces avec matériaux
# --------------------------------------------------------------------------- #

class Builder:
    """
    Assemble des pièces (mesh + matériau) en une scène exportable.

    Exemple :
        b = Builder("mug")
        b.add(mk.lathe([...]), mk.mat.ceramic("#fff"), name="body")
        b.add(handle, mk.mat.ceramic("#fff"), name="handle", at=(0.04, 0, 0.04))
    """

    def __init__(self, name, params=None):
        self.name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
        self.params = dict(params or {})
        self._parts = []  # (mesh, Material|None, label)

    def add(self, mesh, material: Material | None = None, name=None,
            at=None, rot=None):
        """
        rot : (rx_deg, ry_deg, rz_deg) appliqué d'abord (autour de l'origine),
        puis translation at=(x,y,z). Retourne le mesh (chaînage possible).
        """
        if rot is not None:
            rx, ry, rz = rot
            if rx: rot_x(mesh, rx)
            if ry: rot_y(mesh, ry)
            if rz: rot_z(mesh, rz)
        if at is not None:
            place(mesh, *at)
        self._parts.append((mesh, material, name or f"part{len(self._parts)}"))
        return mesh

    @property
    def parts(self):
        return list(self._parts)

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

    def scene(self) -> trimesh.Scene:
        geoms = {}
        for i, (mesh, material, label) in enumerate(self._parts):
            gname = f"{label}_{i}"
            g = mesh.copy()
            if material is not None:
                g.visual = trimesh.visual.TextureVisuals(material=material.to_pbr())
            geoms[gname] = g
        return trimesh.Scene(geoms, base_frame=self.name)

    def union_solid(self) -> trimesh.Trimesh:
        """Fusionne toutes les pièces en un seul solide (export STL)."""
        meshes = [p[0].copy() for p in self._parts]
        if len(meshes) == 1:
            return meshes[0]
        if HAS_MANIFOLD:
            try:
                out = union(meshes)
                # Nettoyage des slivers (faces d'aire quasi nulle créées par le
                # CSG sur intersections tangentes) : ils cassent l'étanchéité
                # après passage en float32 (STL).
                keep = out.area_faces > 1e-10
                if not keep.all():
                    out.update_faces(keep)
                    out.merge_vertices()
                    out.fill_holes()
                return _finish(out)
            except Exception:
                pass
        merged = trimesh.util.concatenate(meshes)
        return _finish(merged)


# --------------------------------------------------------------------------- #
# Export OBJ + MTL (matériaux Phong dérivés du PBR)
# --------------------------------------------------------------------------- #

def export_obj_with_mtl(scene: trimesh.Scene, obj_path: str) -> str:
    """Écrit .obj + .mtl avec groupes par matériau. Retourne le chemin .obj."""
    import os
    base = os.path.splitext(obj_path)[0]
    mtl_path = base + ".mtl"
    mtl_name = os.path.basename(mtl_path)
    lines_obj = ["# généré par 3d-forge (meshkit)", "mtllib " + mtl_name]
    lines_mtl = ["# généré par 3d-forge (meshkit)"]
    seen_mats = set()
    v_off = vn_off = 0
    for gname, geom in scene.geometry.items():
        material = getattr(geom.visual, "material", None)
        mname = getattr(material, "name", None) or f"m_{gname}"
        mname = re.sub(r"[^A-Za-z0-9_]", "_", mname)
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
            lines_mtl += [f"newmtl {mname}",
                          f"Kd {col[0]:.4f} {col[1]:.4f} {col[2]:.4f}",
                          "Ka 0.10 0.10 0.10",
                          f"Ks {ks:.3f} {ks:.3f} {ks:.3f}",
                          f"Ns {ns:.1f}", "Ni 1.45",
                          f"d {opacity:.3f}", "illum 2"]
        v = geom.vertices
        vn = geom.vertex_normals
        f = geom.faces + 1
        lines_obj.append(f"o {gname}")
        lines_obj += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in v]
        lines_obj += [f"vn {x:.4f} {y:.4f} {z:.4f}" for x, y, z in vn]
        lines_obj.append("usemtl " + mname)
        lines_obj += [f"f {a + v_off}//{a + vn_off} {b + v_off}//{b + vn_off} "
                      f"{c + v_off}//{c + vn_off}" for a, b, c in f]
        v_off += len(v)
        vn_off += len(vn)
    with open(obj_path, "w") as fo:
        fo.write("\n".join(lines_obj) + "\n")
    with open(mtl_path, "w") as fm:
        fm.write("\n".join(lines_mtl) + "\n")
    return obj_path


def capability_report() -> dict:
    """État des dépendances (utilisé par detect_env)."""
    return {
        "numpy": np.__version__,
        "trimesh": trimesh.__version__,
        "manifold3d": HAS_MANIFOLD,
        "shapely": HAS_SHAPELY,
        "csg_engine": CSG_ENGINE if HAS_MANIFOLD else None,
    }
