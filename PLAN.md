# PLAN.md — Architecture & feuille de route de 3d-forge

> Document de conception. Décrit *pourquoi* le skill est construit ainsi,
> puis *où il va*. À mettre à jour à chaque évolution majeure.

## 1. Problème et pari fondateur (`v1` -> `v4`)

`3d-forge v4` réunit **en une seule chaîne 100 % autonome** :
1. **La CAO paramétrique exacte (`meshkit.py` + `manifold3d`)** pour les objets mécaniques, architecturaux, mobiliers et verreries (19/19 recettes étanches, pivots articulés `def_joint`, extensions glTF 2.0 `KHR_materials_transmission` / `ior` / `clearcoat`),
2. **La Sculpture Organique 3D par GPU Datacenter (`gpu_sculpt.py`)** pour les bustes, créatures et statues organiques (reconstruction SDF elliptique multi-branches sans boîtes ni escaliers + socle de musée soudé `manifold3d` + bake UV `1024²`),
3. **L'Ingénierie d'Impression 3D Réelle (`split_stl.py` & `validate.py`)** : découpe automatique au volume du plateau (`256 × 256 × 256 mm`) avec clés d'assemblage mâle/femelle chanfreinées (`0,20 mm` de jeu).

La génération 3D par IA (Meshy, Tripo, Luma) impose trois dépendances : une API
payante, un réseau, et une perte de contrôle (mesh opaque, non déterministe,
souvent non étanche). À l'inverse, un LLM agent possède une compétence que ces
services n'exploitent pas : **le raisonnement géométrique**. Un vase amphore,
ce n'est pas un nuage de points statistiquement plausible — c'est un profil de
révolution (pied étroit, panse à 40 %, épaule, col, lèvres évasées) tourné
autour d'un axe, avec une paroi de 5 mm.

**Le pari** : si on donne à l'agent une usine géométrique déterministe et un
retour visuel rapide, il devient lui-même le générateur text-to-3D. Le skill
n'est donc pas un « outil de plus » : c'est le procédé qui convertit la
capacité de raisonnement du modèle en fichiers 3D industriels.

## 2. Architecture — les trois étages

### Étage 1 — meshkit + pbr (la main & l'atelier de surface)
`scripts/meshkit.py` + `scripts/pbr.py` : CAO paramétrique étanche + texturage PBR procédural unifié.

- **Primitives posées au sol** (base z=0, centrées XY) : `box`, `rounded_box` (chanfreins/congés réalistes), `cylinder`, `frustum`, `cone` (anneau + apex, sans faces dégénérées), `sphere`, `torus`, `tube` (fermé, étanche), `capsule`, `lathe`, `extrude`, `loft` (sections 2D/3D ré-échantillonnées par abscisse curviligne), `sweep` (balayage le long d'une courbe 3D à repère de Bishop sans torsion).
- **Pont hybride CAO → PBR (`Builder.bake_pbr`)** : déplie la géométrie exacte avec `xatlas` et cuit 3 cartes glTF 2.0 (`albedo`, `metallicRoughness`, `normal` en espace tangent) avec usure d'arêtes dièdres et 8 overlays 3D sans couture (`rust`, `wrap` / `diamond` *tsuka-maki*, `edge_wear`, `wood_grain`, `brushed_metal`, `hamon`, `patina`, `speckle`), alignés sur la convention UV `1 - v` de `trimesh`/glTF/OBJ/USDZ/WebGL.
- **CSG manifold** : `union`, `difference`, `intersection` — le backend
  manifold3d produit des résultats étanches par construction, ce qui rend le
  fil « impression 3D » trivial : `Builder.union_solid()` fusionne toutes les
  pièces en un solide unique.
- **Matériaux PBR** : classe `Material` (baseColor, metallic, roughness,
  opacity, emissive) + préréglages `mat.*` dont les RGB de métaux sont des
  valeurs de référence physique (or 1.0/0.766/0.336, etc.).
- **Builder** : assemble pièces + matériaux + transforms, produit une
  `trimesh.Scene` (GLB), un solide fusionné (STL), et alimente le renderer.

**Décisions de conception clé** :
- *Tout est posé à z=0, face avant vers -Y* → compositions prévisibles,
  caméra par défaut correcte sans réglage.
- *`lathe` referme automatiquement les profils sur l'axe* → impossible de
  générer un solide de révolution non étanche par accident (le cas d'école
  du STL imprimerie ratée).
- *Paramètres en mètres, échelle réelle* → un mug fait 9,5 cm, pas 9,5 unités
  mystères ; les exports sont à l'échelle pour l'AR comme pour l'impression.

### Étage 2 — renderer + cycles_render + gpu_bridge (les yeux & le GPU datacenter)
`scripts/renderer.py`, `scripts/cycles_render.py`, `scripts/gpu_bridge.py`, `scripts/photo_pass.py` :

- **Pipeline linéaire physique** : décodage sRGB -> lumière linéaire -> tone mapping filmique ACES -> ré-encodage sRGB (élimine tout aspect délavé pastel),
- **BRDF microfacettes Cook-Torrance GGX** ($D_{\text{GGX}}, G_{\text{Smith}}, F_{\text{Schlick}}$) avec vrai vecteur vue perspectif par pixel,
- **Dôme HDRI Studio Softbox** filtré par la rugosité + ligne d'horizon studio pour le chrome et les peintures vernies,
- **Shadow-Map directionnelle 3D PCF** + **SSAO multi-échelles** + **AO géométrique cuite dans `mr.r` (`occlusionTexture` glTF 2.0)**,
- **Pont GPU Datacenter (`gpu_bridge.py` / `photo_pass.py`)** : cuisson directe de textures générées sur le GPU datacenter du modèle hôte dans l'atlas UV `.glb` (`bake-tiles` et `bake-views`) + passe photographique verrouillée 1:1 sur la silhouette et les normales du maillage (`photo_pass.py`).
  spéculaire piloté par `roughness`, terme d'environnement hémisphérique
  ciel/sol pour les métaux (sinon lame d'épée = trou noir), tone mapping ACES,
- ombre de contact : silhouette projetée sur le sol **par la même caméra**
  puis floutée,
- verre : passe après les opaques, blend alpha,
- SSAA ×2 + Lanczos → PNG propre.

Ce renderer existe parce que le retour visuel est la boucle de contrôle de
l'agent : sans lui, l'agent livre à l'aveugle. Il tourne partout (pas d'OpenGL,
pas de GPU), en 1 à 5 s par vue.

### Étage 3 — les recettes (le savoir-faire)
`scripts/recipes/` : 17 builders enregistrés via `@register` (registry avec
défauts + doc de paramètres typée). Les recettes encodent des proportions
réelles (une assise à 44 cm, un col de bouteille à 35 % du rayon) et des
techniques réutilisables : profils PCHIP anti-overshoot, CSG pour les passages
de roues, émissif pour les abat-jour.

**Interface « prompt → 3D »** : elle est délibérément *dans l'agent*, pas dans
le code. `generate.py` ne parse pas le langage naturel ; il reçoit une recette
+ des paramètres coercés (float/int/bool/choice/color, rejet explicite des
clés inconnues). C'est l'agent qui traduit « un grand vase terracotta » en
`vase --set shape=amphora height=0.4 color="#8b3a2a"`. Résultat : zéro
silence sémantique, tout le raisonnement reste auditable.

### Exports — les quatre formats
| Format | Chemin | Particularité |
|---|---|---|
| GLB | `trimesh.Scene.export` | PBR embarqué, Z-up mètres |
| STL | `Builder.union_solid()` | fusion booléenne → solide unique étanche |
| OBJ+MTL | exporteur maison (~60 lignes) | Kd/Ks/Ns/d dérivés du PBR, contrôle total |
| USDZ | `usdz_export.py` via `usd-core` | vrai crate Pixar + UsdPreviewSurface, AR Quick Look |

## 3. Ce que la V1 sait faire (état testé)

- 17/17 recettes : construction OK, solide fusionné étanche, volume positif
  (`tests/test_smoke.py`).
- Exports GLB/OBJ+MTL/STL/USDZ vérifiés (roundtrip GLB relu, USDZ généré par
  usd-core 26.8).
- Rendus multi-angles propres : matériaux distinguishables (céramique crème,
  acier argenté, verre teinté, émissif), ombres de contact, fond studio.
- Pipeline CLI complet < 5 s par objet en qualité standard.

## 4. Feuille de route

### Phase 1.1 — qualité visuelle (prochaines itérations)
- [ ] **Arrondis** : `rounded_box(w,d,h,r)` par union pavé+cylindres+sphères
      (manifold absorbe le coût) — le gain « réalisme » n°1 pour le mobilier.
- [ ] **Textures procédurales** (GLB embarqué) : bois (rayures + bruit),
      céramique (speckle), métal brossé (anisotropie simulée) — bruit value
      numpy → texture 512², aucune dépendance.
- [ ] Corriger les normales du verre à pied (stries intérieures) :
      recalculer les normales après `filter_taubin` ou désactiver le lissage
      sur les profils à paroi mince.
- [ ] Profils amphore plus fidèles (pied + anses optionnelles).

### Phase 1.2 — élargissement catalogue (objectif : 40 recettes)
- [ ] Mobilier : canapé, lit, étagère murale, bureau, lampe de bureau articulée.
- [ ] Cuisine : tasse à espresso, carafe, couteau, planche, casserole.
- [ ] Personnages low-poly (humanoïde paramétrique articulé en 12 pièces).
- [ ] Véhicules : camion, vélo, bateau, fusée V2 ( étages ).
- [ ] Nature : rocher (bruit + déformation sphère), buisson, fleur, nuage.
- [ ] Bâtiments : tour de château, cabane, pont, éolienne.

### Phase 1.3 — scènes multi-objets
- [ ] `Builder.compose(other_builder, at=, rot=)` + collision bbox simple.
- [ ] Recettes de scènes : salle (sol+murs+meubles), diorama, ville low-poly.
- [ ] Export glTF avec hiérarchie de nœuds (groupes nommés).

### Phase 2 — fallback neuronal (optionnel, GPU)
- [ ] `neural/` : installation documentée de TripoSR (image→3D, ~6 Go VRAM)
      et Hunyuan3D-2 (texte/image→3D, 12–16 Go).
- [ ] Bridge : `generate.py --neural "prompt"` → détecte GPU → rend mesh →
      **re-travaille** avec meshkit (réparation étanchéité, mise à l'échelle,
      matériaux) avant export. Le neuronal produit la forme, meshkit la
      fiabilise — jamais l'inverse.
- [ ] Flag qualité : le rapport JSON marque `source: neural` et les contrôles
      d'étanchéité deviennent bloquants.

### Phase 3 — industrialisation
- [ ] Suite pytest complète (recettes × exports × validations) + CI GitHub
      Actions qui **rend** un objet et compare (SSIM léger) à une image de
      référence — détecte les régressions visuelles.
- [ ] Bench rendu : objectif < 1 s/vue à 1024 px (vectorisation des boucles
      triangles, ou tiled rendering).
- [ ] Documentation interactive : `--list --verbose` avec mini-rendus ASCII
      ou QR vers la galerie.
- [ ] Publication : GitHub + README bilingue + vidéo démo turntable (GIF).

## 5. Modèle de contribution (ajouter une recette)

1. Créer `build_xxx(**params) -> Builder` dans le module thématique
   (`furniture.py`, `containers.py`, `props.py`).
2. Décorer avec `@register("xxx", defaults={...}, info=[...])` — chaque
   paramètre documenté (`type`, `help`, `choices`).
3. Règles d'or : base à z=0, face avant -Y, mètres, géométrie étanche
   (primitives/CSG uniquement), matériaux via `mk.mat.*`.
4. Ajouter un cas dans `tests/test_smoke.py` (automatique : il itère sur le
   registre) et une image dans `docs/img/`.

Le test de fumée construit *toutes* les recettes enregistrées : une recette
cassée casse la CI, pas la production.

## 6. Limites connues (honnêteté contractuelle)

- Organique complexe (visages, créatures, sculptures) : hors de portée du
  procédural pur → voir Phase 2.
- Rendu : approximation Blinn-Phong + env hémisphérique, pas de GI ni
  réfraction — suffisant pour valider, pas pour du marketing.
- USDZ : généré par usd-core (correct), non testé sur device Apple réel.
- Performance rendu : ~1–5 s/vue selon densité ; acceptable pour l'agent,
  insuffisant pour la production vidéo (→ Phase 3).
