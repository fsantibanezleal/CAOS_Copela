"""The chat-completions providers (Z.AI, DeepSeek): what they send, and what they make of replies.

No network. The transport is replaced, so every field of the request is pinned and every response
shape the API documents is exercised, including an error whose body names the cause. A reply that
reasoned and never answered is tested once for every lane, in test_providers.py (R-022).
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from copela import providers
from copela.providers import ProviderError, ZaiProvider


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(payload: dict, seen: list):
    def urlopen(request, timeout=None):
        seen.append((request.full_url, dict(request.header_items()), json.loads(request.data)))
        return _Response(json.dumps(payload).encode("utf-8"))

    return urlopen


def test_it_refuses_to_construct_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    with pytest.raises(ProviderError) as caught:
        providers.get("zai")
    assert "ZAI_API_KEY" in str(caught.value)


def test_a_zero_temperature_is_sent_as_greedy_decoding_and_no_seed_is_sent() -> None:
    provider = ZaiProvider(api_key="k")
    body = provider.request_body("p", model_id="glm-4.7", temperature=0.0, max_tokens=64)
    assert body["do_sample"] is False
    assert "temperature" not in body
    assert "seed" not in body
    assert body["stream"] is False
    assert body["max_tokens"] == 64

    sampled = provider.request_body("p", model_id="glm-4.7", temperature=0.6, max_tokens=64)
    assert sampled["temperature"] == 0.6
    assert "do_sample" not in sampled


def test_effort_is_sent_only_to_the_models_that_take_it() -> None:
    provider = ZaiProvider(api_key="k", effort="low")
    assert provider.request_body("p", model_id="glm-5.3", temperature=0.0, max_tokens=8)[
        "reasoning_effort"
    ] == "low"
    assert "reasoning_effort" not in provider.request_body(
        "p", model_id="glm-4.7", temperature=0.0, max_tokens=8
    )
    assert provider.fingerprint("glm-5.3", 0.0) == "zai#effort=low#do_sample=false#no-seed"
    assert provider.fingerprint("glm-4.7", 0.7) == "zai#effort=model-decides#temperature=0.7#no-seed"


def test_a_completion_is_mapped_with_its_usage_and_cost(monkeypatch) -> None:
    seen: list = []
    payload = {
        "model": "glm-5.3",
        "choices": [{"message": {"content": "{}", "reasoning_content": "thought"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 2000},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(payload, seen))
    provider = ZaiProvider(api_key="secret", base_url="https://example.test/v4/")
    completion = provider.complete("prompt", model_id="glm-5.3", temperature=0.0, max_tokens=100)

    url, headers, body = seen[0]
    assert url == "https://example.test/v4/chat/completions"
    assert headers["Authorization"] == "Bearer secret"
    assert body["model"] == "glm-5.3" and body["messages"][0]["content"] == "prompt"
    assert completion.text == "{}"
    assert (completion.input_tokens, completion.output_tokens) == (1000, 2000)
    # 1000 input at 1.4 and 2000 output at 4.4 per million.
    assert completion.cost_usd == pytest.approx(0.0014 + 0.0088)
    assert completion.fingerprint.startswith("zai#effort=high")


def test_an_http_error_carries_its_body_into_the_message(monkeypatch) -> None:
    def urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":{"message":"unknown model"}}')
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(ProviderError) as caught:
        ZaiProvider(api_key="k").complete("p", model_id="glm-9")
    assert "HTTP 400" in str(caught.value) and "unknown model" in str(caught.value)


def test_the_table_holds_what_is_both_priced_and_callable() -> None:
    """Checked 2026-09-23 against the pricing page, ``/models`` and a call to each unlisted one."""
    models = ZaiProvider(api_key="k").models()
    assert (models["glm-5.3"].input_per_mtok, models["glm-5.3"].output_per_mtok) == (1.4, 4.4)
    assert (models["glm-5.3-flash"].input_per_mtok, models["glm-5.3-flash"].output_per_mtok) == (
        0.15,
        0.50,
    )
    # Free, unlisted by /models, and it answered a call on both endpoints with no balance.
    assert models["glm-4.5-flash"].cost(10**6, 10**6) == 0.0
    # Listed by /models and priced nowhere: a sweep must refuse it rather than count it as free.
    assert "glm-5-turbo" not in models


def test_the_flash_models_of_the_5_3_family_take_the_effort_too() -> None:
    provider = ZaiProvider(api_key="k")
    for model_id in ("glm-5.3-flash", "glm-5.3-flashx", "glm-5.2"):
        body = provider.request_body("p", model_id=model_id, temperature=0.0, max_tokens=8)
        assert body["reasoning_effort"] == "high", model_id
    for model_id in ("glm-5.1", "glm-4.5-flash"):
        body = provider.request_body("p", model_id=model_id, temperature=0.0, max_tokens=8)
        assert "reasoning_effort" not in body, model_id


def test_deepseek_sends_its_effort_and_no_temperature_or_seed() -> None:
    """Temperature has no effect in DeepSeek's thinking mode, so none is sent or claimed."""
    provider = providers.DeepSeekProvider(api_key="k")
    body = provider.request_body("p", model_id="deepseek-v4-pro", temperature=0.0, max_tokens=32)
    assert body["reasoning_effort"] == "high"
    assert "temperature" not in body and "seed" not in body and "do_sample" not in body
    assert provider.fingerprint("deepseek-v4-pro", 0.0) == (
        "deepseek#effort=high#temperature-no-effect-in-thinking#no-seed"
    )
    # Peak-hour prices: the guard errs towards stopping early.
    pricing = provider.models()["deepseek-v4-pro"]
    assert (pricing.input_per_mtok, pricing.output_per_mtok) == (1.32, 3.96)


def test_the_served_model_name_is_kept_when_it_differs_from_the_request(monkeypatch) -> None:
    """One endpoint served GLM-5.3 to a request for GLM-5.2; the ledger must say so."""
    payload = {
        "model": "glm-5.3",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(payload, []))
    completion = ZaiProvider(api_key="k").complete("p", model_id="glm-5.2")
    assert completion.model_id == "glm-5.2"
    assert completion.model_version == "glm-5.3"
