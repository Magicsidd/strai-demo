"""AI-laget: to ekte backends (Anthropic API og Claude Code CLI) og én regelbasert reserve.

Alle backends får samme prompt og returnerer tekst. Teksten parses og valideres
mot Pydantic-modellene i ai.modeller. Feiler noe, merkes saken for manuell vurdering.
"""
from .tjeneste import AIResultat, Bilde, vurder_reklamasjon, vurder_tegnetime
from .backends import velg_backend

__all__ = ["AIResultat", "Bilde", "vurder_reklamasjon", "vurder_tegnetime", "velg_backend"]
