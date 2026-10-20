# Matériaux PBR — préréglages et guide

Chaque matériau = `baseColor` (RGB) + `metallic` (0–1) + `roughness` (0–1)
+ `opacity` (1 = opaque) + `emissive` (optionnel). Ces propriétés voyagent
telles quelles dans le GLB et l'USDZ ; le renderer les approxime en
Blinn-Phong, Blender/Cycle les utilisent nativement.

## Préréglages non métalliques (metallic = 0)

| Préréglage | Défaut | Rugosité | Usage |
|---|---|---|---|
| `mat.wood(c, r=0.55)` | `#8a5a2b` | 0.55 | meubles, sols, manches |
| `mat.plastic(c, r=0.35)` | `#c8c8c8` | 0.35 | coques, jouets, props |
| `mat.ceramic(c, r=0.15)` | `#e8e4dc` | 0.15 | vaisselle, vases (brillant) |
| `mat.glass(c, o=0.35, r=0.05)` | `#cfe8ef` | 0.05 | vitres, bouteilles |
| `mat.fabric(c, r=0.85)` | `#4a6fa5` | 0.85 | assises, rideaux, tapis |
| `mat.rubber(c, r=0.9)` | `#222222` | 0.9 | pneus, poignées, joints |
| `mat.paint(c, r=0.45)` | — | 0.45 | carrosserie, murs, éléments colorés |
| `mat.emissive(c, s=1.2)` | `#fff2cc` | 0.6 | ampoules, écrans, phares |

## Métaux (metallic = 1, RGB physiquement fondés)

| Métal | RGB linéaire | Rugosité par défaut |
|---|---|---|
| `gold` | 1.000, 0.766, 0.336 | 0.20 |
| `brass` | 0.715, 0.470, 0.210 | 0.30 |
| `copper` | 0.955, 0.637, 0.538 | 0.30 |
| `bronze` | 0.780, 0.500, 0.320 | 0.40 |
| `steel` | 0.560, 0.570, 0.580 | 0.35 |
| `silver` | 0.972, 0.960, 0.915 | 0.15 |
| `aluminum` | 0.913, 0.921, 0.925 | 0.40 |
| `chrome` | 0.940, 0.940, 0.940 | 0.06 |

## Guide d'usage

- **2 à 4 matériaux par objet** : au-delà, l'objet paraît bricolé. Un accent
  métallique (laiton, acier) sur un corps mat (bois, céramique) marche presque
  toujours.
- **Rugosité** : c'est le levier n°1 du réalisme. 0.05–0.15 = poli/verre,
  0.3–0.5 = plastique/peinture, 0.6–0.9 = mat/tissu/bois brut.
- **Verre** : opacity 0.3–0.45 et roughness ≤ 0.08. Toujours une teinte
  légère (`#cfe8ef`) — le verre « sans couleur » disparaît sur fond clair.
- **Émissif** : strength ≤ 2.0, réservé aux petites surfaces (ampoule, phare).
  Un grand abat-jour émissif léger (0.25–0.35) simule la lumière diffuse.
- **Couleurs** : hex `#rrggbb` ou `#rgb` partout (params CLI comme API).
  Palette réaliste : éviter le saturé pur ; `#c0392b` > `#ff0000`.

## Ajouter un préréglage

Dans `meshkit.py`, classe `mat` :

```python
@staticmethod
def leather(color="#5b3a1e", roughness=0.65):
    return Material("leather", color, roughness=roughness)
```

Puis le documenter ici. Les métaux se ajoutent au dict `mat.METALS`
(RGB de référence, pas au feeling — chercher « metallic RGB values »).
