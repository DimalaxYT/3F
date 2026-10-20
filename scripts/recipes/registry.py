"""Registre des recettes : chaque recette est une fonction build(**params) -> Builder."""

REGISTRY = {}


def register(name, defaults=None, info=None):
    """Décorateur : enregistre un builder avec ses paramètres par défaut et leur doc.

    info : liste de dicts {name, type, help, choices?} documentant chaque paramètre.
    """
    def deco(fn):
        REGISTRY[name] = {
            "builder": fn,
            "defaults": dict(defaults or {}),
            "info": info or [],
            "module": fn.__module__.split(".")[-1],
        }
        return fn
    return deco


def get(name):
    if name not in REGISTRY:
        raise KeyError(f"recette inconnue: {name!r} — disponibles: {sorted(REGISTRY)}")
    return REGISTRY[name]


def catalog():
    """Catalogue complet {name: {defaults, info, module}} trié."""
    return {k: {"defaults": v["defaults"], "info": v["info"], "module": v["module"]}
            for k, v in sorted(REGISTRY.items())}
