# 3d-forge v4 🔨🐉✨

**CAO 3D paramétrique étanche × Sculpture Organique Multi-Vues GPU (`gpu_sculpt.py`) × Verre Cristal & Clearcoat glTF 2.0 × Découpe Imprimante 3D à Tenons (`split_stl.py`) — zéro GPU requis côté utilisateur.**

![Vitrine Technique 3d-forge v4](docs/img/v4_showcase.png)

![Showcase v3 GPU Mécanique & Armes](docs/img/v3_gpu_showcase.png)

![Catalogue Complet des 19 Recettes Étanches v4](docs/img/gallery.png)

> **Les 5 Piliers de `3d-forge v4` :**
> 1. **Sculpture Organique 3D propulsée par le GPU Datacenter (`scripts/gpu_sculpt.py`)** : reconstruction SDF elliptique multi-branches sans escaliers ni angles carrés, lissage de Taubin, socle de musée chanfreiné soudé par `manifold3d` (**100 % `watertight`**) et bake UV `1024²` haute définition (ex. `examples/dragon_buste/` : **84 152 triangles**, `2,68 L`, `.glb` + `.stl` + `.usdz` + `preview.html` + `photo_hero.png`).
> 2. **Catalogue complet de 19 recettes 100 % étanches (`scripts/recipes/`)** : refonte majeure de `car` (coupé GT fastback Clearcoat, vitres encastrées, jantes alliage 5 branches, disques de frein), `house` (fenêtres et porte CSG ajourées à croisillons, perron pierre), `tree` (racines et branches `tube_sweep`, couronnes organiques), `sword` et `motocross` (disques Wave ajourés, ailettes moteur, couronne dentée).
> 3. **Rasteriseur UV NumPy vectorisé `×80` plus rapide (`scripts/pbr.py`)** : `rasterize_uv_triangles` (< `0,35 s` en `1024 × 1024`) + compression PNG sans perte `compress_png` gardant l'intégralité du dépôt légère et rapide.
> 4. **Verre Cristal Réfractif, Vernis Clearcoat & Visionneuse `preview.html` v2** : extensions officielles glTF 2.0 (`KHR_materials_transmission`, `KHR_materials_ior`, `KHR_materials_clearcoat`), réfraction linéaire + réflexion interne totale (TIR) dans `renderer.py`, et inspecteur WebGL interactif hors-ligne avec **4 éclairages HDRI**, **ombre de contact douce** et **7 canaux techniques** (`PBR`, `Albédo`, `Roughness`, `Metallic`, `Normales`, `AO`, `Filaire`).
> 5. **Hiérarchie `.glb` articulée & Découpe Plateau Imprimante 3D (`scripts/split_stl.py`)** : pivots d'articulation nommés (`front_axle`, `rear_axle`, `front_wheel`, `steering`, `front_door`) animables en direct dans `preview.html`, et découpe automatique des grands modèles (ex. `katana.stl` d'1 m découpé en **5 pièces étanches** pour plateau `256 × 256 × 256 mm` avec **7 tenons/mortaises chanfreinés à jeu paramétrique `0,20 mm`**).

Là où un service text-to-3D devine une approximation ballonneuse de « une chaise »,
un agent peut **raisonner** la géométrie — quatre pieds, une assise à 45 cm, un
dossier incliné — et l'exprimer exactement. 3d-forge fournit l'usine déterministe
qui transforme ce raisonnement en maillage propre, étanche, texturé PBR, livré en
GLB / OBJ / STL / USDZ avec photos de toutes les faces — et il impose la même
discipline qu'un service en ligne : **recherche de références avant, autocritique
notée après.**

```
« une épée médiévale rouillée avec pommeau en or »
        │
        ▼
 STAGE 0 · recherche web ──────► photos réelles → planche « détails à respecter »
        │                          + palette mesurée (palette_hints.json)
        ▼
 L'AGENT DESSINE 3 VUES ───────► face / profil / dessus, peintes par matériaux
        │                          (sa « synthèse multi-vues », comme Meshy)
        ▼
┌────────────────────────────────────────────────────────────┐
│  MOTEUR DÉTERMINISTE (scripts/, 100 % local)               │
│  hull visuel → marching cubes → lissage Taubin             │
│  → décimation (budget triangles) → UV xatlas               │
│  → textures PBR procédurales (albedo + metallicRoughness   │
│    + normal, rouille / usure d'arêtes / bandes)            │
│  → rendus PNG (rasterizer numpy, sans GPU)                 │
└────────────────────────────────────────────────────────────┘
        │
        ▼
 PHOTOS DES 6 FACES + TURNTABLE → AUTOCRITIQUE NOTÉE /10
        │
        ├─ note < 9.5  ► paufiner : corriger la spec, régénérer, re-critiquer
        └─ note ≥ 9.5  ► LIVRAISON : GLB · OBJ+MTL · STL étanche · USDZ · photos
```

---

## Comment ça marche

### Le principe : l'agent est le générateur

Aucun réseau de neurones ne tourne ici — et il n'en faut pas. La répartition des
rôles est la suivante :

- **L'agent (le LLM)** raisonne : il décompose l'objet, choisit des dimensions
  réalistes en mètres, dessine les vues, choisit les matériaux PBR, lance la CLI,
  **regarde les rendus**, diagnostique les défauts et corrige.
- **Le code (`scripts/`)** exécute : primitives, CSG manifold, hull visuel,
  marching cubes, UV, bake de textures, rendus, exports, mesures IoU, QA.
  Tout est déterministe et reproductible — même prompt, même objet, à l'identique.

C'est exactement l'architecture d'un pipeline text-to-3D moderne, avec le LLM
branché à la place du modèle de diffusion à **chaque** étape :

| Étape Meshy | Équivalent 3d-forge | Qui fait quoi |
|---|---|---|
| 1. Représentation interne | Spec JSON : palette PBR + 3 vues ASCII | l'agent écrit, le code valide |
| 2. Synthèse multi-vues | Dessin cohérent face / profil / dessus | l'agent (c'est son « latent ») |
| 3. Reconstruction de volume | Hull visuel (intersection d'extrusions) | le code |
| 4. Nettoyage / retopo | Marching cubes → Taubin → décimation | le code |
| 5. UV | Unwrap xatlas (coutures auto, atlas) | le code |
| 6. Textures PBR multi-cartes | Bake procédural reprojété des 3 vues : albedo + metallicRoughness + normal + overlays | le code, palette choisie par l'agent |
| 7. Vérification de cohérence | IoU silhouette par vue + photos 6 faces + turntable + autocritique notée | le code mesure, **l'agent juge** |

### Stage 0 — la recherche web (obligatoire, non contournable)

Avant toute génération d'un objet nouveau, l'agent doit se raccrocher à la
réalité — l'équivalent déterministe des données d'entraînement d'un modèle de
diffusion :

1. **Recherche web** : une requête pour l'objet global, une par détail notable
   (« pommeau doré gros plan », « gouttière d'épée »), une pour la matière
   (« texture métal rouillé »).
2. **Téléchargement de 3–6 images publiques** :
   `python3 scripts/research.py fetch --urls URL1 URL2 ... --dir refs_raw/`
3. **Planche des détails à respecter** :
   `python3 scripts/research.py build --dir refs_raw/ --title "..." --out ... \
       --queries "..." --notes "pommeau disque doré" "gouttière centrale" ...`
   → `reference_sheet.png` (vignettes + palettes par image + notes + traçabilité
   des requêtes) et `palette_hints.json` (couleurs dominantes mesurées,
   indices metallic/roughness). **Ces notes deviennent le contrat QA** : chaque
   détail listé doit être visible sur les photos finales, sinon on ne livre pas.

Pas d'accès web dans l'environnement ? L'agent doit le dire explicitement et
retomber sur ses connaissances internes — sauter l'étape en silence est interdit.

### Quatre workflows selon le point de départ

| Workflow | Quand l'utiliser | Outil |
|---|---|---|
| **A — Recettes & Hybride PBR** | l'objet existe dans le catalogue (19 familles paramétriques dont `katana` texturé PBR) ou se compose via `meshkit` + `b.bake_pbr(...)` | `generate.py` / `meshkit.py` |
| **B — Image → 3D** | l'utilisateur fournit une photo de référence (filtrage auto de l'ombre au sol dans `compare.py`) | `img2mesh.py` + `compare.py` |
| **C — Génération multi-vues v2** (« Meshy mode ») | formes organiques/forgées : **canevas vectoriel 2D continu** (`spline`, `capsule`, `ellipse`, `poly`) ou ASCII → SDF 3D anisotrope + bake PBR 3 cartes | `meshgen.py` + spec JSON |
| **D — Multi-parties** (« katana mode ») | objets composites mixant specs `meshgen`, `recipe` et `.glb` générés **en parallèle** avec cache par pièce et union `manifold3d` étanche | `assemble.py` + manifest |

Les workflows se combinent librement : un objet paramétrique `meshkit` précis (`rounded_box`, `loft`, `sweep`) peut recevoir un unwrap `xatlas` + bake PBR complet (`rust`, `wrap` / `diamond` *tsuka-maki*, `hamon`, `wood_grain`, `brushed_metal`, `edge_wear`, `patina` + carte de normales tangentes) via `Builder.bake_pbr(...)`, et `assemble.py` peut mixer pièces paramétriques et pièces SDF multi-vues dans la même scène.

**A — Recettes paramétriques (19 familles, 19/19 étanches)** : chaise, table, tabouret, bibliothèque, lampe, mug, vase (4 formes), bouteille, bol, assiette, verre à pied (profil spline PCHIP + verre multi-couches), pion d'échecs, épée, **katana forgé PBR (`sweep` courbure *sori* + tressage *tsuka-maki* en losanges + *hamon*)**, fusée, maison, arbre, voiture, motocross (154 pièces, union étanche en 0,19 s).

**B — Image → 3D** : segmentation (fond uni détouré dans `research.py` + filtrage automatique de l'ombre portée au sol dans `compare.py`), contour, profil de largeur W(z), construction `revolve` / `extrude` / `loft`, puis scoring **IoU de silhouette** mesh vs photo (ex. motocross KTM : IoU global **0,747**, zone basse **0,794** sans fausse pénalité d'ombre).

**C — Génération multi-vues v2 (`meshgen.py`)** : vues vectorielles 2D continues sans marche d'escalier (`spline`, `poly`, `rect`, `ellipse`, `capsule`, ajourages `void`) ou vues ASCII classiques, grille SDF 3D anisotrope (`dims` + `grid`) préservant les lames de 4–8 mm, unwrap `xatlas`, puis bake PBR glTF 2.0 complet (`baseColorTexture` + `metallicRoughnessTexture` + `normalTexture`). Exemple de référence : [`specs/epee_rouillee.json`](specs/epee_rouillee.json) — 15 000 tris, **étanche**, **IoU moyen = 0,9152** (`face 0,928` · `profil 0,873` · `dessus 0,945`).

### Stage 3 — l'autocritique notée (la boucle 9.5, obligatoire)

C'est la règle de qualité du skill, appliquée **verbatim** par l'agent après
chaque génération :

> **Tu t'autocritique sur une note de 1/10. Si la note est inférieure à 9.5,
> continue à paufiner. Sinon, envoie-moi le résultat.**

Le prompt intégral à copier dans le contexte d'un agent vit dans
[`AUTOCRITIQUE.md`](AUTOCRITIQUE.md), et le code (`critique.py`) structure la
boucle tout en **empêchant la complaisance mécaniquement** :

```bash
# 1. BRIEF — la fiche de critique de cette itération
python3 scripts/critique.py brief --dir out/epee --iter 1
#    → métriques objectives (IoU par vue, étanchéité, budget), la LISTE des
#      photos à ouvrir, la checklist des détails Stage 0, le barème /10
#      (S silhouette 3 · V volume 2 · M matériaux 2 · D détails 2 · T technique 1)

# 2. VERDICT — après avoir VRAIMENT ouvert chaque photo
python3 scripts/critique.py verdict --dir out/epee --iter 1 \
    --note 7.2 --justification "proportions ok, détails manquants" \
    --issue "S|pointe trop fine|mangée par le lissage : res 80->96, smooth 10->7" \
    --issue "D|gouttière invisible de profil|peindre le fuller dans side aussi"
#    → REFINE  (note < 9.5 : corriger, régénérer dans iter_2, re-critiquer)
#      DELIVER (note ≥ 9.5 avec --deliver : seulement maintenant on livre)

# 3. STATUS — historique des notes et tendance
python3 scripts/critique.py status --dir out/epee
```

Gardes-fous appliqués par le code, pas par la volonté :

- une note ≥ 9.5 **avec des issues ouvertes** est REFUSÉE ;
- une note < 9.5 **sans aucun issue** est REFUSÉE (le diagnostic est obligatoire) ;
- IoU moyen < 0.5 ⇒ toute note ≥ 9.5 est impossible ;
- un 10 donné sans avoir ouvert les photos est de la triche (`critique_log.json`
  garde la trace) ;
- budget d'itérations épuisé (défaut 4) → **FORCE_DELIVER** : note finale
  honnête + issues résiduelles documentées et annoncées. Jamais de faux 9.5.

Chaque itération régénère dans son propre dossier (`out/epee/iter_1/`,
`iter_2/`, …). Boucle réelle sur l'épée rouillée : notes 5.0 → 6.0 → 8.1 → 7.0
→ 7.5 → 8.6, et l'autocritique a **découvert un vrai bug moteur** au passage
(sommets de surface clippés vers le matériau principal, corrigé par
réattribution nearest-occupied-voxel).

### La boucle de photos : « générer → photographier → corriger »

Chaque génération complète (`--faces all`) produit les **photos des 6 faces**
(face, dos, gauche, droite, dessus, dessous) + planche contact
`*_all_faces.png`, et un **turntable 8 angles** + planche. L'agent relit ces
photos comme on relit la galerie de preview de Meshy : les trois faces
frontales doivent raconter la même histoire que les trois vues dessinées, et
chaque détail du Stage 0 doit y être visible. Un détail qu'on ne peut pas
montrer est un détail qu'on n'a pas construit.

---

## Installation — qui installe quoi ?

**Tu veux juste utiliser le skill avec un agent (GLM, Claude…) ? Tu n'installes RIEN.**
Ton PC reste une simple fenêtre de chat. L'agent fait tout : il récupère le
skill, installe les dépendances **dans son propre environnement d'exécution**
(les serveurs où il tourne — pas ta machine), génère l'objet et te rend les
fichiers. Colle-lui simplement :

> Prends le skill https://github.com/DimalaxYT/3F : télécharge-le dans ton
> environnement, installe ses dépendances (requirements.txt), puis suis son
> SKILL.md pour me générer : « une épée médiévale rouillée avec pommeau en or ».

**Tu es l'agent (ou un dev qui veut l'exécuter soi-même)** — une seule fois,
dans l'environnement qui exécute le code :

```bash
git clone https://github.com/DimalaxYT/3F.git
cd 3F
pip install -r requirements.txt
python3 scripts/detect_env.py    # vérifie l'environnement
```

Dépendances : `numpy`, `trimesh`, `manifold3d` (CSG étanche), `shapely`
(extrusions), `pillow`, `scipy`, `scikit-image` (marching cubes), `xatlas` (UV),
`fast-simplification` (décimation), `matplotlib` (diagnostics image→3D),
`usd-core` (USDZ natif Pixar).

**Aucune clé API, aucun compte, aucun téléchargement de modèle, aucun GPU.**
Ça tourne sur un CPU de Raspberry Pi comme sur un serveur. Pour vérifier
l'environnement : `python3 scripts/detect_env.py`.

## Comment le faire fonctionner

### 1. En ligne de commande (standalone)

```bash
# cataloguer les recettes et leurs paramètres
python3 scripts/generate.py --list

# WORKFLOW A — recette + personnalisation (dimensions en mètres !)
python3 scripts/generate.py vase --set shape=amphora height=0.35 color="#7a2e1d" \
    --formats glb obj stl usdz --out ./out
python3 scripts/generate.py chair --set style=scandinavian wood_color="#b08850" \
    seat_color="#2c3e70" --faces all --out ./out

# WORKFLOW C — génération multi-vues « Meshy »
python3 scripts/meshgen.py specs/epee_rouillee.json --out out/epee \
    --faces all --references out/epee/references

# WORKFLOW B — image → 3D
python3 scripts/img2mesh.py analyze photo.png --out out/analyze
python3 scripts/img2mesh.py build out/analyze/analysis.json --mode revolve \
    --height 0.35 --material ceramic --out out/obj
python3 scripts/compare.py --mesh out/obj/obj.glb --ref photo.png --axes xz --out out/cmp

# QA
python3 scripts/validate.py out/vase/vase.stl     # exit 1 si non imprimable
```

Chaque génération écrit un dossier `out/<objet>/` : les 4 formats, les rendus
PNG, les photos de faces, une **`preview.html` interactive autoportante**
(viewer 3D + GLB embarqué en base64 : double-clic, ça s'ouvre dans n'importe
quel navigateur, matériaux PBR compris — c'est le « lightweight preview » à
partager ou à ouvrir pour voir ce que l'IA a fait), et un `report.json`
(paramètres, triangles, étanchéité, IoU par vue, checklist des détails,
photos) — **le rapport QA officiel à lire avant de livrer**.

### 2. Comme skill d'agent (Claude, GPT, …)

C'est le mode d'usage principal. Le dépôt est un skill au format standard :

1. Copier le dossier `3d-forge/` dans le répertoire de skills de votre agent
   (ex. `.claude/skills/3d-forge/`).
2. L'agent découvre `SKILL.md` (frontmatter + instructions complètes : conven-
   tions Z-up/mètres, workflows, quality gates, troubleshooting).
3. Pour la boucle de qualité, ajouter le contenu d'[`AUTOCRITIQUE.md`](AUTOCRITIQUE.md)
   au contexte — c'est le prompt d'autocritique notée qui impose la règle 9.5.
4. Demander simplement : *« génère-moi une épée médiévale rouillée avec pommeau
   en or »* — l'agent enchaîne alors : recherche web → planche des détails →
   spec 3 vues → meshgen → photos 6 faces → autocritique notée → itérations →
   livraison, en suivant les 7 quality gates de SKILL.md.

### 3. En bibliothèque Python (géométrie 100 % sur mesure)

Quand aucune recette ne convient, l'agent écrit directement avec `meshkit` —
c'est le cœur du concept (méthode complète et patterns dans
[`references/cookbook.md`](references/cookbook.md)) :

```python
import sys; sys.path.insert(0, "<chemin>/3d-forge/scripts")
import meshkit as mk

b = mk.Builder("table_basse")
b.add(mk.box(0.9, 0.5, 0.04), mk.mat.wood("#b08850"), name="plateau", at=(0, 0, 0.42))
b.add(mk.cylinder(0.025, 0.42), mk.mat.metal("#444a52"), name="pied", at=(0.35, 0.15, 0))
b.union_solid()
b.export_glb("table_basse.glb")
```

### Conventions à connaître

- **Unités** : mètres (un mug fait 0.095 de haut, une porte 2.0).
- **Axe vertical** : Z (posé au sol, base à z=0). Les GLB sont Z-up — la plupart
  des viewers importent en Y-up : rotation −90° sur X si besoin.
- **Face avant** : −Y.
- **Étanchéité garantie** : toute sortie CSG / lathe / extrude est watertight.
  Si `validate.py` dit le contraire, le bug est en amont — on répare, on ne
  livre pas.

---

## Architecture du dépôt

```
3d-forge/
├── SKILL.md                  ← point d'entrée agent (workflows, gates, protocoles)
├── AUTOCRITIQUE.md           ← le prompt de la boucle notée 1–10 / seuil 9.5
├── PLAN.md                   ← architecture détaillée + roadmap
├── scripts/
│   ├── meshkit.py            ← primitives, CSG (manifold3d), lathe, extrude,
│   │                            matériaux PBR (8 métaux physiques), Builder, OBJ+MTL
│   ├── meshgen.py            ← WORKFLOW C : vues ASCII → hull → marching cubes
│   │                            → Taubin → décimation → UV xatlas → bake PBR
│   ├── assemble.py           ← WORKFLOW D : manifest multi-parties → meshgen
│   │                            PARALLÈLE par partie → assemblage (GLB groupé,
│   │                            STL union étanche) — cache par partie pour
│   │                            itérer « bout par bout »
│   ├── preview.py            ← preview.html autoportante (model-viewer + GLB
│   │                            base64 + photos) — un fichier, double-clic
│   ├── img2mesh.py           ← WORKFLOW B : photo → segmentation → profil → mesh
│   ├── compare.py            ← IoU silhouette mesh vs photo + overlay par zones
│   ├── research.py           ← STAGE 0 : fetch images web → planche « détails
│   │                            à respecter » + palette_hints.json
│   ├── critique.py           ← STAGE 3 : boucle d'autocritique notée (brief /
│   │                            verdict / status, gardes anti-complaisance)
│   ├── renderer.py           ← rasterizer numpy : z-buffer, SSAA 2×, Blinn-Phong
│   │                            3 lumières, ombre de contact, ACES, 6 faces + turntable
│   ├── generate.py           ← CLI recettes (--set, --faces all, 4 formats, report)
│   ├── validate.py           ← QA mesh (étanchéité, volume, composants, dégénérées)
│   ├── detect_env.py         ← sonde CPU/GPU/dépendances
│   ├── usdz_export.py        ← USDZ natif (usd-core) + fallback USDA zippé
│   └── recipes/              ← catalogue 18 recettes (registry + furniture/containers/props)
├── specs/epee_rouillee.json  ← exemple de référence du workflow C
├── references/               ← cookbook.md (méthode sur mesure) + materials.md
├── examples/                 ← modèles générés prêts à télécharger (épée, motocross…)
├── tests/                    ← pytest : smoke 18/18, meshgen, img2mesh, motocross
├── evals/evals.json          ← prompts d'évaluation du skill
├── docs/img/                 ← galerie générée par le pipeline lui-même
└── neural/                   ← fallback neuronal optionnel (GPU), désactivé par défaut
```

## Exemples

Galerie générée par le pipeline (rendus `three_quarter`, qualité 0.75) :

![galerie](docs/img/gallery.png)

Des modèles finis, prêts à télécharger, vivent dans [`examples/`](examples/) :

| Exemple | Workflow | Points forts |
|---|---|---|
| [`examples/katana/`](examples/katana/) | D — multi-parties | 5 parties vectorielles générées **en parallèle** (`kashira`, `tsuka` losanges *tsuka-maki*, `tsuba` *sukashi* ajourée, `habaki` laiton, `blade` courbée *sori* + *hamon*), **STL union 100 % étanche**, `preview.html` WebGL hors-ligne |
| [`examples/epee_rouillee/`](examples/epee_rouillee/) | C — multi-vues v2 | GLB **texturé PBR** (rouille multi-octaves piquée, normal map tangente, cuir spiralé, pommeau or), **IoU moyen = 0.9152** (`profil = 0.8725`), 6 faces + turntable + `preview.html` hors-ligne |
| [`examples/motocross/`](examples/motocross/) | A/B — CAD + photo | 154 pièces, moteur & cadre twin-spar en relief 3D, union étanche en **0.19 s**, overlay silhouette sans ombre au sol (`IoU = 0.7468`, bas `0.7936`) |
| [`examples/chaise_scandinave/`](examples/chaise_scandinave/) · [`vase/`](examples/vase/) · [`rocket/`](examples/rocket/) | A — recettes | paramétrique, STL prêts impression |

Sorties d'une génération complète d'épée (workflow C + Stage 0 + boucle 9.5) :
GLB texturé (`albedo` + `metallicRoughness` + `normal` 1024²), OBJ+MTL avec UVs,
STL étanche, USDZ aligné 64 octets avec textures embarquées, `preview.html`
WebGL 100 % hors-ligne, planche des 6 faces et turntable 8 angles.

## Pourquoi « sans API » ?

| | Meshy & co | 3d-forge |
|---|---|---|
| Coût | abonnement + crédits | gratuit |
| Confidentialité | vos prompts partent chez un tiers | 100 % local |
| Déterminisme | seed à chaque essai | reproductible à l'identique |
| Éditable | non (mesh opaque) | oui (paramètres + spec + code) |
| Étanchéité garantie | non | oui (CSG manifold) |
| Viewer 3D interactif | cloud propriétaire | `preview.html` WebGL PBR **100 % hors-ligne** (0 CDN) |
| Références réelles | implicites | Stage 0 explicite, fond studio détouré, traçable |
| Contrôle qualité | un aperçu | photos 6 faces + IoU + note /10 imposée |
| Temps | ~30 s – 5 min | 0,2 – 90 s |

**Le compromis honnête** : 3d-forge ne sculpte pas d'organique anatomique fin
(visages humains, drapés libres). Pour du sculptural avec GPU NVIDIA,
`neural/README.md` documente le branchement d'un fallback local open-source
(TripoSR, Hunyuan3D, TRELLIS) — le skill fonctionne entièrement sans lui.

## Tests

Toute la suite s'exécute directement via `pytest` (18 tests couvrant les 19 recettes,
`meshkit` v2, l'alignement UV `.glb`/`.obj`/`.usdz`, `meshgen` v2 vectoriel,
`pbr.py`, `renderer.py`, `img2mesh.py`, `research.py`, `compare.py` et `preview.py` hors-ligne) :

```bash
python3 -m pytest -v             # 18/18 tests (inclut smoke 19/19 recettes + motocross + v2)
python3 tests/test_smoke.py      # tableau détaillé des 19 recettes (étanchéité + volume + dims)
python3 tests/test_motocross.py  # benchmark rapide build + union booléenne motocross
```

## Licence

MIT — voir [LICENSE](LICENSE).
