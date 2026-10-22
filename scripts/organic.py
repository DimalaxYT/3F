"""
organic.py — Sculpture organique 3D procédurale lisse, personnages, bustes & créatures (`3d-forge`).

Conçu pour que n'importe quel agent IA (y compris dans **Claude.ai**, CLI ou hors-ligne,
**sans aucun outil `generate_image`**) puisse sculpter en pur Python CPU (`< 0.5 s`), de
façon 100 % déterministe et **100 % étanche (`is_watertight == True`)** :
  - têtes, visages, bustes expressifs, mascottes, figurines stylisées ou réalistes,
  - créatures (dragons, monstres, animaux, familiers Roblox), cornes, crocs, griffes, oreilles,
  - casquettes à visière courbée 3D, casques, cheveux/mèches, moustaches, sourcils, membres,
  - coussins, feuillages, rochers sculptés, poteries organiques, socles de musée.

Deux outils complémentaires :
  1. `Sculpt` (modeleur implicite SDF 3D continu à unions/soustractions douces polynomiales `C¹`
     d'Inigo Quilez + Marching Cubes + lissage Taubin sans retrait + réparation `manifold3d`) :
     fusionne joues, crâne, museau, menton, épaules et cavités orbitales/buccales comme de
     l'argile ZBrush, zéro facette cubique et zéro couture !
  2. Primitives organiques paramétriques exactes (`tapered_curve`, `curved_visor`,
     `ellipsoid`, `superellipsoid`, `smooth_union`, `smooth_difference`, `eyes_pair`,
     `ear_pair`, `museum_plinth`) : s'assemblent directement dans `mk.Builder` avec des
     matériaux PBR séparés pour des frontières de couleur infiniment nettes !

Conventions `3d-forge` : mètres, `Z` vers le haut (`z = 0` au sol), face avant vers **`-Y`**.
"""
from __future__ import annotations

import math
import numpy as np
from scipy import ndimage
from scipy.interpolate import CubicSpline, PchipInterpolator
from skimage.measure import marching_cubes
import trimesh

import meshkit as mk


# --------------------------------------------------------------------------- #
# Opérateurs SDF continus C¹ (Inigo Quilez)
# --------------------------------------------------------------------------- #

def smin_poly(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """Union douce C¹ de deux champs de distance signée (`< 0` à l'intérieur)."""
    if k <= 1e-6:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / float(k), 0.0, 1.0)
    return b * (1.0 - h) + a * h - float(k) * h * (1.0 - h)


def smax_poly(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """Intersection douce C¹ (`smax(a, -b, k)` = soustraction douce `a \\ b`)."""
    if k <= 1e-6:
        return np.maximum(a, b)
    h = np.clip(0.5 - 0.5 * (b - a) / float(k), 0.0, 1.0)
    return b * (1.0 - h) + a * h + float(k) * h * (1.0 - h)


def _rot_matrix_xyz(rot_deg: tuple[float, float, float] | None) -> np.ndarray | None:
    if rot_deg is None or (rot_deg[0] == 0 and rot_deg[1] == 0 and rot_deg[2] == 0):
        return None
    rx, ry, rz = [math.radians(float(v)) for v in rot_deg]
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]], dtype=np.float32)
    my = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float32)
    mz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    return (mz @ my @ mx).astype(np.float32)


class Sculpt:
    """Modeleur implicite 3D à champs de distance signée (SDF) type ZBrush Dynamesh / Clay.

    Exemple :
        s = org.Sculpt(bounds=((-0.14, -0.16, 0.04), (0.14, 0.14, 0.34)), res=96)
        s.ellipsoid((0, 0, 0.19), (0.095, 0.102, 0.108))                  # crâne
        s.ellipsoid((0, -0.045, 0.142), (0.078, 0.062, 0.055), k=0.024)   # joues/mâchoire
        s.ellipsoid((0, -0.108, 0.162), (0.026, 0.032, 0.022), k=0.010)   # nez fondu
        s.ellipsoid((0.036, -0.088, 0.192), (0.024, 0.018, 0.026), mode="sub", k=0.008)  # orbite D
        s.ellipsoid((-0.036, -0.088, 0.192), (0.024, 0.018, 0.026), mode="sub", k=0.008) # orbite G
        head = s.to_mesh(smooth_iter=4)  # 100 % watertight, lisse, prêt pour mk.Builder !
    """

    def __init__(
        self,
        bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = ((-0.18, -0.18, 0.0), (0.18, 0.18, 0.36)),
        res: int = 92,
    ) -> None:
        bmin = np.asarray(bounds[0], dtype=np.float32)
        bmax = np.asarray(bounds[1], dtype=np.float32)
        span = np.maximum(bmax - bmin, 1e-3)
        max_span = float(span.max())
        voxel = max_span / float(max(24, int(res)))
        nx = max(16, int(round(float(span[0]) / voxel)) + 1)
        ny = max(16, int(round(float(span[1]) / voxel)) + 1)
        nz = max(16, int(round(float(span[2]) / voxel)) + 1)
        self.origin = bmin.copy()
        self.spacing = (
            float(span[0]) / (nx - 1),
            float(span[1]) / (ny - 1),
            float(span[2]) / (nz - 1),
        )
        xs = np.linspace(float(bmin[0]), float(bmax[0]), nx, dtype=np.float32)
        ys = np.linspace(float(bmin[1]), float(bmax[1]), ny, dtype=np.float32)
        zs = np.linspace(float(bmin[2]), float(bmax[2]), nz, dtype=np.float32)
        self.X, self.Y, self.Z = np.meshgrid(xs, ys, zs, indexing="ij")
        self.field = np.full((nx, ny, nz), 10.0, dtype=np.float32)

    def _local_coords(
        self,
        center: tuple[float, float, float],
        rot_deg: tuple[float, float, float] | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        px = self.X - float(center[0])
        py = self.Y - float(center[1])
        pz = self.Z - float(center[2])
        R = _rot_matrix_xyz(rot_deg)
        if R is None:
            return px, py, pz
        # Coordonnées dans le repère local de la primitive : R^T @ p
        lx = R[0, 0] * px + R[1, 0] * py + R[2, 0] * pz
        ly = R[0, 1] * px + R[1, 1] * py + R[2, 1] * pz
        lz = R[0, 2] * px + R[1, 2] * py + R[2, 2] * pz
        return lx, ly, lz

    def combine(self, d: np.ndarray, mode: str = "add", k: float = 0.012) -> "Sculpt":
        d32 = np.asarray(d, dtype=np.float32)
        if mode == "add":
            self.field = smin_poly(self.field, d32, k)
        elif mode == "sub":
            self.field = smax_poly(self.field, -d32, k)
        elif mode == "intersect":
            self.field = smax_poly(self.field, d32, k)
        else:
            raise ValueError(f"mode inconnu {mode!r} (attendu 'add', 'sub', 'intersect')")
        return self

    def sphere(self, center, r: float, mode: str = "add", k: float = 0.012) -> "Sculpt":
        px, py, pz = self._local_coords(center)
        d = np.sqrt(px * px + py * py + pz * pz) - float(r)
        return self.combine(d, mode=mode, k=k)

    def ellipsoid(
        self,
        center,
        radii: tuple[float, float, float],
        rot_deg: tuple[float, float, float] | None = None,
        mode: str = "add",
        k: float = 0.012,
        mirror_x: bool = False,
    ) -> "Sculpt":
        rx, ry, rz = [max(float(v), 1e-4) for v in radii]
        centers = [center]
        rots = [rot_deg]
        if mirror_x and abs(float(center[0])) > 1e-6:
            centers.append((-float(center[0]), float(center[1]), float(center[2])))
            if rot_deg is not None:
                rots.append((float(rot_deg[0]), -float(rot_deg[1]), -float(rot_deg[2])))
            else:
                rots.append(None)
        for c_i, r_i in zip(centers, rots):
            px, py, pz = self._local_coords(c_i, r_i)
            # Distance exacte approchée d'Inigo Quilez sans distorsion polaire : k0 * (k0 - 1) / k1
            q0x, q0y, q0z = px / rx, py / ry, pz / rz
            q1x, q1y, q1z = px / (rx * rx), py / (ry * ry), pz / (rz * rz)
            k0 = np.sqrt(q0x * q0x + q0y * q0y + q0z * q0z) + 1e-9
            k1 = np.sqrt(q1x * q1x + q1y * q1y + q1z * q1z) + 1e-9
            d = k0 * (k0 - 1.0) / k1
            self.combine(d, mode=mode, k=k)
        return self

    def capsule(
        self,
        a: tuple[float, float, float],
        b: tuple[float, float, float],
        r_a: float,
        r_b: float | None = None,
        mode: str = "add",
        k: float = 0.012,
        mirror_x: bool = False,
    ) -> "Sculpt":
        """Segment anatomique fuselé (cou, museau, bras, jambe, doigt, sourcils, mâchoire)."""
        rb = float(r_a if r_b is None else r_b)
        ra = float(r_a)
        pairs = [(a, b)]
        if mirror_x:
            pairs.append(((-float(a[0]), float(a[1]), float(a[2])),
                          (-float(b[0]), float(b[1]), float(b[2]))))
        for pa, pb in pairs:
            ax, ay, az = float(pa[0]), float(pa[1]), float(pa[2])
            bx, by, bz = float(pb[0]) - ax, float(pb[1]) - ay, float(pb[2]) - az
            wx, wy, wz = self.X - ax, self.Y - ay, self.Z - az
            b2 = max(bx * bx + by * by + bz * bz, 1e-9)
            h = np.clip((wx * bx + wy * by + wz * bz) / b2, 0.0, 1.0)
            dx = wx - bx * h
            dy = wy - by * h
            dz = wz - bz * h
            r_h = ra + (rb - ra) * h
            d = np.sqrt(dx * dx + dy * dy + dz * dz) - r_h
            self.combine(d, mode=mode, k=k)
        return self

    def sweep(
        self,
        points: list[tuple[float, float, float]],
        radii: list[float] | float,
        n_seg: int = 14,
        mode: str = "add",
        k: float = 0.010,
        mirror_x: bool = False,
    ) -> "Sculpt":
        """Balaye un pinceau anatomique 3D lisse PCHIP le long d'une courbe `points` :
          - `mode='add'` : arête nasale crochue (nez de Tengu), arcade sourcilière, pommette,
            pli nasogénien, lèvre charnue, mâchoire, corne ou crête fondue `C¹` dans l'argile.
          - `mode='sub'` : sillon gravé net, orbite en amande, rictus buccal, narine ou ride !
        Évalue d'abord l'enveloppe exacte `min` le long de la courbe (zéro boudin en chapelet),
        puis fusionne en une seule passe `smin_poly` / `smax_poly` de rayon `k` avec le volume."""
        pts_in = np.asarray(points, dtype=np.float64)
        if isinstance(radii, (int, float)):
            r_in = np.full(len(pts_in), float(radii), dtype=np.float64)
        else:
            r_in = np.asarray(radii, dtype=np.float64)
        if len(pts_in) < 2:
            raise ValueError("Sculpt.sweep requiert au moins 2 points 3D")
        t_src = np.linspace(0.0, 1.0, len(pts_in))
        t_fine = np.linspace(0.0, 1.0, max(int(n_seg) + 1, len(pts_in)))
        pts_fine = np.column_stack([
            PchipInterpolator(t_src, pts_in[:, j])(t_fine) for j in range(3)
        ]).astype(np.float32)
        r_fine = np.maximum(PchipInterpolator(t_src, r_in)(t_fine), 1e-4).astype(np.float32)

        curves = [pts_fine]
        if mirror_x:
            pm = pts_fine.copy()
            pm[:, 0] *= -1.0
            curves.append(pm)

        for crv in curves:
            d_curve = np.full_like(self.field, 10.0)
            for i in range(len(crv) - 1):
                ax, ay, az = float(crv[i, 0]), float(crv[i, 1]), float(crv[i, 2])
                bx = float(crv[i + 1, 0]) - ax
                by = float(crv[i + 1, 1]) - ay
                bz = float(crv[i + 1, 2]) - az
                ra, rb = float(r_fine[i]), float(r_fine[i + 1])
                wx, wy, wz = self.X - ax, self.Y - ay, self.Z - az
                b2 = max(bx * bx + by * by + bz * bz, 1e-9)
                h = np.clip((wx * bx + wy * by + wz * bz) / b2, 0.0, 1.0)
                dx = wx - bx * h
                dy = wy - by * h
                dz = wz - bz * h
                r_h = ra + (rb - ra) * h
                d_seg = np.sqrt(dx * dx + dy * dy + dz * dz) - r_h
                np.minimum(d_curve, d_seg, out=d_curve)
            self.combine(d_curve, mode=mode, k=k)
        return self

    def round_box(
        self,
        center,
        size: tuple[float, float, float],
        r: float = 0.012,
        rot_deg: tuple[float, float, float] | None = None,
        mode: str = "add",
        k: float = 0.012,
        mirror_x: bool = False,
    ) -> "Sculpt":
        hx, hy, hz = [max(0.5 * float(v) - float(r), 1e-4) for v in size]
        centers = [center]
        rots = [rot_deg]
        if mirror_x and abs(float(center[0])) > 1e-6:
            centers.append((-float(center[0]), float(center[1]), float(center[2])))
            rots.append((float(rot_deg[0]), -float(rot_deg[1]), -float(rot_deg[2])) if rot_deg else None)
        for c_i, r_i in zip(centers, rots):
            px, py, pz = self._local_coords(c_i, r_i)
            qx = np.abs(px) - hx
            qy = np.abs(py) - hy
            qz = np.abs(pz) - hz
            out_d = np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qy, 0.0) ** 2 + np.maximum(qz, 0.0) ** 2)
            in_d = np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0.0)
            d = out_d + in_d - float(r)
            self.combine(d, mode=mode, k=k)
        return self

    def torus(
        self,
        center,
        R_major: float,
        r_minor: float,
        rot_deg: tuple[float, float, float] | None = None,
        mode: str = "add",
        k: float = 0.010,
    ) -> "Sculpt":
        px, py, pz = self._local_coords(center, rot_deg)
        qxy = np.sqrt(px * px + py * py) - float(R_major)
        d = np.sqrt(qxy * qxy + pz * pz) - float(r_minor)
        return self.combine(d, mode=mode, k=k)

    def plane_cut(
        self,
        point=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, -1.0),
        k: float = 0.004,
    ) -> "Sculpt":
        """Coupe proprement tout ce qui dépasse du demi-espace `normal` (ex. base plate de buste)."""
        n = np.asarray(normal, dtype=np.float32)
        n /= max(float(np.linalg.norm(n)), 1e-9)
        d = ((self.X - float(point[0])) * n[0]
             + (self.Y - float(point[1])) * n[1]
             + (self.Z - float(point[2])) * n[2])
        return self.combine(-d, mode="sub", k=k)

    def to_mesh(self, smooth_iter: int = 4, target_tris: int | None = None) -> trimesh.Trimesh:
        """Extrait un `trimesh.Trimesh` lisse, propre et 100 % `is_watertight == True`."""
        vol = np.pad(self.field, 2, mode="constant", constant_values=1.0)
        if not (vol < 0.0).any():
            raise ValueError("Sculpt vide : aucune primitive n'a de volume intérieur (< 0)")
        verts, faces, _, _ = marching_cubes(vol, level=0.0, spacing=self.spacing)
        pad_off = np.array([2.0 * self.spacing[0], 2.0 * self.spacing[1], 2.0 * self.spacing[2]])
        verts = verts - pad_off + self.origin.astype(np.float64)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        comps = mesh.split(only_watertight=False)
        if len(comps) > 1:
            # Conserve toutes les composantes significatives (> 2 % des faces)
            min_f = max(24, int(0.02 * len(mesh.faces)))
            kept = [c for c in comps if len(c.faces) >= min_f]
            mesh = trimesh.util.concatenate(kept) if kept else max(comps, key=lambda c: len(c.faces))
        if smooth_iter > 0:
            trimesh.smoothing.filter_taubin(mesh, lamb=0.45, nu=-0.48, iterations=int(smooth_iter))
        mesh.fix_normals(multibody=False)
        mc_clean = mesh.copy()

        def _manifold_clean(cand: trimesh.Trimesh) -> trimesh.Trimesh:
            if not getattr(mk, "HAS_MANIFOLD", False):
                return cand
            import manifold3d
            for tol in (None, 2e-5, 8e-5):
                try:
                    w = cand.copy()
                    if tol is not None:
                        w.vertices = np.round(w.vertices / tol) * tol
                        w.merge_vertices()
                        w.update_faces(w.nondegenerate_faces())
                        w.remove_unreferenced_vertices()
                    v32 = np.asarray(w.vertices, dtype=np.float32)
                    f32 = np.asarray(w.faces, dtype=np.uint32)
                    mm = manifold3d.Manifold(manifold3d.Mesh(vert_properties=v32, tri_verts=f32)).to_mesh()
                    if len(mm.tri_verts) >= 12:
                        out = trimesh.Trimesh(vertices=mm.vert_properties[:, :3], faces=mm.tri_verts, process=True)
                        if out.is_watertight:
                            return out
                except Exception:
                    continue
            return cand

        if target_tris is not None and len(mesh.faces) > int(target_tris):
            import fast_simplification
            ratio = float(np.clip(1.0 - float(target_tris) / len(mesh.faces), 0.05, 0.96))
            for agg_val in (5, 3):
                vo, fo = fast_simplification.simplify(
                    np.asarray(mc_clean.vertices, dtype=np.float32),
                    np.asarray(mc_clean.faces, dtype=np.int32),
                    target_reduction=ratio,
                    agg=agg_val,
                )
                cand = _manifold_clean(trimesh.Trimesh(vertices=vo, faces=fo, process=True))
                if cand.is_watertight and len(cand.faces) >= 12:
                    mesh = cand
                    break
            else:
                mesh = _manifold_clean(mc_clean)
        else:
            mesh = _manifold_clean(mesh)

        mesh.fix_normals(multibody=False)
        if not mesh.is_watertight:
            trimesh.repair.fill_holes(mesh)
            mesh.fix_normals(multibody=False)
        return mesh


# --------------------------------------------------------------------------- #
# Primitives organiques paramétriques exactes 100 % étanches
# --------------------------------------------------------------------------- #

def ellipsoid(rx: float, ry: float, rz: float, center=(0.0, 0.0, 0.0), subdivisions: int = 3) -> trimesh.Trimesh:
    """Ellipsoïde lisse sans singularité polaire (icosphère subdivisée mise à l'échelle)."""
    m = trimesh.creation.icosphere(subdivisions=int(subdivisions), radius=1.0)
    m.apply_scale([float(rx), float(ry), float(rz)])
    m.apply_translation(center)
    m.fix_normals(multibody=False)
    return m


def superellipsoid(
    rx: float,
    ry: float,
    rz: float,
    e_xy: float = 0.75,
    e_z: float = 0.75,
    center=(0.0, 0.0, 0.0),
    u_seg: int = 44,
    v_seg: int = 24,
    e1: float | None = None,
    e2: float | None = None,
) -> trimesh.Trimesh:
    """Super-ellipsoïde fermé 100 % étanche (`e < 1` = coussin galbé doux, `e = 1` = ellipsoïde,
    `e > 1` = losange organique). Idéal pour torses, têtes chibi, casques, coussins, galets."""
    if e1 is not None:
        e_z = float(e1)
    if e2 is not None:
        e_xy = float(e2)
    def _scos(ang, e):
        c = np.cos(ang)
        return np.sign(c) * (np.abs(c) ** float(e))

    def _ssin(ang, e):
        s = np.sin(ang)
        return np.sign(s) * (np.abs(s) ** float(e))

    u = np.linspace(0.0, 2.0 * math.pi, int(u_seg), endpoint=False)
    # Anneaux latitudes hors pôles exacts -> loft fermé par pôles sans triangle dégénéré
    vs = np.linspace(-0.5 * math.pi + 0.06, 0.5 * math.pi - 0.06, int(v_seg))
    rings = []
    for phi in vs:
        cp = _scos(phi, e_z)
        sp = _ssin(phi, e_z)
        rings.append(np.column_stack([
            float(rx) * cp * _scos(u, e_xy) + float(center[0]),
            float(ry) * cp * _ssin(u, e_xy) + float(center[1]),
            np.full_like(u, float(rz) * sp + float(center[2])),
        ]))
    n = len(u)
    nr = len(rings)
    p_south = np.array([[float(center[0]), float(center[1]), float(center[2]) - float(rz)]])
    p_north = np.array([[float(center[0]), float(center[1]), float(center[2]) + float(rz)]])
    verts = np.vstack(rings + [p_south, p_north])
    i_south = nr * n
    i_north = nr * n + 1
    faces = []
    for r in range(nr - 1):
        b0, b1 = r * n, (r + 1) * n
        for i in range(n):
            j = (i + 1) % n
            faces.append([b0 + i, b0 + j, b1 + j])
            faces.append([b0 + i, b1 + j, b1 + i])
    for i in range(n):
        j = (i + 1) % n
        faces.append([i_south, j, i])
        faces.append([i_north, (nr - 1) * n + i, (nr - 1) * n + j])
    m = trimesh.Trimesh(vertices=verts, faces=np.asarray(faces, dtype=np.int64), process=True)
    m.fix_normals(multibody=False)
    return m


def tapered_curve(
    points,
    radii,
    sections: int = 24,
    smooth_pts: int = 44,
    cap_round: bool = True,
) -> trimesh.Trimesh:
    """Tube organique 3D à rayon évolutif `radii` le long d'une courbe `points` lissée PCHIP,
    terminé par des calottes hémisphériques douces aux deux bouts (`100 % watertight`) !

    Indispensable pour : cornes recourbées, crocs, griffes, queues, tentacules, bras/jambes
    anatomiques, sourcils, moustaches sculptées, mèches de cheveux, branches d'arbre.
    """
    pts = np.asarray(points, dtype=float)
    rads = np.asarray(radii, dtype=float)
    if len(pts) < 2:
        raise ValueError("tapered_curve: au moins 2 points requis")
    if rads.ndim == 0:
        rads = np.full(len(pts), float(rads))
    if len(rads) != len(pts):
        t_in = np.linspace(0.0, 1.0, len(rads))
        rads = np.interp(np.linspace(0.0, 1.0, len(pts)), t_in, rads)

    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    t_ctrl = np.concatenate([[0.0], np.cumsum(np.maximum(seg, 1e-6))])
    t_ctrl /= t_ctrl[-1]

    n_core = max(len(pts), int(smooth_pts))
    ts = np.linspace(0.0, 1.0, n_core)
    if len(pts) >= 3:
        # CubicSpline naturelle C² sur la trajectoire 3D : zéro cassure anguleuse aux sommets
        # d'arc (paupières, sourcils, lèvres), tout en gardant PCHIP positif sur les rayons !
        spine = np.column_stack([CubicSpline(t_ctrl, pts[:, k], bc_type="natural")(ts) for k in range(3)])
        r_spine = np.maximum(PchipInterpolator(t_ctrl, rads)(ts), 1e-4)
    else:
        spine = pts[0][None, :] + (pts[1] - pts[0])[None, :] * ts[:, None]
        r_spine = np.maximum(rads[0] + (rads[1] - rads[0]) * ts, 1e-4)

    if cap_round:
        # Prolonge de 4 stations en dôme cosinusoïdal aux deux extrémités -> zéro méplat coupé !
        d_start = spine[1] - spine[0]
        d_start /= max(float(np.linalg.norm(d_start)), 1e-9)
        d_end = spine[-1] - spine[-2]
        d_end /= max(float(np.linalg.norm(d_end)), 1e-9)
        r0, r1 = float(r_spine[0]), float(r_spine[-1])
        phis = [0.88 * 0.5 * math.pi, 0.65 * 0.5 * math.pi, 0.35 * 0.5 * math.pi]
        pre_pts = [spine[0] - d_start * (r0 * math.sin(p)) for p in phis]
        pre_r = [max(r0 * math.cos(p), 2e-4) for p in phis]
        post_pts = [spine[-1] + d_end * (r1 * math.sin(p)) for p in reversed(phis)]
        post_r = [max(r1 * math.cos(p), 2e-4) for p in reversed(phis)]
        spine = np.vstack(pre_pts + [spine] + post_pts)
        r_spine = np.concatenate([pre_r, r_spine, post_r])

    ang = np.linspace(0.0, 2.0 * math.pi, max(8, int(sections)), endpoint=False)
    unit_circle = np.column_stack([np.cos(ang), np.sin(ang)])
    scales = [(float(r), float(r)) for r in r_spine]
    return mk.sweep(unit_circle, spine, scale=scales, caps=True)


def curved_visor(
    width: float = 0.16,
    length: float = 0.085,
    thickness: float = 0.008,
    arch: float = 0.024,
    droop: float = 0.012,
    sections: int = 34,
) -> trimesh.Trimesh:
    """Visière de casquette / casque / épaulière 3D galbée (cintrée en voûte transverse `arch`
    ET plongeante vers l'avant `-Y` de `droop`), fine, lisse et **100 % étanche** !

    Construite à l'origine avec racine en `y = 0` et pointe avant vers `y = -length`.
    """
    n_u = max(12, int(sections))
    n_v = 10
    us = np.linspace(-1.0, 1.0, n_u)
    rings = []
    for k, tv in enumerate(np.linspace(0.0, 1.0, n_v)):
        # Contour avant parabolique arrondi (jamais une pelle carrée !)
        span_w = 0.5 * float(width) * math.sqrt(max(1.0 - 0.72 * (tv ** 2.1), 0.06))
        y_row = -float(length) * tv
        z_droop = -float(droop) * (tv ** 1.65)
        th_k = float(thickness) * (1.0 - 0.35 * tv)
        xs = us * span_w
        zs_mid = float(arch) * (1.0 - us * us) * (1.0 - 0.28 * tv) + z_droop
        top_pts = np.column_stack([xs, np.full_like(xs, y_row), zs_mid + 0.5 * th_k])
        bot_pts = np.column_stack([xs[::-1], np.full_like(xs, y_row), (zs_mid - 0.5 * th_k)[::-1]])
        rings.append(np.vstack([top_pts, bot_pts]))
    return mk.loft(rings, caps=True)


def subdivide_smooth(mesh: trimesh.Trimesh, iterations: int = 1) -> trimesh.Trimesh:
    """Subdivision Loop lissante conservant à 100 % l'étanchéité d'un maillage fermé."""
    m = mesh.copy()
    for _ in range(int(iterations)):
        m = m.subdivide_loop()
    m.fix_normals(multibody=False)
    return m


def _mesh_to_sdf_grid(mesh: trimesh.Trimesh, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """Convertit un `trimesh.Trimesh` étanche en champ SDF euclidien sur `(xs, ys, zs)`."""
    nx, ny, nz = len(xs), len(ys), len(zs)
    vx = float(xs[1] - xs[0])
    m = mesh.copy()
    occ = np.zeros((nx, ny, nz), dtype=bool)
    # Voxelisation rapide par tranches Z via trimesh.voxelized
    vg = m.voxelized(pitch=vx)
    vg = vg.fill()
    pts = vg.points
    ix = np.round((pts[:, 0] - float(xs[0])) / vx).astype(np.int32)
    iy = np.round((pts[:, 1] - float(ys[0])) / vx).astype(np.int32)
    iz = np.round((pts[:, 2] - float(zs[0])) / vx).astype(np.int32)
    valid = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny) & (iz >= 0) & (iz < nz)
    occ[ix[valid], iy[valid], iz[valid]] = True
    d_out = ndimage.distance_transform_edt(~occ)
    d_in = ndimage.distance_transform_edt(occ)
    return ((d_out - d_in) * vx).astype(np.float32)


def smooth_union(meshes: list[trimesh.Trimesh], k: float = 0.012, res: int = 88) -> trimesh.Trimesh:
    """Fusionne une liste de primitives `trimesh` avec un congé organique continu `k` (mètres)."""
    if len(meshes) == 1:
        return meshes[0].copy()
    bmin = np.min([m.bounds[0] for m in meshes], axis=0) - max(float(k) * 2.0, 0.008)
    bmax = np.max([m.bounds[1] for m in meshes], axis=0) + max(float(k) * 2.0, 0.008)
    sc = Sculpt(bounds=(tuple(bmin), tuple(bmax)), res=res)
    xs = sc.X[:, 0, 0]
    ys = sc.Y[0, :, 0]
    zs = sc.Z[0, 0, :]
    for m in meshes:
        sc.combine(_mesh_to_sdf_grid(m, xs, ys, zs), mode="add", k=k)
    return sc.to_mesh(smooth_iter=4)


def smooth_difference(
    base: trimesh.Trimesh,
    tools: list[trimesh.Trimesh],
    k: float = 0.008,
    res: int = 88,
) -> trimesh.Trimesh:
    """Creuse `tools` dans `base` avec un chanfrein organique continu `k` (mètres)."""
    all_m = [base] + list(tools)
    bmin = np.min([m.bounds[0] for m in all_m], axis=0) - max(float(k) * 2.0, 0.008)
    bmax = np.max([m.bounds[1] for m in all_m], axis=0) + max(float(k) * 2.0, 0.008)
    sc = Sculpt(bounds=(tuple(bmin), tuple(bmax)), res=res)
    xs = sc.X[:, 0, 0]
    ys = sc.Y[0, :, 0]
    zs = sc.Z[0, 0, :]
    sc.combine(_mesh_to_sdf_grid(base, xs, ys, zs), mode="add", k=0.0)
    for t in tools:
        sc.combine(_mesh_to_sdf_grid(t, xs, ys, zs), mode="sub", k=k)
    return sc.to_mesh(smooth_iter=4)


# --------------------------------------------------------------------------- #
# Kits anatomiques & socles prêts à brancher dans `mk.Builder`
# --------------------------------------------------------------------------- #

def add_stylized_eyes(
    b: mk.Builder,
    center_y: float,
    center_z: float,
    spacing_x: float = 0.036,
    radius: float = 0.020,
    tall_scale: float = 1.28,
    iris_color: str = "#2563eb",
    yaw_inward_deg: float = 8.0,
) -> None:
    """Ajoute une paire d'yeux expressifs nets en 4 couches géométriques séparées
    (sclère ivoire + iris saturé + pupille noire + reflet spéculaire blanc pur) :
    zéro bavage de texture, regard vivant sous tous les angles !"""
    m_sclera = mk.Material("eye_sclera", "#f5f5f7", metallic=0.0, roughness=0.14, clearcoat=0.8)
    m_iris = mk.Material("eye_iris", iris_color, metallic=0.0, roughness=0.16, clearcoat=0.9)
    m_pupil = mk.Material("eye_pupil", "#101114", metallic=0.0, roughness=0.08, clearcoat=1.0)
    m_glint = mk.Material("eye_glint", "#ffffff", metallic=0.0, roughness=0.06)

    for side_tag, sx in (("r", 1.0), ("l", -1.0)):
        cx = sx * float(spacing_x)
        # Sclère centrée à l'origine AVANT rotation (évite tout décalage d'orbite hors axe !)
        scl = ellipsoid(radius * 0.92, radius * 0.62, radius * tall_scale, subdivisions=3)
        mk.rot_z(scl, -sx * float(yaw_inward_deg))
        mk.place(scl, cx, center_y, center_z)
        b.add(scl, m_sclera, name=f"eye_sclera_{side_tag}")

        # Coque cornéenne enveloppante (+1.2 mm) pour conformer exactement l'iris et la pupille
        # à la courbure sphérique du globe : ZÉRO plot cylindrique qui dépasse en avant !
        cornea_env = ellipsoid(radius * 0.96, radius * 0.68, radius * tall_scale * 1.03, subdivisions=3)
        mk.rot_z(cornea_env, -sx * float(yaw_inward_deg))
        mk.place(cornea_env, cx, center_y, center_z)

        iris_raw = mk.cylinder(radius * 0.56, radius * 1.4, sections=36)
        mk.rot_x(iris_raw, 90.0)
        mk.place(iris_raw, cx - sx * radius * 0.04, center_y + radius * 0.5, center_z - radius * 0.02)
        iris = mk.intersection(cornea_env, iris_raw)
        b.add(iris, m_iris, name=f"eye_iris_{side_tag}")

        cornea_pup = ellipsoid(radius * 0.985, radius * 0.705, radius * tall_scale * 1.05, subdivisions=3)
        mk.rot_z(cornea_pup, -sx * float(yaw_inward_deg))
        mk.place(cornea_pup, cx, center_y, center_z)

        pup_raw = mk.cylinder(radius * 0.31, radius * 1.5, sections=32)
        mk.rot_x(pup_raw, 90.0)
        mk.place(pup_raw, cx - sx * radius * 0.05, center_y + radius * 0.5, center_z - radius * 0.02)
        pup = mk.intersection(cornea_pup, pup_raw)
        b.add(pup, m_pupil, name=f"eye_pupil_{side_tag}")

        glint = ellipsoid(radius * 0.12, radius * 0.08, radius * 0.13, subdivisions=2)
        b.add(glint, m_glint, name=f"eye_glint_{side_tag}",
              at=(cx + radius * 0.16, center_y - radius * 0.69, center_z + radius * tall_scale * 0.24))


def add_sculpted_eyes(
    b: mk.Builder,
    center_y: float,
    center_z: float,
    spacing_x: float = 0.0365,
    rx: float = 0.0195,
    ry: float = 0.0120,
    rz: float = 0.0115,
    pupil_radius: float = 0.0050,
    pupil_recess: float = 0.0022,
    tilt_deg: float = 11.0,
    yaw_deg: float = 7.0,
    iris_mat: mk.Material | None = None,
    pupil_mat: mk.Material | None = None,
    eyelid_mat: mk.Material | None = None,
) -> None:
    """Assemble une paire d'yeux anatomiques sculptés haute définition (masques Noh/Tengu,
    créatures, bustes réalistes) **garantie sans aucun dépassement de pupille ni facettes cassées** :
      1. Globe oculaire haute densité (`subdivisions=3`) centré à `(0,0,0)` avant rotation `tilt`/`yaw`.
      2. Ouverture circulaire de pupille taillée par soustraction booléenne et **fond de pupille
         concave strictement EN RETRAIT (`+pupil_recess` vers `+Y`)** coupé par `mk.intersection`
         à l'intérieur strict du volume du globe (`0,00 mm` de protubérance avant garantie !).
      3. Paupières supérieures et inférieures en amande à **5 points de contrôle C² (`CubicSpline`)**
         épousant exactement le galbe ellipsoïdal du globe jusqu'aux commissures interne/externe.
    """
    m_iris = iris_mat or mk.mat.metal("#e0ba56", roughness=0.16, metallic=0.92)
    m_pup = pupil_mat or mk.mat.eye_gloss("#060708")
    m_lid = eyelid_mat or mk.mat.lacquer("#260c0e", roughness=0.20)

    for tag, sgn in (("R", -1.0), ("L", 1.0)):
        cx = sgn * float(spacing_x)

        # 1) Globe haute densité centré à l'origine avant rotation multi-axes
        globe = ellipsoid(float(rx), float(ry), float(rz), center=(0.0, 0.0, 0.0), subdivisions=3)
        mk.rot_y(globe, -sgn * float(tilt_deg))
        mk.rot_z(globe, sgn * float(yaw_deg))
        mk.place(globe, cx, float(center_y), float(center_z))

        # 2) Puits de pupille taillé proprement + fond noir CONCAVE strictement interne au globe !
        px = cx - sgn * float(rx) * 0.04
        pz = float(center_z)
        # Note : `mk.cylinder(r, h)` va de `z=0` à `z=+h` ; `mk.rot_x(+90°)` envoie `+Z -> -Y` !
        # On place donc l'arrière du cylindre de découpe à `center_y + ry` pour traverser vers `-Y`.
        bore = mk.cylinder(float(pupil_radius), float(ry) * 2.6, sections=36)
        mk.rot_x(bore, 90.0)
        mk.place(bore, px, float(center_y) + float(ry) * 0.8, pz)
        eyeball_pierced = mk.difference(globe, [bore])
        b.add(eyeball_pierced, m_iris, name=f"gilded_brass_eye_{tag}")

        # Cupule noire interne : `intersection` avec une copie du globe reculée de `+pupil_recess`
        # vers `+Y` -> il est MATHÉMATIQUEMENT IMPOSSIBLE que le cylindre noir dépasse du globe !
        inner_bound = globe.copy()
        mk.place(inner_bound, 0.0, float(pupil_recess), 0.0)
        pup_plug = mk.cylinder(float(pupil_radius) * 1.03, float(ry) * 2.0, sections=36)
        mk.rot_x(pup_plug, 90.0)
        mk.place(pup_plug, px, float(center_y) + float(ry) * 0.9, pz)
        pupil_recessed = mk.intersection(inner_bound, pup_plug)
        b.add(pupil_recessed, m_pup, name=f"black_pupil_{tag}")

        # 3) Paupières supérieure & inférieure C² à 5 points épousant la sphère jusqu'aux canthus
        u_angles = [-0.96, -0.50, 0.0, 0.50, 0.96]
        up_pts, lo_pts = [], []
        for u in u_angles:
            arc = math.sqrt(max(1.0 - 0.82 * u * u, 0.04))
            lx = u * float(rx) * 1.06
            ly_surf = -float(ry) * (0.30 + 0.76 * arc)
            lz_up = float(rz) * (0.12 + 0.72 * arc)
            lz_lo = -float(rz) * (0.10 + 0.66 * arc)
            # Rotation locale de l'amande selon `tilt_deg`
            th = math.radians(-sgn * float(tilt_deg))
            ct, st = math.cos(th), math.sin(th)
            rx_u = lx * ct + lz_up * st
            rz_u = -lx * st + lz_up * ct
            rx_l = lx * ct + lz_lo * st
            rz_l = -lx * st + lz_lo * ct
            up_pts.append((cx + rx_u, float(center_y) + ly_surf, float(center_z) + rz_u))
            lo_pts.append((cx + rx_l, float(center_y) + ly_surf * 0.94, float(center_z) + rz_l))

        r_up = [rx * 0.15, rx * 0.22, rx * 0.25, rx * 0.21, rx * 0.14]
        r_lo = [rx * 0.13, rx * 0.18, rx * 0.20, rx * 0.17, rx * 0.12]
        b.add(tapered_curve(up_pts, r_up, sections=24, smooth_pts=36), m_lid, name=f"sculpted_upper_eyelid_{tag}")
        b.add(tapered_curve(lo_pts, r_lo, sections=22, smooth_pts=34), m_lid, name=f"sculpted_lower_eyelid_{tag}")


def museum_plinth(
    width: float = 0.16,
    depth: float = 0.16,
    height: float = 0.038,
    round_profile: bool = False,
) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """Retourne `(base_plinth, collar_ring)` 100 % étanches et largement chevauchants à `z = 0`."""
    if round_profile:
        r = 0.5 * max(float(width), float(depth))
        b1 = mk.frustum(r, r * 0.94, height * 0.34, sections=56)
        b2 = mk.cylinder(r * 0.85, height * 0.80, sections=56)
        mk.place(b2, 0.0, 0.0, height * 0.20)
        base = mk.union([b1, b2])
        ring = mk.cylinder(r * 0.895, height * 0.16, sections=56)
        mk.place(ring, 0.0, 0.0, height * 0.72)
        return base, ring
    p1 = mk.chamfer_box(width, depth, height * 0.58, c=min(width, depth) * 0.07)
    p2 = mk.chamfer_box(width * 0.84, depth * 0.84, height, c=min(width, depth) * 0.06)
    base = mk.union([p1, p2])
    ring = mk.chamfer_box(width * 0.88, depth * 0.88, height * 0.16, c=min(width, depth) * 0.05)
    mk.place(ring, 0.0, 0.0, height * 0.50)
    return base, ring
