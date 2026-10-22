# AGENTS.md — Protocole Agent IA Universel (`3d-forge v5.8`)

Ce dépôt fournit le moteur de génération 3D CAO + Sculpture SDF Organique & Hybride **`3d-forge`** dédié en priorité à **Roblox Studio**, **Unreal Engine 5**, l'**impression 3D étanche** et le **WebGL2 hors-ligne (`preview.html`)**.

## Règle 0 — Zéro Dessin 2D Synthétique (`PIL` / `matplotlib`)

- **N'invente JAMAIS** de fausses images `front.png` / `side.png` dessinées au code Python (`PIL`, `matplotlib`, formes 2D plates) pour alimenter `gpu_sculpt.py` ou `turbo_forge.py --front` !
- **Sans `generate_image` (ex: Claude.ai, CLI local) OU dès qu'un design net et proportionné est attendu** :
  - **Hard-surface (arme, véhicule, meuble, coffre, outil)** -> `custom_<nom>.py` avec **`scripts/meshkit.py` + `scripts/greebles.py`**.
  - **Organique / Personnage / Buste / Créature / Mascotte** -> recette `hero_bust` / `stylized_character` / `dragon_creature` (**`scripts/recipes/characters.py`**) **OU** `custom_<nom>.py` avec **`scripts/meshkit.py` + `scripts/organic.py`** (`org.Sculpt` SDF `C¹` continu + `org.add_stylized_eyes` + `org.tapered_curve` + `org.curved_visor` + matériaux `mk.mat.skin` / `enamel` / `denim` / `clay`).
- **Avec `generate_image` photoréaliste disponible** et uniquement pour une créature ultra-organique complexe : génère `front.png` + `side.png` (+ `back.png`) orthographiques **en parallèle** (`offer_options=False`, fond neutre uni `#e6e6e6`, zéro ombre au sol), puis lance `turbo_forge.py --front ... --side ...`.

## Séquence d'exécution standard (profil `turbo` par défaut)

1. Lire **`SKILL.md`** (source de vérité unique).
2. Exécuter **un seul appel `bash`** :
   ```bash
   python3 scripts/turbo_forge.py <recette | custom.py | --front f.png --side s.png> -o out/<nom>
   ```
3. Lire **`out/<nom>/qa_game_sheet.png`** (`read_file`) et contrôler :
   - **25+ gates 100 % vertes** (`gates.json`),
   - **Face (panneau 5) & Profil (panneau 6)** : proportions harmonieuses, yeux/badges/boutons nets et non enterrés, couleurs franches sans métal parasite (`pbr_coherence`).
4. Maximum **1 passe de correction** si un détail visuel ou une gate échoue.
5. Présenter **`out/<nom>/preview.html`** (`present_file`) + lancer `serve_preview.py` si un live preview navigateur est utile.
