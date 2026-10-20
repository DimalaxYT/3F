# Fallback neuronal (optionnel — nécessite un GPU NVIDIA)

3d-forge fonctionne **entièrement sans cette section**. Elle documente comment
ajouter un vrai text-to-3D / image-to-3D neuronal *local* (open-source, sans
API) quand une carte NVIDIA ≥ 6 Go est disponible — typiquement pour sculpter
de l'organique (créatures, personnages, objets irréguliers) que le procédural
ne couvre pas honnêtement.

Vérifier d'abord : `python3 scripts/detect_env.py` → champ `gpu`.

## Modèles recommandés (état 2025–2026)

| Modèle | Entrée | VRAM | Poids | Qualité | Remarques |
|---|---|---|---|---|---|
| **TripoSR** (Stability × Tripo) | 1 image | ~6 Go | ~0,5 Go | ★★★ | rapide (< 5 s GPU), idéal en image→3D |
| **Stable Fast 3D (SF3D)** | 1 image | ~7 Go | ~1 Go | ★★★ | + UV/matériaux |
| **Hunyuan3D-2.x** (Tencent) | image ou texte | 12–16 Go | ~5 Go | ★★★★ | le meilleur rapport qualité/complexité local |
| **TRELLIS** (Microsoft) | image ou texte | 16–24 Go | ~8 Go | ★★★★ | sorties propres, SLAT |
| **Shap-E** (OpenAI) | texte | CPU possible (lent) | ~2 Go | ★★ | le seul utilisable sans GPU, quelques minutes/objet |

## Installation type (TripoSR, exemple)

```bash
# dans un venv dédié (torch + cu121 selon votre install CUDA)
git clone https://github.com/VAST-AI-Research/TripoSR.git
cd TripoSR && pip install -r requirements.txt
# générer : input.png (photo/rendu de l'objet) → mesh
python run.py input.png out.obj --device cuda
```

Puis **re-travailler la sortie avec meshkit** (règle du skill : le neuronal
produit la forme, meshkit la fiabilise) :

```python
import trimesh, meshkit as mk
mesh = trimesh.load("out.obj")
mk.ground(mesh); mk.scale(mesh, échelle_cible)          # mètres, base z=0
if not mesh.is_watertight:                              # réparation
    trimesh.repair.fill_holes(mesh); trimesh.repair.fix_normals(mesh)
```

## Intégration dans le pipeline

`scripts/detect_env.py` expose déjà la détection (`gpu.cuda_available`,
`vram_gb`). Pour brancher un pipeline neuronal :

1. Créer `neural/run_<model>.py` qui encapsule l'inférence et sort un GLB/OBJ.
2. `generate.py` reste la porte d'entrée unique : ajouter un argument
   `--neural` qui, si `detect_env` est favorable et le modèle installé,
   délègue la forme puis reprend le chemin standard (validation, matériaux,
   exports, rendus, rapport avec `"source": "neural"`).
3. Les contrôles qualité (`validate.py`) deviennent **bloquants** pour un
   mesh neuronal : étanchéité, orientation, échelle réelle.

## Pourquoi pas par défaut ?

- Poids à télécharger (0,5–8 Go), environnement torch lourd, latence GPU.
- Qualité non déterministe (graine aléatoire) : contraire à la philosophie
  reproductible du skill.
- Le procédural couvre 90 % des besoins pratiques (props, mobilier, contenants)
  avec une qualité contrôlée et éditable.

La règle : **procédural d'abord, neuronal en renfort, jamais l'inverse.**
