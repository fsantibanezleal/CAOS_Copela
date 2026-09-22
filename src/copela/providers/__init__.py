"""Providers. Everything that knows a vendor's name lives in here and nowhere else."""

from __future__ import annotations

from .base import Completion, Pricing, Provider, ProviderError, StubProvider
from .hosted import AnthropicProvider, GroqProvider, OllamaProvider

#: Constructors by seam name. The harness selects by string and never imports a vendor module.
REGISTRY: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
    "ollama": OllamaProvider,
    "stub": StubProvider,
}


def get(name: str, **kwargs: object) -> Provider:
    """Build a provider by seam name."""
    try:
        constructor = REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(REGISTRY))
        raise ProviderError(f"unknown provider {name!r}; known: {known}") from None
    return constructor(**kwargs)  # type: ignore[arg-type]


__all__ = [
    "REGISTRY",
    "AnthropicProvider",
    "Completion",
    "GroqProvider",
    "OllamaProvider",
    "Pricing",
    "Provider",
    "ProviderError",
    "StubProvider",
    "get",
]
