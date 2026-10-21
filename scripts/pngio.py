#!/usr/bin/env python3
"""
pngio.py — encodage PNG adapté à l'usage (vitesse d'itération vs poids livré)
et cache des encodages déjà effectués.

⚠️ PIL capture le handler PNG dans `Image.SAVE["PNG"]` **à l'import** : patcher
`PngImagePlugin._save` n'a aucun effet (piège rencontré dans ce dépôt, le
« compress_level=1 » de `meshkit` n'avait jamais été appliqué). On patche donc la
table de dispatch réelle.

Deuxième levier mesuré : un run turbo encode 46 PNG pour seulement 18 images
distinctes (les mêmes cartes sont ré-encodées pour chaque GLB exporté) — le cache
par contenu ci-dessous supprime ce travail redondant (~1,9 s/run).

Niveaux : cartes livrées niveau 4 (1,8× plus vite que 6, +3 % de poids),
planches QA niveau 1.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os

import PIL.PngImagePlugin  # noqa: F401  (enregistre le handler PNG)
from PIL import Image

GAME_LEVEL = 4
QA_LEVEL = 1

# `Image.SAVE` n'est peuplé qu'après `Image.init()` : sans cet appel, un import
# « à froid » de ce module (premier import PIL du process) lève KeyError("PNG").
Image.init()
_ORIG_PNG_SAVE = Image.SAVE.get("PNG", PIL.PngImagePlugin._save)

_CACHE: dict[tuple, bytes] = {}
_CACHE_BYTES = 0
_CACHE_MAX = 96 * 1024 * 1024  # borne mémoire d'un run


def clear_cache() -> None:
    global _CACHE_BYTES
    _CACHE.clear()
    _CACHE_BYTES = 0


def _cache_key(im: "Image.Image", level: int) -> tuple:
    return (hashlib.blake2b(im.tobytes(), digest_size=16).digest(),
            im.size, im.mode, level)


@contextlib.contextmanager
def fast_png(level: int = GAME_LEVEL, cache: bool = True):
    """Force le niveau PNG par défaut et réutilise les encodages identiques.

    Restaure `Image.SAVE["PNG"]` en sortie, même en cas d'exception.
    """
    global _CACHE_BYTES

    def _patched(im, fp, filename, *a, **kw):
        global _CACHE_BYTES
        lvl = int(im.encoderinfo.get("compress_level", level))
        im.encoderinfo["compress_level"] = lvl   # applique réellement le niveau
        if not cache or kw.get("save_all"):
            return _ORIG_PNG_SAVE(im, fp, filename, *a, **kw)
        key = _cache_key(im, lvl)
        data = _CACHE.get(key)
        if data is None:
            buf = io.BytesIO()
            _ORIG_PNG_SAVE(im, buf, filename, *a, **kw)
            data = buf.getvalue()
            if _CACHE_BYTES + len(data) <= _CACHE_MAX:
                _CACHE[key] = data
                _CACHE_BYTES += len(data)
        if isinstance(fp, (str, os.PathLike)):
            with open(fp, "wb") as fh:
                fh.write(data)
        else:
            fp.write(data)
        return None

    Image.SAVE["PNG"] = _patched
    try:
        yield
    finally:
        Image.SAVE["PNG"] = _ORIG_PNG_SAVE
