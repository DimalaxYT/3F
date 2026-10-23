"""Catalogue de recettes 3d-forge. Importer ce package peuple le registre."""
from .registry import REGISTRY, register, get, catalog  # noqa: F401
from . import furniture, containers, props, characters, weapons  # noqa: F401  (peuplent le registre)
