"""Game families supported by the builder. Each module provides the reference payoff model,
quiz generation and budget bounds for its family; templates live in ``expbuilder/templates/<game>``."""
from . import public_goods

GAMES = {"public_goods": public_goods}
