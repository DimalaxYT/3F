"""Fixture d'eval : fusil plasma hard-surface (custom builder `turbo_forge`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import greebles as grb  # noqa: E402
import meshkit as mk  # noqa: E402


def build() -> mk.Builder:
    b = mk.Builder("plasma_rifle")
    mat_armor = mk.Material("painted_armor", "#2b3848", metallic=0.25, roughness=0.42)
    mat_steel = mk.Material("brushed_steel", "#a8b0b8", metallic=0.90, roughness=0.28)
    mat_rubber = mk.Material("rubber_grip", "#1b1d20", metallic=0.0, roughness=0.85)
    mat_neon = mk.Material("cyan_core", "#00e5ff", metallic=0.0, roughness=0.15, emissive="#00e5ff")

    hull = mk.chamfer_box(0.08, 0.56, 0.13, c=0.012)
    b.add(mk.place(hull, 0, 0, 0.14), mat_armor, "receiver_hull")
    barrel = mk.rot_x(mk.tube(0.018, 0.010, 0.34), 90)
    b.add(mk.place(barrel, 0, -0.42, 0.155), mat_steel, "heavy_barrel")
    b.add(mk.place(grb.picatinny_rail(length=0.30, teeth=11), 0, -0.05, 0.212), mat_steel, "top_rail")
    grip = mk.rot_x(mk.capsule(0.016, 0.09), 18)
    b.add(mk.place(grip, 0, 0.12, 0.06), mat_rubber, "grip")
    for bm in grb.bolt_array([[-0.041, -0.15, 0.16], [-0.041, 0.15, 0.16]],
                             [[-1, 0, 0], [-1, 0, 0]], r=0.006, h=0.005):
        b.add(bm, mat_steel, "side_bolt")
    b.add(mk.place(mk.box(0.084, 0.22, 0.018), 0, -0.10, 0.155), mat_neon, "plasma_strip")
    b.def_socket("grip", pos=(0.0, 0.12, 0.06))
    b.def_socket("muzzle", pos=(0.0, -0.60, 0.155))
    return b
