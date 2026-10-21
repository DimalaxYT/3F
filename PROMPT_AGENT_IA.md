# 🤖 Prompts Prêts à Copier pour Agents IA — `3d-forge v5.1 Turbo`

Clique simplement sur l'icône **📋 Copier** en haut à droite du bloc ci-dessous dans GitHub, colle-le dans ton agent IA (**Arena, Claude Code, Cursor, Codex, Windsurf, GitHub Copilot, OpenCode, Cline…**), et remplace uniquement la dernière ligne **`DEMANDE : ...`** par l'objet 3D que tu veux créer !

---

## ⚡ 1. Prompt Universel Tout-en-Un (Recommandé — fonctionne partout, même dans un projet vide !)

```markdown
Tu dois générer un asset 3D réaliste AAA prêt à l'emploi pour **Roblox Studio (Priorité n°1)** et **Unreal Engine 5 (Priorité n°2)** en utilisant le skill **`3d-forge v5.1 Turbo`** depuis `https://github.com/DimalaxYT/3F`.

### Protocole d'exécution obligatoire (`OBJECTIF : < 90 SECONDES`, ZÉRO BOUCLE DE 30 MIN) :
1. **Préparation rapide (si `scripts/turbo_forge.py` n'est pas déjà dans le dossier courant)** :
   - Clone le dépôt : `git clone --depth 1 https://github.com/DimalaxYT/3F.git` et place-toi dedans.
   - Installe les dépendances si nécessaire : `pip install -q -r requirements.txt` (ajoute `--break-system-packages` sous Linux conteneurisé si besoin).
   - Lis `SKILL.md` (en particulier la section `CRITICAL SPEED RULE`) pour suivre toutes les conventions `meshkit.py`, `greebles.py`, `gpu_sculpt.py` et `gpu_bridge.py`.

2. **Choisis la bonne méthode et lance UNE SEULE COMMANDE `scripts/turbo_forge.py` (`12 à 20 s` CPU)** :
   - **Objet mécanique / arme / coffre / véhicule / architecture (Hard-Surface)** :
     Écris un module Python propre `custom_<nom>.py` exposant `def build() -> mk.Builder:` qui assemble de vraies pièces 3D profilées (`mk.loft`, `mk.revolve`, `mk.tube_sweep`, chanfreins) + les pièces détaillées étanches de `scripts/greebles.py` (`hex_bolt`, `bolt_array`, `toggle_latch`, `louver_vent`, `picatinny_rail`, `ribbed_conduit`, `ergonomic_handle`, `corner_armor_cap`) + parties lumineuses séparées (`emissive`) + articulations (`b.def_joint(...)` si ouvrant/mobile).
     *(Optionnel si tu as un outil `generate_image` GPU : sors d'abord les guides orthographiques avec `--emit-guides`, génère `front`/`side`/`top` en parallèle dans UN SEUL tour avec `offer_options=False`, puis passe `--ai-front`, `--ai-side`, `--ai-top`.)*
     Lance ensuite :
     `python3 scripts/turbo_forge.py custom_<nom>.py --name <nom> --lod0-tris 4800 --stl -o out/<nom>`
   - **Créature / personnage / monstre / buste / organique** :
     Si tu disposes de `generate_image`, génère **`front.png` + `side.png` (+ `back.png`) EN PARALLÈLE DANS LE MÊME TOUR** (`offer_options=False`, fond neutre uni, éclairage diffus sans ombre portée, proportions alignées), puis lance en 1 commande :
     `python3 scripts/turbo_forge.py --front front.png --side side.png --back back.png --name <nom> --lod0-tris 4800 -o out/<nom>`

3. **Contrôle Qualité Express (PAS DE BOUCLE INFINIE !)** :
   - ❌ **INTERDIT** de lancer `research.py fetch` (scraping web lent) ou `render_views --faces all` (14 images inutiles).
   - ✅ Ouvre **uniquement `out/<nom>/qa_game_sheet.png`** pour vérifier visuellement les 4 angles, les matériaux PBR (`metallic == 0` sur caoutchouc/tissu, AO net dans `ColorMap`, pas de bavure) et vérifie dans `out/<nom>/game_manifest.json` que `under_10k_tris_limit == true` et que `out/<nom>/roblox/<nom>_roblox.glb` est bien en PNG pur (`webp=False`).
   - Si le rendu est propre (`>= 8.8/10`), **livre immédiatement dès la passe 0 (0 reconstruction inutile !)**. Sinon, fais **au maximum 1 seule retouche ciblée** puis livre.

4. **Livraison claire** :
   Présente l'aperçu `out/<nom>/qa_game_sheet.png` et indique les chemins exacts de :
   - `out/<nom>/roblox/<nom>_roblox.glb` + `out/<nom>/roblox/setup_<nom>.lua` (prêts pour Roblox Studio -> `Import 3D`),
   - `out/<nom>/unreal/SM_<nom>.glb` (prêt pour Unreal Engine 5).

---
DEMANDE : [DÉCRIS ICI TON MODÈLE 3D — ex: "Un fusil plasma cybernétique noir et orange avec rail Picatinny, bobines néon bleues et crosse tactique en polymère mat"]
```

---

## 🚀 2. Prompt Court (Si ton Agent IA est DÉJÀ ouvert dans le dépôt `DimalaxYT/3F`)

> Comme ce dépôt contient déjà **`AGENTS.md`**, **`CLAUDE.md`**, **`.github/copilot-instructions.md`** et **`SKILL.md`**, Claude Code, Cursor, Codex, Arena et GitHub Copilot connaissent déjà automatiquement les règles ! Tu peux juste coller ces 4 lignes :

```markdown
Utilise le skill local `SKILL.md` en mode Turbo (`scripts/turbo_forge.py` + `scripts/greebles.py`, < 90 s, zéro boucle longue) pour créer cet asset 3D réaliste prêt pour Roblox Studio (`roblox/<nom>_roblox.glb` + `setup_<nom>.lua`) et Unreal Engine 5 (`unreal/SM_<nom>.glb`), vérifie `qa_game_sheet.png` et présente-moi le rendu :

DEMANDE : [DÉCRIS ICI TON MODÈLE 3D]
```

---

## 🎨 3. Prompt Spécial « Ultra-Texture Peinte par GPU » (Marquages, Pochoirs, Camouflages Sci-Fi)

```markdown
Utilise `SKILL.md` (`https://github.com/DimalaxYT/3F`) en 2 étapes rapides (< 2 min) pour créer cet asset avec **géométrie mécanique `greebles.py` + peinture multi-vues GPU Z-Buffer** :
1. Construis `custom_<nom>.py` (`meshkit.py` + `greebles.py`) et génère les guides orthographiques exacts :
   `python3 -c "import sys; sys.path.insert(0,'scripts'); import custom_<nom> as m, gpu_bridge as gb; gb.render_orthographic_paint_guides(m.build(), 'out/<nom>/guides', size=768)"`
2. Appelle `generate_image(..., images=[guide], offer_options=False)` **EN PARALLÈLE dans un seul tour** sur `guide_front.png`, `guide_side.png` et `guide_top.png` pour peindre des textures studio PBR ultra-nettes (marquages, panneaux, micro-usure, éclairage neutre plat) alignées au pixel près sur les silhouettes des guides.
3. Lance **une seule commande finale** :
   `python3 scripts/turbo_forge.py custom_<nom>.py --name <nom> --ai-front ... --ai-side ... --ai-top ... --lod0-tris 4800 -o out/<nom>`
4. Vérifie `out/<nom>/qa_game_sheet.png` et livre le pack `roblox/` + `unreal/`.

DEMANDE : [DÉCRIS ICI TON MODÈLE 3D AVEC MARQUAGES / CAMOUFLAGE]
```
