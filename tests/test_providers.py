"""Gate for R-006: the provider seam does not leak."""

from __future__ import annotations

import pathlib
import re

import pytest

import copela
from copela import providers

SOURCE_ROOT = pathlib.Path(copela.__file__).parent
PROVIDERS_DIR = SOURCE_ROOT / "providers"

#: Names that must not appear outside the seam. Written to match code, not prose: the docstrings in
#: this package explain why several providers exist, and forbidding the words entirely would force
#: the explanation out of the code.
VENDOR_TOKENS = (
    "anthropic",
    "openai",
    "groq",
    "ollama",
    "claude-",
    "gpt-",
    "llama-",
    "api.groq.com",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
)


def _code_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """Source lines with comments and docstring bodies removed, crudely but conservatively."""
    out: list[tuple[int, str]] = []
    in_docstring = False
    delimiter = ""
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw
        if in_docstring:
            if delimiter in line:
                in_docstring = False
                line = line.split(delimiter, 1)[1]
            else:
                continue
        stripped = line.strip()
        for quote in ('"""', "'''"):
            if stripped.startswith(quote):
                rest = stripped[3:]
                if quote not in rest:
                    in_docstring = True
                    delimiter = quote
                    line = ""
                else:
                    line = rest.split(quote, 1)[1]
                break
        line = re.sub(r"#.*$", "", line)
        if line.strip():
            out.append((number, line))
    return out


def test_no_provider_name_leaks_outside_the_seam() -> None:
    """R-006: vendor names live in copela/providers/ and nowhere else."""
    offenders: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if PROVIDERS_DIR in path.parents or path == PROVIDERS_DIR:
            continue
        for number, line in _code_lines(path):
            lowered = line.lower()
            for token in VENDOR_TOKENS:
                if token.lower() in lowered:
                    offenders.append(
                        f"{path.relative_to(SOURCE_ROOT)}:{number}: {token!r} in {line.strip()[:70]}"
                    )
    assert not offenders, "a vendor name escaped the seam:\n  " + "\n  ".join(offenders)


def test_the_harness_selects_a_provider_by_name() -> None:
    provider = providers.get("stub")
    assert provider.name == "stub"
    assert set(providers.REGISTRY) >= {"anthropic", "groq", "ollama", "stub"}


def test_an_unknown_provider_is_refused_with_the_known_list() -> None:
    with pytest.raises(providers.ProviderError) as caught:
        providers.get("not-a-provider")
    assert "stub" in str(caught.value)


def test_every_provider_implements_the_whole_interface() -> None:
    for name, constructor in providers.REGISTRY.items():
        for method in ("complete", "models"):
            assert callable(getattr(constructor, method, None)), f"{name} is missing {method}"
        assert getattr(constructor, "name", ""), f"{name} does not declare its seam name"


def test_a_hosted_provider_refuses_to_construct_without_a_key(monkeypatch) -> None:
    """A missing key is an error at construction, not a confusing failure mid-sweep."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(providers.ProviderError) as caught:
        providers.get("anthropic")
    assert "key" in str(caught.value).lower()


def test_the_stub_records_what_it_was_asked(monkeypatch) -> None:
    provider = providers.StubProvider(default="ok")
    completion = provider.complete(
        "a prompt", model_id="stub-small", temperature=0.0, seed=7
    )
    assert provider.calls == [("a prompt", "stub-small", 0.0, 7)]
    assert completion.model_id == "stub-small"
    assert completion.fingerprint
    assert completion.cost_usd > 0


def test_pricing_is_per_million_tokens() -> None:
    pricing = providers.Pricing(input_per_mtok=3.0, output_per_mtok=15.0)
    assert pricing.cost(1_000_000, 0) == pytest.approx(3.0)
    assert pricing.cost(0, 1_000_000) == pytest.approx(15.0)
    assert providers.Pricing().cost(10**9, 10**9) == 0.0
