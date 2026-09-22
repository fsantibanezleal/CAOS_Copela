"""Hosted and local providers behind the seam.

Three backends, one interface. The SDK imports are deliberately inside the methods: the package
installs with no provider dependency at all, and a user who only wants the local lane never installs
a cloud SDK.

Pricing is configuration, not knowledge. Published prices move, and a stale number here makes the
budget guard wrong rather than the harness. Every entry carries the date it was set, so a reader can
see how old it is instead of trusting it.
"""

from __future__ import annotations

import os
import time

from .base import Completion, Pricing, Provider, ProviderError


class AnthropicProvider(Provider):
    """Claude models through the official SDK.

    Pricing below was set 2026-09-22 and is not re-verified by the code. Check it before quoting a
    cost from a sweep.
    """

    name = "anthropic"

    _MODELS = {
        "claude-opus-5": Pricing(15.0, 75.0),
        "claude-sonnet-5": Pricing(3.0, 15.0),
        "claude-haiku-4-5-20251001": Pricing(1.0, 5.0),
    }

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ProviderError(
                "no Anthropic API key: pass one, or set ANTHROPIC_API_KEY. "
                "The key belongs in the environment, never in a committed file"
            )
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as error:
                raise ProviderError(
                    "the anthropic package is not installed: pip install 'copela[anthropic]'"
                ) from error
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        model_id: str,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        client = self._get_client()
        started = time.perf_counter()
        try:
            message = client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as error:  # the SDK's exception tree is not ours to depend on
            raise ProviderError(f"anthropic call failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000

        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        return Completion(
            text=text,
            model_id=model_id,
            model_version=getattr(message, "model", model_id),
            # This API exposes no serving fingerprint. Recording the absence explicitly is more
            # honest than recording an empty string that reads like a missing field.
            fingerprint="not-exposed",
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_ms=latency_ms,
            pricing=self._MODELS.get(model_id, Pricing()),
        )

    def models(self) -> dict[str, Pricing]:
        return dict(self._MODELS)


class GroqProvider(Provider):
    """Open-weight models served by Groq, through its OpenAI-compatible endpoint."""

    name = "groq"

    _MODELS = {
        "openai/gpt-oss-120b": Pricing(0.15, 0.60),
        "moonshotai/kimi-k2-instruct": Pricing(1.0, 3.0),
        "llama-3.3-70b-versatile": Pricing(0.59, 0.79),
    }

    _BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not self._api_key:
            raise ProviderError("no Groq API key: pass one, or set GROQ_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError as error:
                raise ProviderError(
                    "the openai package is not installed: pip install 'copela[openai]'"
                ) from error
            self._client = openai.OpenAI(api_key=self._api_key, base_url=self._BASE_URL)
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        model_id: str,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        client = self._get_client()
        started = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
            )
        except Exception as error:
            raise ProviderError(f"groq call failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000

        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            model_id=model_id,
            model_version=response.model,
            # The OpenAI-compatible shape carries a system fingerprint, which is the one handle on
            # the serving configuration that no seed controls.
            fingerprint=getattr(response, "system_fingerprint", "") or "not-exposed",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
            pricing=self._MODELS.get(model_id, Pricing()),
        )

    def models(self) -> dict[str, Pricing]:
        return dict(self._MODELS)


class OllamaProvider(Provider):
    """Local open-weight models. Zero marginal cost, and the data never leaves the machine.

    The local lane is bounded rather than default: small local models are weaker at structured,
    multi-step output than the frontier, which is exactly what this harness measures. Including
    them is the point; assuming they are equivalent is not.
    """

    name = "ollama"

    def __init__(self, host: str | None = None, think: bool | None = None) -> None:
        """``think`` controls a reasoning model's visible reasoning.

        It matters more than it looks. A reasoning model spends its output budget on reasoning
        first, so a small one can emit three thousand tokens of thought, hit the limit, and return
        nothing at all. Measured on qwen3.5:4b: every call produced about 3100 tokens of reasoning
        and no answer, which reads as a total formalization failure and is actually a truncation.

        ``None`` leaves the model's default alone, ``False`` asks it to answer directly. Whichever
        is used goes in the run record, because it changes what is being measured.
        """
        self._host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self._think = think

    def complete(
        self,
        prompt: str,
        *,
        model_id: str,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        import json
        import urllib.error
        import urllib.request

        options: dict[str, object] = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        if seed is not None:
            options["seed"] = seed

        body: dict[str, object] = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if self._think is not None:
            body["think"] = self._think

        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self._host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                response_body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ProviderError(f"ollama call failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000

        text = response_body.get("response", "")
        if not text and response_body.get("thinking"):
            # The model reasoned and produced no answer, which is a truncation rather than a
            # refusal. Saying so in the text means the ledger records WHY instead of an empty
            # string that reads like a model that had nothing to say.
            reasoned = len(str(response_body["thinking"]))
            text = (
                f"[no answer: the model emitted {reasoned} characters of reasoning and stopped "
                "before answering. Raise max_tokens or set think=False]"
            )

        return Completion(
            text=text,
            model_id=model_id,
            model_version=str(response_body.get("model", model_id)),
            # A local model's serving configuration is the host itself, plus whether reasoning was
            # on, because that changes what is being measured. The same weights on two machines,
            # or with reasoning toggled, are not the same lane.
            fingerprint=f"ollama@{self._host}#think={self._think}",
            input_tokens=int(response_body.get("prompt_eval_count", 0)),
            output_tokens=int(response_body.get("eval_count", 0)),
            latency_ms=latency_ms,
            pricing=Pricing(),  # local inference has no per-token price
        )

    def models(self) -> dict[str, Pricing]:
        """Whatever the local server has pulled. Queried, never assumed."""
        import json
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(f"{self._host}/api/tags", timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ProviderError(f"cannot list ollama models at {self._host}: {error}") from error
        return {model["name"]: Pricing() for model in body.get("models", [])}
