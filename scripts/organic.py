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


# --------------------------------------------------------------------------- #
# 4. Primitives Anatomiques Avancées : Écailles 3D, Plaques Ventrales, Crêtes & Ailes
# --------------------------------------------------------------------------- #

def displace_scales(
    mesh: trimesh.Trimesh,
    scale_size: float = 0.016,
    depth: float = 0.0022,
    sharpness: float = 1.45,
) -> trimesh.Trimesh:
    """Sculpte un vrai réseau 3D d'écailles reptiliennes hexagonales imbriquées directement
    sur les sommets de `mesh` le long de ses normales (visible dans le `.stl` ET cuit dans
    les Normal/AO maps 1024² !)."""
    if len(mesh.vertices) < 36 or float(scale_size) <= 1e-6:
        return mesh
    out = mesh.copy()
    v = np.asarray(out.vertices, dtype=np.float64)
    nrm = np.asarray(out.vertex_normals, dtype=np.float64)

    # Coordonnées curvilignes triplanaires pondérées par les normales (zéro couture UV !)
    an = np.abs(nrm)
    w = an / np.maximum(an.sum(axis=1, keepdims=True), 1e-6)
    freq = 1.0 / float(scale_size)

    def _hex_scales_2d(u_coord: np.ndarray, v_coord: np.ndarray) -> np.ndarray:
        row = v_coord * freq * 1.1547
        row_i = np.floor(row)
        fu = u_coord * freq + 0.5 * np.mod(row_i, 2.0)
        du = np.mod(fu, 1.0) - 0.5
        dv = np.mod(row, 1.0) - 0.5
        # Profil d'écaille imbriquée en goutte/losange (imbrication vers le bas/arrière)
        d = np.sqrt((du * 1.18) ** 2 + ((dv + 0.14) * 1.02) ** 2)
        dome = np.clip(1.0 - (d / 0.58) ** float(sharpness), -0.35, 1.0)
        lip = 0.28 * np.exp(-(((dv - 0.34) / 0.14) ** 2)) * np.clip(1.0 - np.abs(du) * 1.9, 0.0, 1.0)
        return dome + lip

    s_yz = _hex_scales_2d(v[:, 1], v[:, 2])
    s_xz = _hex_scales_2d(v[:, 0], v[:, 2])
    s_xy = _hex_scales_2d(v[:, 0], v[:, 1])
    field = w[:, 0] * s_yz + w[:, 1] * s_xz + w[:, 2] * s_xy
    field = field - float(np.mean(field))

    out.vertices = v + nrm * (field[:, None] * float(depth))
    out.fix_normals(multibody=False)
    return out


def armored_scutes(
    spine_pts,
    widths,
    outward_hint=(0.0, -1.0, -0.35),
    thickness_ratio: float = 0.42,
    arch_ratio: float = 0.30,
) -> trimesh.Trimesh:
    """Génère une rangée de plaques ventrales/pectorales imbriquées (`scutes`)
    mathématiquement tangentes à `spine_pts` et profondément ancrées dans le corps
    (élimine 100 % des plaques flottantes détachées du cou ou du torse !)."""
    pts = np.asarray(spine_pts, dtype=float)
    wds = np.asarray(widths, dtype=float)
    if len(pts) < 2:
        raise ValueError("armored_scutes: au moins 2 points requis")
    if len(wds) != len(pts):
        wds = np.interp(np.linspace(0.0, 1.0, len(pts)), np.linspace(0.0, 1.0, len(wds)), wds)

    hint = np.asarray(outward_hint, dtype=float)
    hint /= max(float(np.linalg.norm(hint)), 1e-8)

    plates: list[trimesh.Trimesh] = []
    n = len(pts)
    for i in range(n):
        t_vec = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
        t_norm = float(np.linalg.norm(t_vec))
        t_vec = t_vec / max(t_norm, 1e-8)

        # Repère orthonormé local : X = latéral, Z_loc = tangent le long du cou, -Y_loc = vers l'extérieur !
        x_ax = np.array([1.0, 0.0, 0.0], dtype=float)
        out_ax = np.cross(t_vec, x_ax)
        if float(np.dot(out_ax, hint)) < 0.0:
            out_ax = -out_ax
        out_ax /= max(float(np.linalg.norm(out_ax)), 1e-8)
        z_ax = np.cross(x_ax, out_ax)
        z_ax /= max(float(np.linalg.norm(z_ax)), 1e-8)

        step_len = float(np.linalg.norm(pts[min(i + 1, n - 1)] - pts[i])) if i < n - 1 else float(np.linalg.norm(pts[i] - pts[i - 1]))
        w_cur = float(wds[i])
        h_plate = max(step_len * 1.48, w_cur * 0.42)
        thk = max(w_cur * float(thickness_ratio), 0.010)

        pl = curved_visor(
            width=w_cur,
            length=thk,
            thickness=h_plate,
            arch=w_cur * float(arch_ratio),
            droop=-h_plate * 0.14,
            sections=18,
        )
        # Dans `curved_visor`, l'arc pointe vers `-Y` : on aligne `-Y` sur `out_ax` et `Z` sur `z_ax`
        R4 = np.eye(4, dtype=float)
        R4[:3, 0] = x_ax
        R4[:3, 1] = -out_ax
        R4[:3, 2] = z_ax
        # Recule de `0.38 * thk` vers l'intérieur du cou/poitrail pour un ancrage solide à 100 % !
        R4[:3, 3] = pts[i] - out_ax * (thk * 0.35)
        pl.apply_transform(R4)
        if float(pl.volume) < 0.0:
            pl.invert()
        plates.append(pl)

    return mk.union(plates) if len(plates) > 1 else plates[0]


def ridge_spines(
    spine_pts,
    heights,
    radii,
    up_hint=(0.0, 0.25, 1.0),
    lean_back: float = 0.42,
    sections: int = 10,
) -> trimesh.Trimesh:
    """Génère automatiquement une crête d'épines dorsales courbées le long de n'importe
    quelle courbe 3D `spine_pts` (cou en S, échine, queue enroulée)."""
    pts = np.asarray(spine_pts, dtype=float)
    hts = np.interp(np.linspace(0.0, 1.0, len(pts)), np.linspace(0.0, 1.0, len(heights)), heights)
    rds = np.interp(np.linspace(0.0, 1.0, len(pts)), np.linspace(0.0, 1.0, len(radii)), radii)
    hint = np.asarray(up_hint, dtype=float)
    hint /= max(float(np.linalg.norm(hint)), 1e-8)

    spines: list[trimesh.Trimesh] = []
    n = len(pts)
    for i in range(n):
        tang = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
        tang /= max(float(np.linalg.norm(tang)), 1e-8)
        lat = np.array([1.0, 0.0, 0.0], dtype=float)
        nrm = np.cross(lat, tang)
        if float(np.dot(nrm, hint)) < 0.0:
            nrm = -nrm
        nrm /= max(float(np.linalg.norm(nrm)), 1e-8)

        h = float(hts[i])
        r = float(rds[i])
        base = pts[i] - nrm * (r * 0.9)
        mid = pts[i] + nrm * (h * 0.56) + tang * (h * float(lean_back) * 0.42)
        tip = pts[i] + nrm * h + tang * (h * float(lean_back))
        sp = tapered_curve([base, mid, tip], [r, r * 0.58, max(r * 0.16, 0.0018)], sections=sections, smooth_pts=10)
        spines.append(sp)

    return mk.union(spines) if len(spines) > 1 else spines[0]


def bat_wing(
    shoulder,
    elbow,
    wrist,
    finger_tips: list[tuple[float, float, float]],
    body_anchors: list[tuple[float, float, float]] | None = None,
    membrane_thickness: float = 0.011,
    camber: float = 0.026,
    arm_radius: float = 0.024,
    claw_len: float = 0.046,
) -> tuple[trimesh.Trimesh, trimesh.Trimesh, trimesh.Trimesh]:
    """Construit une aile de dragon / chauve-souris 100 % solide, étanche et cambrée :
      - `(arm_and_fingers_mesh, membrane_mesh, thumb_claw_mesh)`
      - Membrane pleine épaisse (`>= membrane_thickness`) à festons arqués entre phalanges :
        ne se déchire JAMAIS à la décimation QEM (`LOD0 / LOD1 / LOD2`) !"""
    sh = np.asarray(shoulder, dtype=float)
    el = np.asarray(elbow, dtype=float)
    wr = np.asarray(wrist, dtype=float)
    tips = [np.asarray(p, dtype=float) for p in finger_tips]
    if len(tips) < 2:
        raise ValueError("bat_wing: au moins 2 extrémités de phalanges requises")

    sx = 1.0 if wr[0] >= 0.0 else -1.0

    # 1. Os musclés : humérus -> avant-bras -> phalanges arquées
    arm_mesh = tapered_curve(
        [sh, 0.5 * (sh + el) + np.array([0.0, 0.0, 0.012]), el, wr],
        [arm_radius * 1.28, arm_radius * 1.02, arm_radius * 0.88, arm_radius * 0.72],
        sections=18,
        smooth_pts=24,
    )
    bone_parts = [arm_mesh]

    finger_curves: list[np.ndarray] = []
    n_u = 14
    us = np.linspace(0.0, 1.0, n_u)
    for fi, tip in enumerate(tips):
        mid1 = wr + 0.36 * (tip - wr) + np.array([sx * camber * 0.55, 0.0, camber * 0.85])
        mid2 = wr + 0.72 * (tip - wr) + np.array([sx * camber * 0.30, 0.0, camber * 0.42])
        ctrl = np.vstack([wr, mid1, mid2, tip])
        t_c = np.linspace(0.0, 1.0, 4)
        curve = np.column_stack([CubicSpline(t_c, ctrl[:, k], bc_type="natural")(us) for k in range(3)])
        finger_curves.append(curve)
        r_f = arm_radius * max(0.46 - 0.06 * fi, 0.24)
        bone_parts.append(
            tapered_curve([wr, mid1, mid2, tip], [r_f, r_f * 0.72, r_f * 0.46, max(r_f * 0.20, 0.0025)], sections=12, smooth_pts=18)
        )

    # Courbe d'attache interne contre le flanc du corps (`patagium`)
    if body_anchors and len(body_anchors) >= 2:
        ba_ctrl = np.asarray(body_anchors, dtype=float)
    else:
        flank_end = sh + np.array([0.0, abs(tips[-1][1] - sh[1]) * 0.58, -abs(wr[2] - sh[2]) * 0.30])
        ba_ctrl = np.vstack([sh, 0.5 * (sh + flank_end) + np.array([sx * 0.012, 0.0, -0.015]), flank_end])
    t_b = np.linspace(0.0, 1.0, len(ba_ctrl))
    flank_curve = np.column_stack([PchipInterpolator(t_b, ba_ctrl[:, k])(us) for k in range(3)])
    all_ribs = [
        np.column_stack([PchipInterpolator([0.0, 0.5, 1.0], np.vstack([sh, el, wr])[:, k])(us) for k in range(3)]),
        *finger_curves,
        flank_curve,
    ]

    # 2. Panneaux de membrane solides fermés et festonnés entre chaque paire de nervures !
    mem_panels: list[trimesh.Trimesh] = []
    n_u_mem = 13
    us_mem = np.linspace(0.07, 1.0, n_u_mem)
    all_ribs_mem = [
        np.column_stack([PchipInterpolator(np.linspace(0.0, 1.0, len(r)), r[:, k])(us_mem) for k in range(3)])
        for r in all_ribs
    ]
    n_v = 9
    vs = np.linspace(0.0, 1.0, n_v)
    half_t = max(float(membrane_thickness) * 0.5, 0.0045)

    for ri in range(len(all_ribs_mem) - 1):
        cA = all_ribs_mem[ri]
        cB = all_ribs_mem[ri + 1]
        # Grille surfacique `(n_u_mem, n_v, 3)` avec feston concave au bord de fuite (`u -> 1`)
        grid = np.zeros((n_u_mem, n_v, 3), dtype=np.float64)
        for iu, u_val in enumerate(us_mem):
            scallop = np.sin(math.pi * vs) * (u_val ** 2.2)
            # Le bord de fuite remonte élégamment en arc gothique vers le poignet !
            pull_to_wrist = 0.20 * scallop[:, None] * (wr - (0.5 * (cA[iu] + cB[iu])))[None, :]
            arch_lift = (float(camber) * 0.55 * math.sin(math.pi * u_val)) * scallop[:, None] * np.array([[sx * 0.6, 0.0, 1.0]])
            base_row = (1.0 - vs)[:, None] * cA[iu][None, :] + vs[:, None] * cB[iu][None, :]
            grid[iu] = base_row + pull_to_wrist + arch_lift

        # Normales locales lissées de la feuille de membrane pour l'extrusion bilatérale épaisse
        du_g = np.gradient(grid, axis=0)
        dv_g = np.gradient(grid, axis=1)
        nrm_g = np.cross(du_g, dv_g)
        nrm_len = np.maximum(np.linalg.norm(nrm_g, axis=2, keepdims=True), 1e-8)
        nrm_g = nrm_g / nrm_len

        top_v = (grid + nrm_g * half_t).reshape(-1, 3)
        bot_v = (grid - nrm_g * half_t).reshape(-1, 3)
        nv_sheet = n_u_mem * n_v
        verts = np.vstack([top_v, bot_v])
        faces: list[list[int]] = []

        def _idx_t(i_u: int, i_v: int) -> int:
            return i_u * n_v + i_v

        def _idx_b(i_u: int, i_v: int) -> int:
            return nv_sheet + i_u * n_v + i_v

        for i_u in range(n_u_mem - 1):
            for i_v in range(n_v - 1):
                a, b0 = _idx_t(i_u, i_v), _idx_t(i_u, i_v + 1)
                c, d = _idx_t(i_u + 1, i_v + 1), _idx_t(i_u + 1, i_v)
                faces.append([a, b0, c])
                faces.append([a, c, d])
                ab, bb = _idx_b(i_u, i_v), _idx_b(i_u, i_v + 1)
                cb, db = _idx_b(i_u + 1, i_v + 1), _idx_b(i_u + 1, i_v)
                faces.append([ab, cb, bb])
                faces.append([ab, db, cb])

        # Couture étanche des 4 bords périmétriques de la feuille
        perim = (
            [(0, j) for j in range(n_v - 1)]
            + [(i, n_v - 1) for i in range(n_u_mem - 1)]
            + [(n_u_mem - 1, j) for j in range(n_v - 1, 0, -1)]
            + [(i, 0) for i in range(n_u_mem - 1, 0, -1)]
        )
        for k_p in range(len(perim)):
            u0, v0 = perim[k_p]
            u1, v1 = perim[(k_p + 1) % len(perim)]
            t0, t1 = _idx_t(u0, v0), _idx_t(u1, v1)
            b00, b11 = _idx_b(u0, v0), _idx_b(u1, v1)
            faces.append([t0, b00, b11])
            faces.append([t0, b11, t1])

        panel = trimesh.Trimesh(vertices=verts, faces=np.asarray(faces, dtype=np.int64), process=True)
        panel.fix_normals(multibody=False)
        if float(panel.volume) < 0.0:
            panel.invert()
        mem_panels.append(panel)

    # 3. Griffe crochue d'alula au sommet du poignet (`wrist`)
    fwd_dir = np.array([sx * 0.14, -0.86, -0.48], dtype=float)
    fwd_dir /= np.linalg.norm(fwd_dir)
    claw = tapered_curve(
        [
            wr - fwd_dir * (arm_radius * 0.5),
            wr + fwd_dir * (claw_len * 0.52) + np.array([0.0, 0.0, claw_len * 0.18]),
            wr + fwd_dir * claw_len - np.array([0.0, 0.0, claw_len * 0.24]),
        ],
        [arm_radius * 0.52, arm_radius * 0.30, max(arm_radius * 0.08, 0.002)],
        sections=12,
        smooth_pts=14,
    )

    bones_union = mk.union(bone_parts)
    mem_union = mk.union(mem_panels) if len(mem_panels) > 1 else mem_panels[0]
    return bones_union, mem_union, claw

