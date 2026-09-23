"""Gates for R-006, the provider seam does not leak, and R-022, a truncation is reported."""

from __future__ import annotations

import io
import json
import pathlib
import re
from types import SimpleNamespace

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
    "api.z.ai",
    "api.deepseek.com",
    "deepseek-",
    "glm-",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "ZAI_API_KEY",
    "DEEPSEEK_API_KEY",
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
    assert set(providers.REGISTRY) >= {"anthropic", "deepseek", "groq", "ollama", "stub", "zai"}


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


class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _replying(body: dict):
    return lambda request, timeout=None: _Body(json.dumps(body).encode("utf-8"))


def _groq_client(reasoning: str) -> SimpleNamespace:
    """The SDK surface the Groq lane touches, replying with reasoning and no answer."""
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", reasoning=reasoning), finish_reason="length"
            )
        ],
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=8192),
        model="openai/gpt-oss-120b",
        system_fingerprint="fp_test",
    )
    completions = SimpleNamespace(create=lambda **_: response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _complete_with_reasoning_only(lane: str, reasoning: str, monkeypatch):
    if lane == "ollama":
        body = {
            "model": "qwen3:8b",
            "response": "",
            "thinking": reasoning,
            "done_reason": "length",
            "eval_count": 8192,
        }
        monkeypatch.setattr("urllib.request.urlopen", _replying(body))
        return providers.OllamaProvider(host="http://local.test").complete("p", model_id="qwen3:8b")
    if lane == "groq":
        provider = providers.GroqProvider(api_key="k")
        provider._client = _groq_client(reasoning)
        return provider.complete("p", model_id="openai/gpt-oss-120b")
    body = {
        "model": "m",
        "choices": [
            {"message": {"content": "", "reasoning_content": reasoning}, "finish_reason": "length"}
        ],
        "usage": {"prompt_tokens": 900, "completion_tokens": 8192},
    }
    monkeypatch.setattr("urllib.request.urlopen", _replying(body))
    return providers.REGISTRY[lane](api_key="k").complete("p", model_id="m")


@pytest.mark.parametrize("lane", ["ollama", "zai", "deepseek", "groq"])
def test_reasoning_with_no_answer_is_a_truncation_on_every_lane(lane, monkeypatch) -> None:
    """R-022: every lane that can reason reports a reasoning-only reply as the truncation it is.

    qwen3.5:4b spent every call on about 3100 characters of reasoning and answered nothing, and an
    empty string would have recorded a model with nothing to say. The sentence is the same on every
    lane because a report classifies truncations by it. Anthropic is not a lane here: the provider
    enables no thinking, so a reply carries no reasoning to report.
    """
    completion = _complete_with_reasoning_only(lane, "x" * 3100, monkeypatch)

    assert completion.text.startswith(
        "[no answer: the model emitted 3100 characters of reasoning and stopped before answering "
        "(finish_reason length). Raise max_tokens"
    ), completion.text
    assert completion.text.endswith("]")
    assert completion.output_tokens == 8192
