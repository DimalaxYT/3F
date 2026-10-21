# IMPROVEMENTS.md — Audit & propositions d'amélioration du skill `3d-forge`

> Audit exécuté le **2026-10-21** dans un bac à sable Arena (branche `arena/51f6a1f4-3f`,
> commit `43fe88b`), Python 3.11 CPU-only, dépendances installées depuis `requirements.txt`
> (+ `matplotlib`, `networkx`). Toutes les commandes de repro sont indiquées.
> Objectif : **améliorer le skill en tant que skill** — fiabilité du protocole agent,
> QA actionnable, documentation à source unique, poids du dépôt, évaluation continue.

---

## TL;DR — 18 propositions classées par priorité

| # | Proposition | Impact | Effort |
|---|---|---|---|
| 1 | Corriger/aliasser le flag `--stl` d'`AGENTS.md` (commande du tour 2 invalide) | 🔴 bloquant | 10 min |
| 2 | Réconcilier `critique.py` et `turbo_forge.py` (`report.json` vs `game_manifest.json`) | 🔴 bloquant | 1 h |
| 3 | Une seule politique de qualité (8.8/1 itération vs 9.5/4 itérations) | 🔴 bloquant | 1 h |
| 4 | Profils explicites `turbo / standard / showcase` (Stage 0 & recherche web) | 🔴 | 2 h |
| 5 | Tests indépendants de l'environnement (`usd-core`) | 🟠 | 30 min |
| 6 | `matplotlib` en import paresseux dans `img2mesh.py` | 🟠 | 20 min |
| 7 | `detect_env.py` exhaustif + `--fix` | 🟠 | 30 min |
| 8 | CLI `scripts/gates.py` → `gates.json` + code de sortie | 🟠 fort | 3 h |
| 9 | `qa_game_sheet.png` v2 : cadrage auto, ortho + règle d'échelle, ColorMap Roblox, carte de gates | 🟠 fort | 4 h |
| 10 | Corriger les artefacts de normales sur LOD2 | 🟠 | 2 h |
| 11 | `turbo_forge --quiet` (résumé 6 lignes au lieu du manifest JSON complet) | 🟢 | 30 min |
| 12 | Découper `SKILL.md` (43,7 Ko / 5 780 mots) en corps court + `references/` | 🟠 fort | 4 h |
| 13 | Générer tables recettes + bench depuis le code (dérives chiffrées constatées) | 🟠 | 2 h |
| 14 | Une seule copie du protocole agent (6 duplications aujourd'hui) | 🟠 | 1 h |
| 15 | Alléger le dépôt (pack git 165,6 Mo ; `preview.html` 14 Mo) via LFS/branche assets | 🟠 | 3 h |
| 16 | Étendre `evals/` au chemin v5.1 + harnais `evals/run.py` | 🟠 fort | 4 h |
| 17 | Mettre à jour les plafonds Roblox documentés (20 k tris/mesh, UGC 4 k) + `--target ugc` | 🟢 | 1 h |
| 18 | `qa_summary.md` généré pour des livraisons homogènes | 🟢 | 1 h |

---

## 0. Ce qui marche — ne pas y toucher

Mesuré sur `sci_fi_crate --lod0-tris 2800` : **21,9 s** bout en bout (promesse « 12–20 s »
tenue à la machine près), STL `is_watertight: true`, pack `roblox/` conforme
(6 images `image/png`, zéro `EXT_texture_webp`, `size_studs_xyz` cohérent,
`setup_*.lua` avec `Enum.Material.Neon` + `HingeConstraint` + `ProximityPrompt`),
pack `unreal/` complet (`UCX_*`, BC/ORM/N). Suite pytest : **39 passed, 1 failed en 84 s**.
Les gates Roblox sont déjà *écrits* dans `tests/test_v5_game_ready.py`
(PNG-only, `< 10 k tris/part`, Studs, AO dans ColorMap, Luau) : c'est un excellent
socle — le problème est qu'ils ne sont **pas exposés** à l'agent ni à la CI E2E (voir §8).

---

## P0 — Le protocole obligatoire se casse lui-même

### 1. La commande du « TOUR 2 » d'`AGENTS.md` est invalide (`--stl` n'existe pas)
**Constat** : `AGENTS.md` impose
`python3 scripts/turbo_forge.py custom_<nom>.py --name <nom> --lod0-tris 4800 --stl -o out/<nom>`.
Or `turbo_forge.py` ne définit que `--no-stl` (le STL est déjà actif par défaut).
**Repro** : `python3 scripts/turbo_forge.py katana --name katana --lod0-tris 4800 --stl -o /tmp/x`
→ `error: unrecognized arguments: --stl` (exit 2). Le protocole « 3 tours » échoue donc
au premier vrai appel, et un agent docile perd un tour à déboguer.
**Fix** : accepter `--stl` comme alias explicite (action `store_true`, no-op documenté)
*et* corriger `AGENTS.md`. **Acceptation** : la commande littérale d'`AGENTS.md` sort en 0.

### 2. `critique.py` (QA notée obligatoire) est incompatible avec `turbo_forge.py` (chemin obligatoire)
**Constat** : `critique.py` lit `out/<dir>/iter_N/report.json` ; `turbo_forge.py` n'écrit que
`game_manifest.json`. **Repro** : `python3 scripts/critique.py brief --dir out/x --iter 1`
après un run turbo → `report.json introuvable — lance d'abord meshgen.py`.
Conséquence : sur le chemin principal, la boucle d'autocritique notée (exigée par
`SKILL.md`, `AUTOCRITIQUE.md`, `CLAUDE.md`) est **inexécutable** ; l'agent note « à l'œil »
sans métriques objectives, exactement ce que le barème interdit.
**Fix** : schéma unique `report.json` (turbo l'écrit en plus du manifest, avec
`watertight`, `tris`, `studs`, `iou_views` le cas échéant) ou `critique.py --manifest`.
**Acceptation** : `critique.py brief/verdict/status` fonctionne sur une sortie turbo.

### 3. Deux politiques de qualité contradictoires dans les docs vs le code
**Constat** : `scripts/critique.py` → `THRESHOLD_DEFAULT = 8.8`, `MAX_ITERS_DEFAULT = 1` ;
`AUTOCRITIQUE.md` → 8.8 / 1 ; mais `SKILL.md` (Stage 3 + Quality gates) → seuil **9.5**,
budget **4** itérations, « note ≥ 9.5 avec DELIVER ». Un agent qui suit `SKILL.md` relance
4–5 boucles de 20 s + re-lectures d'images : le comportement que la « SPEED RULE » interdit.
**Fix** : le code est la source de vérité ; `SKILL.md` dit « seuil = `critique.py policy` » ;
ajouter `critique.py policy` qui imprime seuil/budget actifs ; supprimer les chiffres codés
en dur des docs. **Acceptation** : `grep -n "9.5" SKILL.md AUTOCRITIQUE.md` ne contient plus
de seuil normatif.

### 4. Stage 0 « MANDATORY » vs « NE JAMAIS lancer research.py fetch »
**Constat** : `SKILL.md` impose 3 requêtes web + `research.py fetch` avant chaque génération ;
`AGENTS.md`/`CLAUDE.md` l'interdisent (pare-feu, timeouts). Même conflit sur `--faces all`
(14 images) vs 1 planche.
**Fix** : définir 3 profils nommés une fois pour toutes — `turbo` (défaut agent : 0 fetch,
1 planche, 1 retouche max), `standard` (Stage 0 léger, 3 vues), `showcase` (Stage 0 complet,
`--faces all`, critique 9.5) — et préfixer chaque section de doc par le profil concerné.

### 5. La suite de tests dépend de l'environnement (1 échec reproductible)
**Constat** : `tests/test_v2_features.py::test_obj_mtl_and_usdz_texture_export` assert
`res["engine"] == "usd-core"` → **échoue** dès que `usd-core` n'est pas installé (ce bac :
`AssertionError: 'usda-fallback' == 'usd-core'`) ; la CI masque le problème car elle installe
`requirements.txt`. Le fallback usda — un chemin de production réel — n'est jamais testé.
**Fix** : `pytest.importorskip` pour l'assertion usd-core + un test dédié du fallback.

### 6. `matplotlib` importé au niveau module : Workflow B mort sans lui
**Constat** : `scripts/img2mesh.py:37` importe `matplotlib` à l'import ; `compare.py` importe
`img2mesh` → sans matplotlib, `pytest` **ne collecte même pas** `test_img2mesh.py` /
`test_v2_features.py`, et `compare.py` (le score IoU du Workflow B) est inutilisable.
**Fix** : import paresseux dans les seules fonctions de tracé ; `detect_env.py` le signale.

### 7. `detect_env.py` ne rapporte pas la moitié des dépendances réelles
**Constat** : sorties actuelles = numpy/trimesh/manifold/shapely/pillow/scipy/usd/gpu.
Manquent `xatlas`, `fast_simplification`, `scikit-image`, `matplotlib`, `networkx` — tous
utilisés par les pipelines v4/v5. Un agent ne peut pas diagnostiquer un échec.
**Fix** : table complète + `detect_env.py --fix` qui imprime la ligne `pip install` exacte.

---

## P1 — Rendre la QA lisible et actionnable par un agent

### 8. Exposer les gates en CLI : `scripts/gates.py` → `gates.json` + exit code
Les assertions existent déjà (`tests/test_v5_game_ready.py` : PNG-only Roblox, `< 10 k tris/part`,
Studs 2.8–3.8, AO dans ColorMap, Luau, `-Y` DirectX, ORM/MaskMap). Mais l'agent ne peut que
*regarder une image*. **Fix** : `python3 scripts/gates.py out/<nom> --target hero|ugc|print`
→ `gates.json` (1 ligne par gate : `pass/fail/valeur/attendu`) + code de sortie non nul ;
`turbo_forge.py --check` l'appelle en fin de run ; étape CI E2E dédiée.
**Gates proposés** : tris/part ≤ 9 800 (hero) / 4 000 (ugc) ; textures Roblox `image/png` et
≤ 1024² ; STL watertight + volume > 0 ; dims Studs ∈ [0.1, 2048] ; LOD0 > LOD1 > LOD2 ;
`setup_*.lua` non vide et parsable (identifiants) ; `UCX_*` présents si `--engine` unreal ;
normal map `-Y` cohérente avec `+Y` GL.

### 9. `qa_game_sheet.png` v2 — l'unique image lue par l'agent doit porter l'information
**Constat (visuel)** : la planche = **un seul angle** (three_quarter) décliné sur High-Poly /
LOD0 / LOD2 + colliders + normal + ORM. (a) Sur `examples/katana/game_ready/qa_game_sheet.png`,
l'objet occupe ~10 % des pixels de chaque panneau (pas de cadrage auto) : juger une silhouette
y est impossible. (b) Une erreur de proportion latérale (vue `side` inversée, le piège n°1
documenté par le skill lui-même) est **invisible** puisqu'aucune vue ortho n'est montrée.
(c) La `ColorMap` Roblox (AO cuit) — ce que le joueur voit vraiment — n'apparaît pas.
**Fix** : cadrage auto par bbox serrée (+10 % de marge) ; panneaux ortho `front`/`side` avec
règle d'échelle double (Studs + cm) ; vignette `ColorMap` Roblox et `BC` Unreal côte à côte ;
7ᵉ panneau « gate card » texte (résultats de §8) ; résolution 2048² pour rester lisible.

### 10. Artefacts de normales sur LOD2
**Constat (visuel)** : panneau 3 de la planche `sci_fi_crate` (run du 2026-10-21) : facettes
noires/épineuses — le LOD2 (698 tris) échantillonne l'atlas de normales **baké pour le LOD0**
(« même atlas UV »), dont les tangentes ne correspondent plus à la surface décimée.
**Fix** : baker une normale par LOD (coût faible en 256²) ou désactiver la normale tangente
sur LOD2 (matériau PBR plat) ; documenter que LOD2 = imposteur/collision visuelle.

### 11. Sortie console économe en tokens
`turbo_forge.py` imprime le manifest JSON indenté (~3 Ko, 100+ lignes) : coût en tokens pour
chaque appel agent. **Fix** : résumé 6 lignes par défaut (chemins clés, tris, watertight,
gates pass/fail, durée), manifest complet seulement avec `--json`.

---

## P2 — Documentation : une seule source de vérité

### 12. Découper `SKILL.md` (43,7 Ko, 5 780 mots, 653 lignes)
Le corps dépasse les bonnes pratiques des Agent Skills (~500 lignes max, divulgation
progressive). **Fix** : corps ≤ 300 lignes = arbre de décision (quelle voie : recette /
custom `.py` / organique 3 vues / photo), protocole 1 commande, conventions, QA ; déplacer
vers `references/` : format de spec meshgen (vectoriel + ASCII), manifest Workflow D,
profils moteurs détaillés, règles de dessin des vues. La table des recettes et le cheatsheet
API deviennent **générés** (voir §13) pour ne plus dériver.

### 13. Générer tables & benchmarks depuis le code (dérives mesurées)
- Registre = **20** recettes ; table `SKILL.md` = « 18 » et omet `katana` + `sci_fi_crate` ;
  `PLAN.md` dit 17 ; `README.md` dit 20.
- Bench `README.md` vs réel (run du 2026-10-21) : `sci_fi_crate` high-poly **4 824 tris doc /
  13 076 réels**, LOD0 **608 Ko doc / 1,09 Mo réel** ; `katana` LOD0 **2 598 tris doc /
  8 200 réels** (voir `examples/katana/game_ready/game_manifest.json`).
**Fix** : `generate.py --list --markdown` → table injectée dans SKILL/README ;
`scripts/bench.py --write docs/bench.json` (tris, Ko, s par asset) + job CI qui régénère et
échoue si le doc diffère.

### 14. Fusionner les 6 copies du protocole agent
`SKILL.md` (bloc speed), `AGENTS.md`, `CLAUDE.md`, `PROMPT_AGENT_IA.md`,
`.github/copilot-instructions.md`, `README.md` (bloc prompt) répètent le protocole avec des
variantes (c'est là que `--stl` et « 9.5 » ont survécu). **Fix** : `SKILL.md` = source ;
les 5 autres = 5 lignes de pointeur + le prompt copiable.

---

## P3 — Poids du dépôt & distribution

### 15. 165,6 Mo de pack git, `examples/` = 174 Mo, `preview.html` jusqu'à 14 Mo
`PROMPT_AGENT_IA.md` demande aux agents de **cloner** le dépôt : sur un bac contraint,
c'est lent voire fatal. Causes : `.glb/.stl/.usdz/.png` d'exemples + `preview.html` qui
embarque le GLB en base64 (ex. `examples/dragon_buste/preview.html` = 14 Mo ; un run
`sci_fi_crate` produit un `preview.html` de 7 Mo pour 2 798 tris, car il embarque le GLB
**PNG** de 4 Mo au lieu du GLB webp de 1,09 Mo).
**Fix** : (a) `preview.py --embed {webp-lod0,lod2,none}` (défaut `webp-lod0`, `none` =
référence relative) ; (b) exemples binaires vers Git LFS **ou** branche orpheline
`examples-assets` / release GitHub, en gardant 2 exemples légers (`vase`, `chaise`) en repo ;
(c) `.gitignore` : `out/` déjà exclu ✓.

---

## P4 — Évaluer le skill lui-même, et coller à la réalité des moteurs

### 16. `evals/evals.json` ne couvre que la v1
4 prompts (vase, lampe, maison, pion) — aucun sur le chemin v5.1 qui est pourtant le chemin
obligatoire (turbo, custom builder, organique 3 vues, gates Roblox/UE5, split print).
**Fix** : +6 evals avec `expected_output` vérifiable par fichier (watertight, tris/part,
mime PNG, présence `setup_*.lua`, `gates.json` pass) et un harnais `evals/run.py` headless
(exécute le protocole, asserte, imprime un score) → métrique de progression du skill,
exécutable en CI.

### 17. Plafonds Roblox documentés à jour + profil UGC
Les docs présentent « Hard 10,000 Triangle Limit per MeshPart » comme la limite moteur.
Spécification Roblox actuelle : **20 000 tris/mesh** (Creator Store), **4 000** pour un
accessoire UGC rigide, textures `SurfaceAppearance` ≤ **1024²** ; ratio **25:7 Studs/m**
(= 0,28 m/Stud ✓ déjà correct ici). Garder 9 800 comme *budget de perf* est une bonne
pratique, mais il faut le dire, et ajouter `--target ugc` (≤ 4 000 tris, 1 texture 1024²).
Sources : create.roblox.com/docs/parts/models ; devforum.roblox.com (limite 20 k/21 k).

### 18. `qa_summary.md` généré
Une page markdown (métriques + gates + chemins de livraison + note critique) écrite par
`turbo_forge`/`gates.py` : des messages de livraison homogènes, copiables, auditables.

---

## Plan d'attaque suggéré (3 PR)

1. **PR1 « le protocole ne se casse plus »** (§1–7) : correctifs flags/docs/tests/env.
   Risque nul, ½ journée.
2. **PR2 « QA actionnable »** (§8–11) : `gates.py`, `qa_game_sheet` v2, normales LOD2,
   `--quiet`. 1–2 jours ; c'est le PR qui améliore le plus la qualité perçue des livraisons.
3. **PR3 « docs & distribution »** (§12–18) : découpage SKILL.md, tables/bench générés,
   fusion des prompts, LFS/preview léger, evals v5.1. 2 jours.

*Règle transverse proposée : toute valeur normative (seuil, budget, limite, table, bench)
vit dans le code et est **injectée** dans les docs par génération — plus jamais recopiée.*

---

## Statut d'implémentation — 2026-10-21 (branche `arena/51f6a1f4-3f`)

| # | Proposition | Statut | Preuve / commit |
|---|---|---|---|
| 1 | alias `--stl` + doc AGENTS corrigée | ✅ | `turbo_forge.py --stl` accepté ; commande littérale AGENTS sort 0 |
| 2 | réconciliation `critique.py` ↔ `turbo_forge.py` | ✅ | turbo écrit `report.json` (schéma unifié) ; `critique.py` accepte `game_manifest.json` ; `brief` fonctionne sur sortie turbo |
| 3 | politique de qualité unique | ✅ | `critique.py policy` = source de vérité ; plus aucun seuil normatif recopié (grep `9.5` vide dans SKILL/AGENTS/CLAUDE/README/AUTOCRITIQUE) |
| 4 | profils `turbo/standard/showcase` | ✅ | SKILL.md §contrat de vitesse + en-tête de `references/workflows.md` |
| 5 | tests env-indépendants | ✅ | `test_v2_features` : fallback usda testé, usd-core optionnel |
| 6 | matplotlib paresseux | ✅ | `img2mesh._plt()` ; Workflow B mesurable sans matplotlib |
| 7 | `detect_env.py` exhaustif + `--fix` | ✅ | 12 dépendances listées, commande pip imprimée |
| 8 | `scripts/gates.py` + intégration | ✅ | 13 gates, `gates.json`, exit code ; appelé par `turbo_forge` ; étape CI E2E |
| 9 | `qa_game_sheet.png` v2 | ✅ | 10 panneaux : face/profil + barre d'échelle cm/Studs calibrée, ColorMap Roblox, carte QA |
| 10 | artefacts LOD2 | ✅ | cause racine double : pointes hors bbox (clamp + purge slivers dans `decimate_mesh_clean`) + atlas LOD0 interpolé par triangles géants (bake dédié 128² du LOD2) |
| 11 | sortie console économe | ✅ | résumé 8 lignes ; `--json` pour le manifest complet |
| 12 | découpage SKILL.md | ✅ | 653 → 180 lignes ; `references/workflows.md`, `references/engine_profiles.md`, `references/recipes.md` |
| 13 | tables/bench générés | ✅ | `generate.py --list --markdown` → `references/recipes.md` ; `scripts/bench.py` → `docs/bench.json` + table README entre marqueurs ; CI `--check` + `diff` |
| 14 | fusion des copies du protocole | ✅ | SKILL.md source ; AGENTS/CLAUDE/copilot = pointeurs + séquence outils |
| 15 | poids du dépôt | 🟡 partiel | `preview.html` 8,0 → **1,6 Mo** (GLB webp conservé par chirurgie JSON + vignettes JPEG) ; **migration LFS/histoire des 174 Mo d'`examples/` NON faite** : réécriture d'historique sur `main` = décision propriétaire hors périmètre de la branche |
| 16 | evals v5.1 + harnais | ✅ | 10 evals dont 6 sur le chemin v5.2 ; `evals/run.py` headless (table PASS/FAIL, exit code) ; sous-ensemble en CI |
| 17 | plafonds Roblox à jour + `--target ugc` | ✅ | description SKILL + gates (`hero` 9 800 / `ugc` 4 000 / plafond moteur 20 000 documenté) |
| 18 | `qa_summary.md` | ✅ | écrit par `gates.py`/`turbo_forge` |

### Vérifications exécutées après refonte
- `pytest -q` : **40 passed** (84 s).
- `turbo_forge.py sci_fi_crate` : 18–21 s, gates **13/13**, planche QA v2 propre (LOD2 sans artefacts).
- `critique.py brief/verdict` fonctionnels sur sortie turbo ; `critique.py policy` imprime seuil/budget.
- `evals/run.py` : **10/10 PASS** en local (sous-ensemble 1,4,5,8 en CI).

### Reste à faire (décisions propriétaires ou hors périmètre branche)
- Migration Git LFS / branche orpheline des binaires `examples/` (nécessite un push
  sur `main` + hook LFS côté serveur).
- Lint Luau externe de `setup_<Name>.lua` (compilateur Luau non disponible en CI).
- Test d'import Roblox Studio réel (nécessite l'éditeur, hors sandbox).

---

## Vague v5.3 — implémentée le 2026-10-21 (même branche)

| # | Proposition | Statut | Preuve |
|---|---|---|---|
| A1 | gate animations (`Idle_Action` si joints) | ✅ | `gates.py` ; manifest porte désormais `joints` |
| A2 | gate normales pixel-level DirectX `-Y` | ✅ | `G_unreal == 255 - G_roblox` : 0 pixel incohérent mesuré |
| A3 | gate silhouette LOD0↔LOD2 (proximity) | ✅ | seuils calibrés sur cas sain (moy 0.27 % / p95 1.6 %) ; bug `ProximityQuery.vertex` (tuple) corrigé au passage |
| A4 | gate UV/texel (couverture ≥ 0.5, bornes [0,1]) | ✅ | couverture mesurée 0.84 sur sci_fi_crate |
| A5 | gate + test structure Luau | ✅ | `gates.luau_issues` partagé gate/test ; bug de comptage `for … do` corrigé ; `tests/test_luau_structure.py` |
| A6 | gate budget UCX (≤ 6 hulls / 64 tris) | ✅ | gate à 28 a révélé un vrai défaut : `fast_simplification` ne convergeait pas sur les coques (108→124 tris). Corrigé par farthest-point sampling + raffinement glouton par échange ; sweep mesuré : cap 28 = 11,3 mm de violation (1,06 % diag), cap 64 = 2,2 mm (0,21 %) → budget fixé à 64 tris/hull, largement low-poly pour un cook physique |
| B7 | `turbo_forge --dry-run` | ✅ | plan cible/livrables/gates/cache sans exécuter |
| B8 | `turbo_forge --resume` | ✅ | re-run identique : **0,8 s** au lieu de ~19 s (hash des entrées, gates re-vérifiées) |
| B9 | `scripts/serve_preview.py` | ✅ | HTTP 0.0.0.0 pour live preview Arena |
| B10 | turntable GIF | ✅ | `renderer.make_gif` + `turbo_forge --gif` |
| C11 | CI visuelle IoU vs baseline commité | ✅ | `scripts/visual_regression.py` + `docs/visreg_baseline.json` (chair 0.607 / rocket 0.888 / vase 0.834) ; étape CI |
| C12 | triggers dans la description SKILL.md | ✅ | « Use when the user asks for a 3D model, game asset, … » |
| C13 | CI : cache pip + commentaire PR gates/evals | ✅ | workflow mis à jour (`permissions: pull-requests: write`) |
| D14 | allègement `examples/` sans stockage dupliqué | ✅ | arbre 174 Mo → **1,1 Mo** ; `scripts/fetch_examples.py` (tarball codeload = objets existants, zéro upload) ; packs complets documentés |
| D15 | split `game_ready.py` en modules | ⏸ différé | refactor à risque sans gain utilisateur ; 40 tests + 19 gates couvrent le module tel quel — à faire si le fichier doit encore grossir |

Gates totales : **19** (13 v5.2 + 6 v5.3). Vérifications : pytest **37 passed +
4 skipped** (skips explicites = packs d'exemples lourds non restaurés, message
donnant la commande `fetch_examples.py`), evals **10/10**, visual regression OK,
turbo `--dry-run`/`--resume`/`--gif` testés, plasma 18/18 et crate 19/19 gates.

Note : la gate UCX a servi immédiatement — elle a mis en évidence que la
promesse « ≤ 28 tris/hull » du code n'était pas tenue (collider à 124 tris sur
le fusil). Les tests qui lisaient des artefacts pré-générés des packs lourds
passent en `pytest.skip` documenté : un clone léger reste vert, la couverture
de ces chemins est assurée par les evals (reconstruction fraîche) et l'E2E CI.

---

## Vague v5.4 — « améliorer encore » : qualité prouvée + vitesse (2026-10-21)

| # | Amélioration | Statut | Preuve |
|---|---|---|---|
| B11 | **bug latent corrigé** : le `compress_level=1` de `meshkit` n'a jamais été appliqué (PIL fige `Image.SAVE` à l'import) | ✅ | `scripts/pngio.py` patche la vraie table de dispatch ; **encodage PNG 5,6 s → 2,7 s** |
| B12 | colliders convexes : scipy `ConvexHull` brut au lieu de la reconstruction trimesh | ✅ | **4,4 s → 70 ms** (raffinement glouton inchangé, budget 64 tris respecté) |
| B13 | run turbo complet | ✅ | crate **~16,2 s** (vs ~19 s), katana 11,8 s au bench |
| A7 | gate `texture_content` : cartes PBR plates / normal map dégénérée | ✅ | calibration mesurée (BC std 48-59, N stdRG 27-40, B≈240) |
| A8 | gate `emissive` : pièce Neon déclarée ⇒ matériau émissif dans le GLB | ✅ | 21 gates au total |
| A9 | **tests « mutants »** : on casse un package sain et on vérifie que 7 gates passent au rouge | ✅ | `tests/test_gates_mutants.py` (7 tests, 13 s) — c'est ce qui manquait pour croire aux gates |
| D16 | `fetch_examples` durci | ✅ | refus des entrées `..`/absolues/liens dans le tarball |
| — | CI/docs alignés | ✅ | bench régénéré (octets), README v5.4, SKILL 21 gates, version v5.4 |

**Bilan perf mesuré** : `sci_fi_crate` 19,0 s → **16,2 s** (−15 %), `katana` 13,8 s → **11,8 s** (−14 %).
**Bilan qualité** : 21 gates + 7 tests de mutants + 10 evals + CI visuelle.

---

## Vague v5.5 — reproductibilité + nouveau palier de vitesse (2026-10-21)

| # | Amélioration | Statut | Preuve |
|---|---|---|---|
| B14 | cache d'encodage PNG par contenu | ✅ | 46 encodages → 18 images distinctes ; 24 hits, ~1 s gagné |
| B15 | planche QA rendue en **un seul pool** (les vues face/profil étaient séquentielles) + `ssaa=1.5` + workers plafonnés aux cœurs | ✅ | 6 rendus : 8,5 s → ~4,8 s de mur ; comparaison visuelle à l'œil nu identique |
| **R1** | **bug de reproductibilité** : `trimesh.sample.sample_surface` ignore `np.random.seed()` (générateur propre) ⇒ l'AO variait à chaque run | ✅ | même maillage, deux AO différentes (Δ 0.03) ; `seed=42` explicite ⇒ **deux runs = octets identiques** |
| A10 | gate `lod1_silhouette` (LOD intermédiaire cassé) | ✅ | 23 gates |
| A11 | gate `uv_overlap` (îlots superposés = bavage de texture) | ✅ | métrique aire UV / aire couverte, insensible aux arêtes partagées (sain : 0.91-0.98) |
| T1 | tests de mutants étendus (LOD1, UV) | ✅ | 9 tests |
| T2 | **test de déterminisme** | ✅ | `tests/test_determinism.py` : mêmes entrées ⇒ mêmes tris ET mêmes octets (GLB inclus) |
| — | titre de la planche QA | ✅ | « v5.2 » → « v5.5 » |

**Bilan perf** : `sci_fi_crate` **19,0 s → 12,1 s** (−36 %), `katana` **13,8 → 10,2 s** (−26 %).
**Bilan qualité** : 23 gates, 9 mutants, 10 evals, CI visuelle, déterminisme prouvé.

---

## Vague v5.6/v5.7 — qualité de DESIGN (rendu & matière)

Objectif : la qualité *visuelle* des assets, mesurée puis corrigée là où elle péchait.

| # | Défaut constaté (mesuré) | Correction |
|---|---|---|
| D1 | rendu plat : key/fill sans séparation, coins aussi lumineux que le sujet | key/fill 1.05/0.38 → **1.35/0.26**, IBL 0.42 → 0.34 |
| D2 | objet « posé » sans ancrage au sol | ombre de contact **deux couches** (halo large + noyau serré) |
| D3 | pas de halo sur les émissions, coins plats, micro-détail écrasé | post-finition : **bloom émissif**, vignettage, unsharp mask |
| D4 | **usure d'arêtes sur 80 % des sommets** (courbure médiane 0.71 !) → « neige » blanche sur les panneaux plats | recalibrage `compute_edge_wear` (seuil 0.80 rad, gain 1.3) → médiane **0.37**, 40 % ; masque d'exposition par AO ; usure réduite de 65 % sur le jaune sécurité |
| D5 | émail uniforme = aspect « objet imprimé » | variations grande échelle : dérive de teinte par panneau (fbm 2.6/tile), poussière verticale (+Z), micro-nuance |
| D6 | crasse écrasante | plafond 0.52 → 0.34 sur les cavités |
| D7 | **néon mat** : intensité HDR perdue (glTF borne `emissiveFactor` à 1, et `hex_rgb` clipait) | `KHR_materials_emissive_strength` exportée ; chromaticité et force séparées |
| D8 | familles non-métal pouvaient finir métalliques après additifs | **contrainte dure** en sortie de patine (`metal = 0` pour soie/caoutchouc/bois) |
| D9 | galuchat blanc pur → plastique | ivoire vieilli (0.72 contre 0.86) |
| D10 | **silhouette invisible** : fond uni à 0.99 pour une lame à 0.886 de luminance — aucun détourage possible | cyclorama studio : nappe de lumière + chute radiale vers 0.57 dans les coins |
| D11 | **hamon invisible** : la trempe était à l'envers (tranchant `metal 0.95 / rough 0.10` = miroir, corps mat) ; la réflexion saturait ACES à ~0.89 partout | `ji` miroir / `ha` martensitique mat (`rough 0.40`, `metal 0.80`) + laminage ondulé ; écart-type de luminance de la lame **0.040 → 0.060** |
| G1 | aucune gate ne mesurait le **design** | gate `albedo_design` (saturation ≥ 0.12, contraste ≥ 0.08, blancs ≤ 15 %) + test mutant → **24 gates**, **10 mutants** |

**Reste connu** : la poignée du katana sort encore gris clair au rendu alors que l'ORM y
mesure `metallic 0.54` (la soie devrait être à 0). L'atlas est sain (ratio UV 0.947) et la
contrainte unitaire fonctionne : le chemin de bake de cette zone reste à élucider (piste :
la région d'atlas n'est pas classée `MAT_TSUKA_WRAP` au pixel, alors qu'elle l'est au sommet).
