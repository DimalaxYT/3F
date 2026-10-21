# AGENTS.md — Protocole Ultra-Rapide Arena.ai / GLM / Agents IA (`3d-forge v5.1 Turbo`)

Ce dépôt contient **`3d-forge v5.1 Turbo`** : moteur de génération 3D réaliste pensé en priorité pour **Roblox Studio** (`roblox/<nom>_roblox.glb` en PNG pur `webp=False` + `Studs` + `< 9 800 tris` + `Neon_*` + `setup_<nom>.lua`) et **Unreal Engine 5** (`unreal/SM_<nom>.glb` + `UCX_*` + `ORM` + `DirectX -Y`).

---

## ⚡ PROTOCOLE OBLIGATOIRE `3 TOURS MAXIMUM` (`< 90 SECONDES` SUR ARENA + GLM !)

> **RÈGLE STRICTE ANTI-LENTEUR (NE DÉPASSE JAMAIS 2 MINUTES !)** :
> - ❌ **NE LIS PAS** les longs fichiers internes (`game_ready.py`, `pbr.py`, `renderer.py`, `meshkit.py`) : toute l'API exacte est résumée ci-dessous !
> - ❌ **N'APPELLE JAMAIS** `scripts/research.py fetch` ni de téléchargement HTTP externe (bloqué par le pare-feu sandbox d'Arena -> cause des timeouts de 60 s !).
> - ❌ **NE LANCE PAS** `render_views --faces all` ni 4 ou 5 boucles `critique.py` !
> - ✅ **`scripts/turbo_forge.py` auto-installe tout seul `requirements.txt` (`--break-system-packages`) s'il manque un module Python dans le conteneur Arena !**

### Séquence exacte des outils à exécuter dans Arena Agent Mode :

1. **TOUR 1 — Créer la source géométrique (1 seul appel `write_file` ou `generate_image` parallèle)** :
   - **Si Hard-Surface / Arme / Véhicule / Coffre / Bâtiment** : écris directement `custom_<nom>.py` avec **`write_file`** en utilisant l'aide-mémoire API ci-dessous (formes profilées `mk.*` + pièces détaillées `grb.*` de `greebles.py`, jamais un simple cube nu !).
   - **Si Créature / Personnage / Monstre / Buste organique** : appelle **`generate_image(..., offer_options=False)` EN PARALLÈLE DANS CE MÊME TOUR** pour `out/<nom>/front.png`, `out/<nom>/side.png` et `out/<nom>/back.png` (fond gris neutre uni `#c8cbd0`, éclairage studio plat sans ombre portée, cadrage centré identique). *(Important : passe toujours `offer_options=False` pour ne pas bloquer le tour sur les vues intermédiaires !)*
2. **TOUR 2 — Exécuter UNE SEULE COMMANDE `turbo_forge.py` via `bash` (`12 à 20 s` tout compris)** :
   - Hard-Surface : `python3 scripts/turbo_forge.py custom_<nom>.py --name <nom> --lod0-tris 4800 --stl -o out/<nom>`
   - Organique : `python3 scripts/turbo_forge.py --front out/<nom>/front.png --side out/<nom>/side.png --back out/<nom>/back.png --name <nom> --lod0-tris 4800 -o out/<nom>`
   - Recette existante : `python3 scripts/turbo_forge.py <katana|sci_fi_crate|car|motocross|...> --lod0-tris 4800 -o out/<nom>`
3. **TOUR 3 — Contrôler `qa_game_sheet.png` + Afficher à l'utilisateur (`read_file` + `present_file`)** :
   - Lis **uniquement** `out/<nom>/qa_game_sheet.png` avec `read_file` et ouvre-le dans le panneau Arena avec **`present_file(path="out/<nom>/qa_game_sheet.png")`**.
   - Si le résultat est propre, **livre immédiatement** avec les chemins exacts (`out/<nom>/roblox/<nom>_roblox.glb`, `out/<nom>/roblox/setup_<nom>.lua`, `out/<nom>/unreal/SM_<nom>.glb`). Ne fais au maximum **qu'une seule** retouche si un défaut géométrique flagrant est visible.

---

## 🧩 Aide-Mémoire API 100 % Vérifié (`custom_<nom>.py` — Zéro `read_file` requis !)

```python
import sys
sys.path.insert(0, "scripts")
import meshkit as mk
import greebles as grb

def build() -> mk.Builder:
    b = mk.Builder("plasma_rifle")  # Repère métrique : X = gauche/droite, Y = avant(-)/arrière(+), Z = haut(+)

    # 1. Matériaux physiques sémantiques reconnus automatiquement par `game_ready.py` :
    mat_armor  = mk.Material("painted_armor", "#2b3848", metallic=0.25, roughness=0.42)
    mat_steel  = mk.Material("brushed_steel", "#a8b0b8", metallic=0.90, roughness=0.28)
    mat_rubber = mk.Material("rubber_grip",   "#1b1d20", metallic=0.0,  roughness=0.85)  # `rubber`/`grip`/`poly` -> metallic=0 strict !
    mat_hazard = mk.Material("hazard_stripe", "#e09018", metallic=0.15, roughness=0.45)  # `hazard` -> chevrons noirs/jaunes auto !
    mat_neon   = mk.Material("cyan_core",     "#00e5ff", metallic=0.0,  roughness=0.15, emissive="#00e5ff")  # -> MeshPart `Neon_*` auto dans Roblox !

    # 2. Primitives CAO 100 % étanches (`scripts/meshkit.py`) :
    #   mk.box(w, d, h)                      mk.chamfer_box(w, d, h, c=None)
    #   mk.rounded_box(w, d, h, r=None)      mk.cylinder(r, h, sections=32)      # ATTENTION : `mk.cylinder`, PAS `mk.cyl` !
    #   mk.tube(r_out, r_in, h)              mk.cone(r, h) / mk.frustum(r1, r2, h)
    #   mk.sphere(r) / mk.capsule(r, h_cyl)  mk.torus(R, r)
    #   mk.extrude(points2d, height)         mk.lathe(profile_rz, sections=48)
    #   mk.loft(sections, zs=None)           mk.tube_sweep(path_xyz, r, r_inner=0.0)
    #   mk.helix_spring(r_coil, r_wire, pitch, turns=6.0)
    #   Booléens CSG étanches : mk.union([m1, m2, ...]), mk.difference(base, [tool1, ...]), mk.intersection(a, b)
    #   Transformations (modifient ET retournent `m`) :
    #   mk.place(m, x=0, y=0, z=0), mk.rot_x(m, deg), mk.rot_y(m, deg), mk.rot_z(m, deg), mk.scale(m, s), mk.ground(m)

    hull = mk.chamfer_box(0.08, 0.56, 0.13, c=0.012)
    b.add(mk.place(hull, 0, 0, 0.14), mat_armor, "receiver_hull")

    barrel = mk.rot_x(mk.tube(0.018, 0.010, 0.34), 90)
    b.add(mk.place(barrel, 0, -0.42, 0.155), mat_steel, "heavy_barrel")

    # 3. Détails mécaniques AAA 100 % étanches (`scripts/greebles.py`) :
    #   grb.picatinny_rail(length=0.28, width=0.026, height=0.014, teeth=9) -> Trimesh
    #   grb.louver_vent(width=0.16, height=0.088, slats=5, depth=0.018)     -> Trimesh
    #   grb.hex_bolt(r=0.011, h=0.009, washer=True, socket=True)            -> Trimesh
    #   grb.bolt_array(points, normals, r=0.009, h=0.0075)                  -> list[Trimesh]
    #   grb.ribbed_conduit(path_xyz, r=0.011, rings=12)                     -> Trimesh
    #   grb.corner_armor_cap(size=0.082, height=0.38)                       -> Trimesh
    #   grb.toggle_latch(width=0.058, height=0.118, depth=0.026)            -> list[(Trimesh, role_str)]
    #   grb.ergonomic_handle(span=0.17, reach=0.04, r=0.0105)               -> list[(Trimesh, role_str)]

    b.add(mk.place(grb.picatinny_rail(length=0.30, teeth=11), 0, -0.05, 0.212), mat_steel, "top_rail")
    for bm in grb.bolt_array([[-0.041, -0.15, 0.16], [-0.041, 0.15, 0.16]], [[-1, 0, 0], [-1, 0, 0]], r=0.006, h=0.005):
        b.add(bm, mat_steel, "side_bolt")

    b.add(mk.place(mk.box(0.084, 0.22, 0.018), 0, -0.10, 0.155), mat_neon, "plasma_strip")

    # 4. Sockets gameplay (& articulations optionnelles `b.def_joint("lid", pivot=(...), axis=(1,0,0))`) :
    b.def_socket("grip", pos=(0.0, 0.12, 0.06))
    b.def_socket("muzzle", pos=(0.0, -0.60, 0.155))
    return b
```
