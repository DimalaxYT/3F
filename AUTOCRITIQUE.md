# AUTOCRITIQUE NOTÉE — Protocole Turbo Express (`< 60–90 s` bout en bout, `3d-forge v5.9`)

Ce fichier définit le protocole de contrôle qualité obligatoire de `3d-forge`.
Le moteur déterministe qui structure le contrôle est `scripts/critique.py`
(seuil & budget d'itérations : source de vérité = **`python3 scripts/critique.py policy`**, soit `THRESHOLD = 8.8`, **`MAX_ITERS = 1`**).

> ## ⛔ GARDE-FOU ANTI-BOUCLE D'UNE HEURE (OBLIGATOIRE SUR ARENA, Z.AI, CLAUDE, CURSOR)
> - **INTERDICTION ABSOLUE** de lancer 5, 8 ou 12 reconstructions successives ou de rendre `render_all_faces` / `render_turntable` à chaque essai !
> - **Temps cible total = `20 à 90 secondes` maximum** : **1 run initial `turbo_forge.py` (`~15 s`) + lecture de `qa_game_sheet.png` + AU MAXIMUM 1 SEULE passe de correction (`iter_1`)**, puis **LIVRAISON IMMÉDIATE**.
> - Si ton modèle ressemble à des primitives empilées (`sphere` + cylindre mou), **ne décale pas des coordonnées pendant 1 heure** : utilise **`org.Sculpt` (`s.ellipsoid` + `s.sweep` + `mode="sub"`)** + **`b.trim_inside(cutter)`** (voir `scripts/recipes/characters.py` : `tengu_mask`, `hero_bust`, `stylized_character`, `dragon_creature`).

---

## LE PROTOCOLE EN 4 ÉTAPES (`< 90 s` TOTAL)

1. **GÉNÈRE EN UNE SEULE COMMANDE** via `scripts/turbo_forge.py` (`12 à 20 s` CPU tout compris :
   géométrie + `LOD0/1/2` + pack `roblox/` PNG Studs + pack `unreal/` ORM DirectX `-Y` + `.stl` étanche + `preview.html` + `qa_game_sheet.png` + `gates.json`).
   - Ne lance **PAS** `research.py fetch` ni `--faces all` en mode standard (`turbo`).
2. **INSPECTE `qa_game_sheet.png` AVEC `read_file`** (planche 10 panneaux : High-Poly, LOD0, LOD2, Colliders UCX, Face, Profil, ColorMap AO, Normal Mikk, ORM et carte QA).
3. **CONTRÔLE LES 6 AXES QUALITÉ** :
   - **S — Silhouette & proportions (`/2.5`)** : volumes anatomiques sculptés (`org.Sculpt` + `s.sweep`), zéro forme molle ou primitive brute reconnaissable.
   - **V — Volume & envers propre (`/1.5`)** : sur tout masque, casque ou coque creuse, **aucune pièce interne ne dépasse à l'arrière** (`b.trim_inside(cutter)` obligatoire !).
   - **M — Matériaux & palette PBR (`/1.5`)** : laque *urushi* profonde (`mk.mat.lacquer`), peau vivante (`mk.mat.skin`), émail franc (`mk.mat.enamel`), `metallic = 0` strict hors vrais métaux (`pbr_coherence`).
   - **R — Relief & lumière (`/1.5`)** : arcades, plis, yeux, crocs et bandeaux francs (`>= 3 mm` de relief pour ne jamais être mangés par le `LOD0`).
   - **D — Détails distinctifs (`/2.0`)** : yeux multi-couches, emblèmes/bandeaux continus, cordons/poignées/sockets bien attachés sans traverser les parois.
   - **T — Intégrité technique (`/1.0`)** : **`25/25 gates OK`** dans `gates.json` (`stl_watertight == True`, `< 9 800 tris/part`, PNG pur Roblox, WebP léger `preview.html`).
4. **DÉCISION IMMÉDIATE (`MAX_ITERS = 1`, ZÉRO BOUCLE INFINIE)** :
   - **Tout est propre sur `qa_game_sheet.png` et `gates.json` = `all_pass: true`** -> **LIVRE IMMÉDIATEMENT DÈS LA PASSE 0** (`preview.html` + `qa_game_sheet.png`).
   - **Un défaut visuel précis est visible** (ex: bandeau enterré de 3 mm, détail trop fin, gate rouge) -> **corrige tous les points en UNE SEULE passe groupée (`iter_1`)**, relance `turbo_forge.py` une fois (`~15 s`), vérifie `qa_game_sheet.png`, et **LIVRE IMMÉDIATEMENT**.
