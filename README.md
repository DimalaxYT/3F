# 3d-forge 🔨

**Générateur 3D pour agents LLM — façon Meshy, mais sans API, sans GPU, sans réseau.**

> Le LLM **est** le modèle de diffusion. Le code n'exécute que la géométrie.

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

### Trois workflows selon le point de départ

| Workflow | Quand l'utiliser | Outil |
|---|---|---|
| **A — Recettes** | l'objet existe dans le catalogue (18 familles paramétriques) | `generate.py` |
| **B — Image → 3D** | l'utilisateur fournit une photo de référence | `img2mesh.py` + `compare.py` |
| **C — Génération multi-vues** (« Meshy mode ») | tout le reste : formes organiques, props composites, objets sans recette ni photo | `meshgen.py` + spec JSON |

Les trois se combinent : on peut dessiner les vues du workflow C **guidé par les
mesures** du workflow B (`img2mesh analyze` donne le profil de largeur, l'aspect,
les couleurs dominantes).

**A — Recettes paramétriques** : chaise, table, tabouret, bibliothèque, lampe,
mug, vase (4 formes), bouteille, bol, assiette, verre à pied, pion d'échecs,
épée, fusée, maison, arbre, voiture, motocross. Paramètres coercés (float, int,
bool, choice, color), clés inconnues rejetées avec la liste valide.

**B — Image → 3D** : segmentation (fond uni ou transparent), contour, profil de
largeur W(z), puis trois modes de construction — `revolve` (objets de
révolution, IoU de roundtrip ≈ 0.99), `extrude` (objets plats), `loft` (objets
gonflés, sections super-elliptiques) — puis scoring **IoU de silhouette** mesh
vs photo, global et par tiers, avec overlay rouge/vert/jaune qui montre où
manque et où dépasse la masse. C'est la boucle qui a recalé la motocross du
catalogue sur une photo KTM 450 : IoU 0.55 → 0.74.

**C — Génération multi-vues** : l'agent écrit une spec JSON — palette PBR
(`{id, name, color, metallic, roughness}`) et trois vues ASCII où chaque lettre
peint un matériau. Le moteur en déduit le volume par **hull visuel** (intersection
des extrusions des trois vues : une cellule n'existe que si les trois vues
d'accord), maille en marching cubes, lisse (Taubin), décime au budget de
triangles, unwrap xatlas, puis **bake les textures** en reprojetant les vues sur
l'UV : albedo, metallicRoughness, normal map, plus des overlays procéduraux —
`rust` (bruit fBm 3D par bande de hauteur), `wrap` (enroulement cuir),
`edge_wear` (usure d'arêtes). Résultat : un GLB **vraiment texturé**, pas un
mesh uni. Exemple de référence : [`specs/epee_rouillee.json`](specs/epee_rouillee.json)
— 12 196 tris, étanche, textures 1024², ~39 s.

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
PNG, les photos de faces, et un `report.json` (paramètres, triangles,
étanchéité, IoU par vue, checklist des détails, photos) — **le rapport QA
officiel à lire avant de livrer**.

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
| [`examples/epee_rouillee/`](examples/epee_rouillee/) | C — multi-vues | GLB **texturé PBR** (rouille fBm, usure d'arêtes), 6 faces + turntable, `critique_log.json` (la boucle 9.5 en trace réelle : 5.0 → 8.6) |
| [`examples/motocross/`](examples/motocross/) | B — image → 3D | recalée photo KTM : overlay silhouette, `score.json` IoU 0.55 → 0.74, STL étanche |
| [`examples/chaise_scandinave/`](examples/chaise_scandinave/) · [`vase/`](examples/vase/) · [`rocket/`](examples/rocket/) | A — recettes | paramétrique, STL prêts impression |

Sorties d'une génération complète d'épée (workflow C + Stage 0 + boucle 9.5) :
GLB texturé (albedo + metallicRoughness + normal 1024²), 4 formats, planche des
6 faces, turntable 8 angles, planche des références, `report.json` + `critique_log.json`.

## Pourquoi « sans API » ?

| | Meshy & co | 3d-forge |
|---|---|---|
| Coût | abonnement + crédits | gratuit |
| Confidentialité | vos prompts partent chez un tiers | 100 % local |
| Déterminisme | seed à chaque essai | reproductible à l'identique |
| Éditable | non (mesh opaque) | oui (paramètres + spec + code) |
| Étanchéité garantie | non | oui (CSG manifold) |
| Références réelles | implicites | Stage 0 explicite, traçable |
| Contrôle qualité | un aperçu | photos 6 faces + IoU + note /10 imposée |
| Temps | ~30 s – 5 min | 0,2 – 60 s |

**Le compromis honnête** : 3d-forge ne sculpte pas d'organique complexe
(personnages, créatures) et l'IoU de profil reste structurellement faible sur
les objets très fins (une lame de 0.7 cm vue de côté). Pour du sculptural avec
GPU NVIDIA, `neural/README.md` documente le branchement d'un fallback local
open-source (TripoSR, Hunyuan3D, TRELLIS) — le skill fonctionne entièrement
sans lui.

## Tests

```bash
python3 -m pytest tests/ -v      # 5 tests : meshgen (hull + vues) + img2mesh (roundtrips)
python3 tests/test_smoke.py      # 18/18 recettes étanches, volume > 0
python3 tests/test_motocross.py  # motocross : build + union + étanchéité
```

(`test_smoke.py` et `test_motocross.py` sont des scripts à tableau de sortie,
pas des fonctions pytest — les lancer directement.)

## Licence

MIT — voir [LICENSE](LICENSE).
