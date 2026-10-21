# AGENTS.md — Protocole Ultra-Rapide Arena.ai / GLM / Agents IA (`3d-forge v5.2`)

Ce dépôt contient **`3d-forge`** : moteur de génération 3D réaliste pensé en priorité
pour **Roblox Studio** (`roblox/<nom>_roblox.glb` PNG pur + `Studs` + budget tris par
`MeshPart` + `Neon_*` + `setup_<nom>.lua`) et **Unreal Engine 5** (`unreal/SM_<nom>.glb`
+ `UCX_*` + `ORM` + normales DirectX `-Y`).

> **Source de vérité unique : [`SKILL.md`](SKILL.md)** (protocole, profils, arbre de
> décision, cheatsheet) + ses références (`references/workflows.md`,
> `references/engine_profiles.md`, `references/recipes.md`). Ce fichier ne répète
> QUE la séquence d'outils Arena ; **seuil & budget de critique =
> `python3 scripts/critique.py policy`**, gates = `scripts/gates.py`.

---

## ⚡ PROTOCOLE `3 TOURS MAXIMUM` (profil `turbo`)

> **RÈGLE STRICTE ANTI-LENTEUR** :
> - ❌ **NE LIS PAS** les longs fichiers internes (`game_ready.py`, `pbr.py`,
>   `renderer.py`, `meshkit.py`) : l'API exacte est dans SKILL.md §3.
> - ❌ **N'APPELLE JAMAIS** `scripts/research.py fetch` ni de download HTTP externe
>   (pare-feu sandbox -> timeouts) en profil `turbo`.
> - ❌ **NE LANCE PAS** `--faces all` ni 4-5 boucles de critique : le budget
>   d'itérations est borné par le code (`critique.py policy`).
> - ✅ `turbo_forge.py` auto-installe `requirements.txt` au 1er lancement si un
>   module manque ; sinon `python3 scripts/detect_env.py --fix`.

### Séquence exacte des outils dans Arena Agent Mode

1. **TOUR 1 — source géométrique (1 seul appel, parallélisable)** :
   - **Hard-surface / arme / véhicule / coffre / bâtiment** : `write_file`
     `custom_<nom>.py` (`def build() -> mk.Builder`, cheatsheet SKILL.md §3 ;
     `meshkit` + `greebles`, jamais un cube nu).
   - **Créature / buste organique** : `generate_image(..., offer_options=False)`
     **en parallèle dans ce même tour** pour `out/<nom>/front.png`, `side.png`
     (optionnel `back.png`) — fond gris neutre `#c8cbd0`, éclairage studio plat,
     cadrage centré identique.
2. **TOUR 2 — UNE seule commande `bash` (12–25 s)** :
   - Hard-surface : `python3 scripts/turbo_forge.py custom_<nom>.py --name <nom> --lod0-tris 4800 -o out/<nom>`
   - Organique : `python3 scripts/turbo_forge.py --front out/<nom>/front.png --side out/<nom>/side.png --back out/<nom>/back.png --name <nom> --lod0-tris 4800 -o out/<nom>`
   - Recette : `python3 scripts/turbo_forge.py <katana|sci_fi_crate|car|motocross|...> --lod0-tris 4800 -o out/<nom>`
   - Le STL étanche est exporté **par défaut** (`--no-stl` pour le désactiver,
     `--split-bed` pour le découper au plateau 256 mm).
3. **TOUR 3 — contrôle & livraison** :
   - `read_file out/<nom>/qa_game_sheet.png` (10 panneaux : LODs, face/profil avec
     échelle cm+Studs, ColorMap Roblox, cartes) **et** le résumé gates imprimé au
     tour 2 (`gates.json` / `qa_summary.md` en cas de doute).
   - Gates OK + planche propre → `present_file(out/<nom>/qa_game_sheet.png)` et
     livrer les chemins (`roblox/<nom>_roblox.glb`, `roblox/setup_<nom>.lua`,
     `unreal/SM_<nom>.glb`, `<nom>.stl`). **Une seule** retouche chirurgicale max
     (`critique.py --fast`), jamais 4 reconstructions.

---

## 🧩 Aide-mémoire API (`custom_<nom>.py` — zéro `read_file` requis)

Identique à SKILL.md §3 (recopié ici pour vitesse) :

```python
import sys
sys.path.insert(0, "scripts")
import meshkit as mk
import greebles as grb

def build() -> mk.Builder:
    b = mk.Builder("plasma_rifle")  # Repère métrique : X = gauche/droite, Y = avant(-)/arrière(+), Z = haut(+)

    # Matériaux sémantiques reconnus par game_ready.py :
    mat_armor  = mk.Material("painted_armor", "#2b3848", metallic=0.25, roughness=0.42)
    mat_steel  = mk.Material("brushed_steel", "#a8b0b8", metallic=0.90, roughness=0.28)
    mat_rubber = mk.Material("rubber_grip",   "#1b1d20", metallic=0.0,  roughness=0.85)  # rubber/grip/poly -> metallic=0 strict
    mat_hazard = mk.Material("hazard_stripe", "#e09018", metallic=0.15, roughness=0.45)  # chevrons noirs/jaunes auto
    mat_neon   = mk.Material("cyan_core",     "#00e5ff", metallic=0.0,  roughness=0.15, emissive="#00e5ff")  # -> MeshPart Neon_*

    # Primitives CAO 100 % étanches (meshkit.py) :
    #   mk.box(w,d,h)  mk.chamfer_box(w,d,h,c=None)  mk.rounded_box(w,d,h,r=None)
    #   mk.cylinder(r,h,sections=32)   # `mk.cylinder`, PAS `mk.cyl`
    #   mk.tube(r_out,r_in,h)  mk.cone(r,h)  mk.frustum(r1,r2,h)  mk.sphere(r)
    #   mk.capsule(r,h_cyl)  mk.torus(R,r)  mk.extrude(pts2d,height)
    #   mk.lathe(profile_rz,sections=48)  mk.loft(sections,zs=None)
    #   mk.tube_sweep(path_xyz,r,r_inner=0.0)  mk.helix_spring(r_coil,r_wire,pitch,turns=6)
    #   CSG : mk.union([...]), mk.difference(base,[...]), mk.intersection(a,b)
    #   Transforms (modifient ET retournent m) : mk.place(m,x=0,y=0,z=0),
    #   mk.rot_x(m,deg), mk.rot_y(m,deg), mk.rot_z(m,deg), mk.scale(m,s), mk.ground(m)

    hull = mk.chamfer_box(0.08, 0.56, 0.13, c=0.012)
    b.add(mk.place(hull, 0, 0, 0.14), mat_armor, "receiver_hull")
    barrel = mk.rot_x(mk.tube(0.018, 0.010, 0.34), 90)
    b.add(mk.place(barrel, 0, -0.42, 0.155), mat_steel, "heavy_barrel")

    # Kitbash mécanique étanche (greebles.py) :
    #   grb.picatinny_rail(length,width,height,teeth)  grb.louver_vent(width,height,slats,depth)
    #   grb.hex_bolt(r,h,washer=True,socket=True)      grb.bolt_array(points,normals,r,h)
    #   grb.ribbed_conduit(path_xyz,r,rings)           grb.corner_armor_cap(size,height)
    #   grb.toggle_latch(w,h,d) -> [(m,role)]          grb.ergonomic_handle(span,reach,r) -> [(m,role)]
    b.add(mk.place(grb.picatinny_rail(length=0.30, teeth=11), 0, -0.05, 0.212), mat_steel, "top_rail")
    for bm in grb.bolt_array([[-0.041, -0.15, 0.16], [-0.041, 0.15, 0.16]],
                             [[-1, 0, 0], [-1, 0, 0]], r=0.006, h=0.005):
        b.add(bm, mat_steel, "side_bolt")
    b.add(mk.place(mk.box(0.084, 0.22, 0.018), 0, -0.10, 0.155), mat_neon, "plasma_strip")

    # Sockets gameplay + articulations optionnelles :
    b.def_socket("grip", pos=(0.0, 0.12, 0.06))
    b.def_socket("muzzle", pos=(0.0, -0.60, 0.155))
    # b.def_joint("lid", pivot=(...), axis=(1, 0, 0))
    return b
```
