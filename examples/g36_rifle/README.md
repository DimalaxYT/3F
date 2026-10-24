# G36 — Heckler & Koch G36 (5,56 × 45 mm), hard-surface

Modèle game-ready reconstruit en **hard-surface** et calé au **millimètre** sur une
vue de profil photographique. Référence : version à **rails Picatinny intégrés**,
**chargeur translucide vert**, crosse ajourée à talon galbé.

![Planche QA](qa_game_sheet.png)

![Comparaison référence / rendu](compare_reference.png)

**IoU de silhouette 0,928** · erreur de contour **1,5 mm en haut / 1,4 mm en bas**
sur une arme de 277 mm de haut — soit 0,5 % de la hauteur.

## Méthode

Chaque pièce est un prisme extrudé : **silhouette anguleuse** en (y, z) ∩
**section chanfreinée** en (x, z). Le profil n'est pas dessiné à l'œil : il est
**relevé sur le masque binaire de la photo**, colonne par colonne, puis
reconverti en millimètres.

Le contrôle de ressemblance (`refcheck.py`) compare deux silhouettes
**orthographiques** rastérisées à **1 px = 1 mm**. C'est le point qui a coûté le
plus cher : un rendu en caméra *perspective* déplace les bords de 1 à 3 mm sur
une arme de 61 mm de large vue à 1,1 m, et fait croire à des erreurs de géométrie
qui n'existent pas.

## Cotes mesurées

Masque : distance à la couleur du fond > 8, fermeture 3 × 3, composante
connexe principale. Échelle **998 mm / 1276 px**, axe du canon à 29 % de la
hauteur du cadre.

| Repère | Mesuré photo | Modèle |
|---|---|---|
| Longueur × hauteur | 998 × 278 mm (L/H **3,59**) | 996,5 × 276,6 mm (3,60) |
| Garde-main | y +336 → +115, dessus +28, rail +36,8 | idem |
| Rail haut cranté | +61,0, de y +112 à −244 | idem, 30 dents |
| Fenêtre de poignée | 205 × 27 mm (y +76 → −129, z +26 → +53) | tracée sur 8 sommets |
| Boîtier | dessus +54, dessous −30 puis **−46** (logement de détente) | idem |
| Ouïes du garde-main | 7 + 2, z +8 / −19, pas de 20 mm | poches 20 × 10 + lumière traversante |
| Chargeur | face avant raide, pointe à **−196**, talon en biais | banane 12 sommets |
| Poignée pistolet | y −182 → −273, pointe à **−151** | relevé tous les 10 mm |
| Pontet | plancher à −89, ouverture y −140 → −171, détente à −108 | idem |
| Crosse | fenêtre **142 × 28 mm**, dessous −39…−113 | idem |
| Talon | galbe : 148 mm de haut à −486, 65 mm à −498 | arc de 12 sommets |
| Frein de bouche | y +434 → +499 | idem |

## Ce qui est modélisé

| Zone | Détail |
|---|---|
| Garde-main | nez biseauté, **7 ouïes + 2 lumières** mesurées au pixel, rail 18 dents, ouïes en poches latérales |
| Poignée de transport | pilier, poutre, rampe avant **courbe** (mesurée : +36 à +105, +42 à +100, +52 à +90, +56 à +80) |
| Boîtier | fenêtre d'éjection, déflecteur, 3 goupilles, logement de détente en marche à −46 |
| Crosse | cadre ajouré, disque de charnière, plaque de couche à **échelles fines** |
| Chargeur | polymère **translucide vert pâle** (opacité 0,62, transmission 0,35), nervures |
| Canon | Ø 15 mm, frein ajouré à 6 fentes + âme débouchante |
| Mécanique | sélecteurs ambidextres, poignée d'armement, grenadière au nez |

## Contrôler la ressemblance

```bash
PYTHONPATH=scripts python3 examples/g36_rifle/build_g36.py     # 25 pièces · 3 836 tris
PYTHONPATH=scripts python3 examples/g36_rifle/refcheck.py      # IoU + écarts par colonne
PYTHONPATH=scripts python3 examples/g36_rifle/compare_reference.py
```

`refcheck.py` écrit `refcheck_overlay.png` (rouge = manquant, bleu = en trop) et
affiche l'écart haut/bas toutes les 25 mm. Seuils actuels : **toutes les colonnes
sous 6 mm, moyenne 1,5 mm**.

## Export

```bash
PYTHONPATH=scripts python3 - <<'EOF'
import importlib.util, game_ready as gr
spec = importlib.util.spec_from_file_location("g36", "examples/g36_rifle/build_g36.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
gr.export_game_package(m.build(), out_dir="exports/g36_rifle", name="g36_rifle",
                       engine="roblox_unreal", lod0_tris=9200, tex_size=2048,
                       joint_tex_size=1024, weathering=0.30)
EOF
python3 scripts/gates.py exports/g36_rifle --target hero   # 24/24
```

## Preview temps réel

```bash
python3 preview/serve_preview.py --port 8000   # -> http://localhost:8000
```

Visualiseur WebGL (three.js vendorisé, zéro CDN) : orbite, bascule LOD0/1/2,
arêtes franches, sockets, colliders UCX, mode comparaison avec la photo.

## Livrables (`exports/g36_rifle/`)

| Fichier | Contenu |
|---|---|
| `g36_rifle_game.glb` | LOD0 — **3 812 tris**, **2 draw calls** (le chargeur translucide est un matériau à part) |
| `g36_rifle_LOD1.glb` / `_LOD2.glb` | 2 592 / 1 684 tris |
| `g36_rifle_colliders.glb` | 6 hulls UCX, 218 tris |
| `roblox/` | GLB + PNG 1024², script Luau |
| `unreal/` | `SM_g36_rifle.glb` + BC / ORM / N (DirectX −Y) 2048² |
| `g36_rifle.zip` | paquet complet |

Sockets : `muzzle`, `grip`, `optic`, `eject`, `mag`, `rail_top`, `rail_bottom`,
`stock`, `origin_ground`, `top`, `interact`.

## Notes d'implémentation

- **Ne jamais mesurer la silhouette avec une caméra perspective.** À 61 mm de
  large, les bords bougent de 1 à 3 mm et l'IoU perd 6 points.
- **Le chargeur est translucide** : un seuil de luminance le troue (25 % de son
  aire), et l'on croit alors que le modèle a un excès de matière. Le masque doit
  se faire par **distance à la couleur du fond**, jamais par luminosité seule —
  mais pas trop près non plus, sinon l'ombre portée sous le canon entre dans le
  masque (+900 mm² d'aire fantôme).
- `mk.place()` ancre les boîtes **par la base en Z** mais centre en X/Y ; un oubli
  fait dépasser une pièce de 20 mm.
- `mk.extrude()` base à z = 0, extrusion vers +Z : `_M_X` / `_M_Y` compensent.
- `gr.picatinny_rail()` : axe long en Y, base à z = 0. Ses dents descendent sous
  la base — au-dessus d'une fenêtre il faut **rogner les dents**, pas décaler le
  rail.
- Le renderer cadre sur la sphère englobante : à fov 32° une arme de 1 m remplit
  le cadre ; à fov 14° on ne voit qu'une moitié.
- Les « facettes diagonales » vues en 3/4 sur le garde-main ne sont **pas** de la
  géométrie : c'est l'ombre du rail projetée sur le flanc.
