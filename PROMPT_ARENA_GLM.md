# 🚀 Prompt Spécial `Arena.ai + GLM` — Génération 3D en ~60 secondes !

Ce guide est taillé sur mesure pour **Arena.ai (Agent Mode) avec GLM** :
- Évite le pare-feu réseau d'Arena (zéro timeout HTTP `research.py fetch`),
- Évite l'erreur Python PEP-668 d'Arena (`turbo_forge.py` auto-installe `requirements.txt --break-system-packages` tout seul !),
- Inclut l'aide-mémoire exact des fonctions `meshkit.py` + `greebles.py` directement dans le prompt (**GLM n'a aucun fichier de code à lire avant de coder : 3 tours d'outils = ~60 s au lieu de 30+ min !**),
- Utilise nativement `write_file`, `generate_image(..., offer_options=False)` en parallèle et `present_file` d'Arena !

---

## Méthode A (La plus rapide sur Arena : connecter le repo GitHub `DimalaxYT/3F` !)

1. Dans **Arena -> Agent Mode**, sélectionne ton repo GitHub **`DimalaxYT/3F`** et choisis **GLM**.
2. Arena charge **automatiquement `AGENTS.md`** ! Tu n'as même pas besoin d'un long prompt — écris simplement :

```markdown
Utilise `AGENTS.md` (mode 3 tours `turbo_forge.py`, < 90 s) pour me créer cet asset 3D réaliste prêt pour Roblox Studio et UE5 :
[DÉCRIS TON MODÈLE ICI — ex: "Une épée énergétique katana cybernétique noire et rouge avec lame néon écarlate, garde gravée et poignée tressée"]
```

---

## Méthode B (Dans n'importe quel chat Arena + GLM sans repo connecté — Copier-Coller 1 clic !)

Clique sur **📋 Copier** en haut à droite du bloc ci-dessous, colle-le dans **Arena (GLM)** et remplace juste la dernière ligne :

```markdown
Tu tournes dans Arena Agent Mode. Génère mon modèle 3D prêt pour **Roblox Studio** (`roblox/<nom>_roblox.glb` + `setup_<nom>.lua`) et **Unreal Engine 5** (`unreal/SM_<nom>.glb`) en **MAXIMUM 3 TOURS D'OUTILS (< 90 s)** avec `3d-forge v5.1 Turbo` :

### RÈGLES ARENA + GLM STRICTES (ZÉRO PERTE DE TEMPS) :
- ❌ **INTERDIT** : `web_search`, `fetch_page`, `research.py fetch` (réseau filtré dans Arena !), `render_views --faces all`, ou lire les fichiers sources de `scripts/` (toute l'API exacte est ci-dessous !).
- ✅ **TOUR 1** :
  - Si `/home/user/3F` n'existe pas encore, clone-le en 2 s avec `bash` : `git clone --depth 1 https://github.com/DimalaxYT/3F.git /home/user/3F`
  - **Objet mécanique / arme / véhicule / coffre / bâtiment** : écris `custom_<nom>.py` avec `write_file` en utilisant les fonctions exactes ci-dessous (`meshkit` + `greebles`, jamais de simples boîtes nues !) :
    - `mk.Builder(name)` -> `b.add(mesh, mat, part_name, group=None)`, `b.def_joint(group, pivot=(x,y,z), axis=(1,0,0))`, `b.def_socket(name, pos=(x,y,z))`
    - `mk.Material(name, hex_color, metallic=0.0, roughness=0.5, opacity=1.0, emissive=None)` *(noms contenant `rubber`/`grip`/`poly` -> `metallic=0` strict ; `emissive="#..."` -> `Neon_*` auto dans Roblox !)*
    - Primitives `meshkit as mk` : `mk.box(w,d,h)`, `mk.chamfer_box(w,d,h,c=None)`, `mk.rounded_box(w,d,h,r=None)`, `mk.cylinder(r,h)`, `mk.tube(r_out,r_in,h)`, `mk.cone(r,h)`, `mk.frustum(r1,r2,h)`, `mk.sphere(r)`, `mk.capsule(r,h_cyl)`, `mk.torus(R,r)`, `mk.extrude(pts2d,h)`, `mk.lathe(profile_rz)`, `mk.loft(sections,zs=None)`, `mk.tube_sweep(path_xyz,r)`, `mk.helix_spring(r_coil,r_wire,pitch,turns=6)`, `mk.union([...])`, `mk.difference(base,[...])`, `mk.place(m,x,y,z)`, `mk.rot_x(m,deg)`, `mk.rot_y(m,deg)`, `mk.rot_z(m,deg)`, `mk.scale(m,s)`
    - Détails `greebles as grb` : `grb.picatinny_rail(length,width,height,teeth)`, `grb.louver_vent(width,height,slats,depth)`, `grb.hex_bolt(r,h)`, `grb.bolt_array(points,normals,r,h)`, `grb.ribbed_conduit(path_xyz,r,rings)`, `grb.corner_armor_cap(size,height)`, `grb.toggle_latch(width,height,depth)` *(liste `(mesh, role)`)*, `grb.ergonomic_handle(span,reach,r)` *(liste `(mesh, role)`)*
  - **Créature / personnage / monstre organique** : appelle `generate_image(..., offer_options=False)` **EN PARALLÈLE dans ce même tour** pour `front.png`, `side.png` et `back.png` (fond gris neutre uni, éclairage studio plat sans ombre portée).
- ✅ **TOUR 2** : lance **UNE SEULE commande `bash`** (`turbo_forge.py` auto-installe `requirements.txt` tout seul si besoin !) :
  `python3 scripts/turbo_forge.py custom_<nom>.py --name <nom> --lod0-tris 4800 --stl -o out/<nom>` *(ou `--front ... --side ... --back ...` pour de l'organique)*.
- ✅ **TOUR 3** : vérifie `out/<nom>/qa_game_sheet.png` avec `read_file`, affiche-le avec `present_file`, et donne-moi les chemins exacts de `out/<nom>/roblox/<nom>_roblox.glb` + `setup_<nom>.lua` et `out/<nom>/unreal/SM_<nom>.glb` !

DEMANDE : [DÉCRIS TON MODÈLE 3D ICI]
```
