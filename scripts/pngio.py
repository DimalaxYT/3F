#!/usr/bin/env python3
"""
pngio.py — encodage PNG adapté à l'usage (vitesse d'itération vs poids livré).

⚠️ PIL capture le handler PNG dans `Image.SAVE["PNG"]` **à l'import** : patcher
`PngImagePlugin._save` n'a aucun effet (piège rencontré dans ce dépôt, le
« compress_level=1 » de `meshkit` n'avait jamais été appliqué). On patche donc la
table de dispatch réelle.

Mesures (1024² ColorMap, ce dépôt) : niveau 6 = 217 ms / 806 Ko,
niveau 4 ≈ 120 ms / ~830 Ko, niveau 3 = 87 ms / 870 Ko.

Règle : cartes livrées niveau 4 (1,8× plus vite, +3 % de poids), planches QA
niveau 1 (jamais chargées par un moteur).
"""
from __future__ import annotations

import contextlib

import PIL.PngImagePlugin  # noqa: F401  (enregistre le handler PNG)
from PIL import Image

GAME_LEVEL = 4
QA_LEVEL = 1

# `Image.SAVE` n'est peuplé qu'après `Image.init()` : sans cet appel, un import
# « à froid » de ce module (premier import PIL du process) lève KeyError("PNG").
Image.init()
_ORIG_PNG_SAVE = Image.SAVE.get("PNG", PIL.PngImagePlugin._save)


@contextlib.contextmanager
def fast_png(level: int = GAME_LEVEL):
    """Force le niveau de compression PNG par défaut dans le bloc `with`."""
    def _patched(im, fp, filename, *a, **kw):
        im.encoderinfo.setdefault("compress_level", level)
        return _ORIG_PNG_SAVE(im, fp, filename, *a, **kw)

    Image.SAVE["PNG"] = _patched
    try:
        yield
    finally:
        Image.SAVE["PNG"] = _ORIG_PNG_SAVE
