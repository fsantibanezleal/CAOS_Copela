"""Hosted and local providers behind the seam.

Five backends, one interface: Anthropic and Groq through their SDKs, and the local lane, Z.AI and
DeepSeek over plain HTTP. The SDK imports are deliberately inside the methods: the package installs
with no provider dependency at all, and a user who only wants the local lane never installs a cloud
SDK.

Pricing is configuration, not knowledge. Published prices move, and a stale number here makes the
budget guard wrong rather than the harness. Every entry carries the date it was set, so a reader can
see how old it is instead of trusting it.
"""

from __future__ import annotations

import os
import time

from .base import Completion, Pricing, Provider, ProviderError, ProviderUnreachable, unreachable


def no_answer_text(reasoned_chars: int, finish_reason: object, remedy: str) -> str:
    """What a provider returns when the model reasoned and never answered (R-022).

    A reasoning model spends its output cap on reasoning first, so a reply can be all reasoning and
    no answer. That is a truncation, and an empty string would record it as a model with nothing to
    say. Every lane that can reason returns this same sentence, because a report classifies
    truncations by it.
    """
    cause = f" (finish_reason {finish_reason})" if finish_reason else ""
    return (
        f"[no answer: the model emitted {reasoned_chars} characters of reasoning and stopped "
        f"before answering{cause}. {remedy}]"
    )


class AnthropicProvider(Provider):
    """Claude models through the official SDK.

    Two things here are easy to get wrong and were wrong in the first version.

    **Model ids carry no date suffix.** `claude-sonnet-5`, not `claude-sonnet-5-20250101`. A dated
    variant recalled from older material is not a real id and fails at the API.

    **These models do not accept a temperature.** The parameter was removed, and the installed SDK
    does not even define it, so passing one is a `TypeError` rather than a polite rejection. The
    depth lever is `output_config.effort`. That matters beyond the call site: the run ledger records
    temperature as pinned provenance, and recording `0.0` for a provider that has no such control
    would be recording a number nobody set.

    Pricing below is configuration, set 2026-09-22 from the current published table. It moves.
    Re-check it before quoting a cost from a sweep.
    """

    name = "anthropic"

    _MODELS = {
        "claude-opus-5": Pricing(5.0, 25.0),
        "claude-sonnet-5": Pricing(2.0, 10.0),
        "claude-haiku-4-5": Pricing(1.0, 5.0),
    }

    #: Effort replaces temperature as the depth control, but NOT on every model: the current
    #: frontier models take it and Haiku 4.5 returns a 400 for it. So it is a per-model capability
    #: rather than a uniform parameter, and sending it everywhere makes the cheapest lane fail.
    _SUPPORTS_EFFORT = frozenset({"claude-opus-5", "claude-sonnet-5"})

    _DEFAULT_EFFORT = "high"

    def __init__(self, api_key: str | None = None, effort: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ProviderError(
                "no Anthropic API key: pass one, or set ANTHROPIC_API_KEY. "
                "The key belongs in the environment, never in a committed file"
            )
        self._effort = effort or self._DEFAULT_EFFORT
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

        # No temperature and no seed: neither exists on these models. Effort is the control that
        # does, where the model accepts it, so it is what gets pinned and recorded.
        uses_effort = model_id in self._SUPPORTS_EFFORT
        request: dict[str, object] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if uses_effort:
            request["output_config"] = {"effort": self._effort}

        started = time.perf_counter()
        try:
            message = client.messages.create(**request)  # type: ignore[arg-type]
        except Exception as error:  # the SDK's exception tree is not ours to depend on
            if unreachable(error):
                raise ProviderUnreachable(f"anthropic could not be reached: {error}") from error
            raise ProviderError(f"anthropic call failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000

        if getattr(message, "stop_reason", "") == "refusal":
            # A refusal is an HTTP 200 with no usable content. Treating it as an empty response
            # would record a formalization failure where the model declined to try.
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderError(
                f"anthropic declined the request (category {category or 'unspecified'})"
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        return Completion(
            text=text,
            model_id=model_id,
            model_version=getattr(message, "model", model_id),
            # No serving fingerprint is exposed, and temperature and seed do not exist on this
            # provider. The fingerprint records the control that DOES apply, so a ledger row says
            # what was actually pinned instead of implying a temperature nobody set.
            fingerprint=(
                f"anthropic#effort={self._effort}#no-temperature"
                if uses_effort
                else "anthropic#no-effort#no-temperature"
            ),
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
            if unreachable(error):
                raise ProviderUnreachable(f"groq could not be reached: {error}") from error
            raise ProviderError(f"groq call failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000

        usage = response.usage
        message = response.choices[0].message
        text = message.content or ""
        # The reasoning models here (gpt-oss) return their reasoning in ``message.reasoning`` by
        # default, and spend the cap on it first, like every other reasoning lane.
        reasoning = getattr(message, "reasoning", None) or ""
        if not text and reasoning:
            text = no_answer_text(
                len(reasoning),
                getattr(response.choices[0], "finish_reason", None),
                "Raise max_tokens or lower the effort",
            )
        return Completion(
            text=text,
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

    #: The context is requested in steps of this many tokens, so the cases of one corpus land on one
    #: size and the server does not reload the model between them.
    CONTEXT_STEP = 4096

    def __init__(
        self,
        host: str | None = None,
        think: bool | None = None,
        timeout_s: float = 3600.0,
    ) -> None:
        """``think`` switches a reasoning model's reasoning; ``timeout_s`` bounds one call.

        A reasoning model spends its output cap on reasoning first: qwen3:4b, on the first corpus
        case with a context that held the whole cap, reasoned for all 8192 tokens and answered
        nothing. ``False`` asks a reasoning model to answer directly and ``None`` leaves its default
        alone. A model that does not reason gets neither, because the switch would be a no-op and
        recording it would claim a control that did not exist (R-027).

        ``False`` is a request, and the model's template decides whether it is honoured. qwen3:8b's
        template appends ``/no_think`` and pre-fills an empty reasoning block; qwen3:4b's has no off
        path, and with ``False`` it wrote the same 29083 characters of reasoning into its answer
        instead of into the reasoning field. The fingerprint records what was asked; the response
        in the ledger shows what happened.

        The timeout is an hour rather than the hosted lanes' fifteen minutes: a local call costs
        nothing, and a model larger than the GPU runs partly on the CPU at a few tokens a second,
        so a full cap can take longer than a hosted call ever does.
        """
        host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        # Ollama's own tools take the host without a scheme ("127.0.0.1:11435"); urllib does not.
        self._host = (host if "://" in host else f"http://{host}").rstrip("/")
        self._think = think
        self._timeout_s = timeout_s
        self._shown: dict[str, dict] = {}
        self._digests: dict[str, str] | None = None

    @classmethod
    def context_for(cls, prompt: str, max_tokens: int) -> int:
        """A context that holds the prompt and the whole output cap (R-026).

        The server's default does not: it picks one from the GPU's memory, 4096 tokens on an 8 GB
        card, and a generation that outgrows it is not stopped. The server shifts the context,
        silently, and the model goes on writing with the start of its prompt gone. Measured on
        qwen3:4b and the first corpus case: 942 prompt tokens and 6109 generated inside a 4096
        window, finishing "stop" with an answer a fifth the length of a formalization. Two
        characters per token over-counts English, which is the safe direction here.
        """
        needed = len(prompt) // 2 + max_tokens
        return -(-needed // cls.CONTEXT_STEP) * cls.CONTEXT_STEP

    def _post(self, path: str, body: dict[str, object], timeout: float) -> dict:
        import json
        import urllib.request

        request = urllib.request.Request(
            f"{self._host}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _show(self, model_id: str) -> dict:
        """What the server says about a model, once per model: whether it reasons, its window."""
        if model_id not in self._shown:
            try:
                self._shown[model_id] = self._post("/api/show", {"model": model_id}, 30)
            except Exception:  # noqa: BLE001, an older server without the endpoint: assume nothing
                self._shown[model_id] = {}
        return self._shown[model_id]

    def _tags(self) -> list[dict]:
        import json
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(f"{self._host}/api/tags", timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ProviderError(f"cannot list ollama models at {self._host}: {error}") from error
        return list(body.get("models", []))

    def _digest(self, model_id: str) -> str:
        """The digest of the weights behind a tag (R-028). A tag is a name, and it can be re-pulled."""
        if self._digests is None:
            try:
                self._digests = {m["name"]: str(m.get("digest", "")) for m in self._tags()}
            except ProviderError:
                self._digests = {}
        return self._digests.get(model_id, "")

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

        shown = self._show(model_id)
        capabilities = shown.get("capabilities")
        reasons = None if capabilities is None else "thinking" in capabilities
        window = next(
            (
                int(value)
                for key, value in (shown.get("model_info") or {}).items()
                if key.endswith(".context_length")
            ),
            None,
        )

        num_ctx = self.context_for(prompt, max_tokens)
        if window is not None and num_ctx > window:
            if len(prompt) // 2 + max_tokens > window:
                raise ProviderError(
                    f"ollama: {model_id} has a {window}-token context, and the prompt plus a cap "
                    f"of {max_tokens} need more; the server would shift the context silently"
                )
            num_ctx = window

        options: dict[str, object] = {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": num_ctx,
        }
        if seed is not None:
            options["seed"] = seed

        body: dict[str, object] = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if self._think is not None and reasons is not False:
            body["think"] = self._think

        started = time.perf_counter()
        try:
            response_body = self._post("/api/generate", body, self._timeout_s)
        except urllib.error.HTTPError as error:
            # The body names the cause ("model not found", out of memory); the status alone does not.
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ProviderError(f"ollama call failed: HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            # No response at all: the server is down or the host is wrong. A read that times out
            # after connecting is the model taking too long, and stays a recorded failure.
            raise ProviderUnreachable(f"ollama could not be reached at {self._host}: {error}") from error
        except (TimeoutError, json.JSONDecodeError) as error:
            raise ProviderError(f"ollama call failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000

        text = response_body.get("response", "")
        if not text and response_body.get("thinking"):
            # The model reasoned and produced no answer, which is a truncation rather than a
            # refusal. Saying so in the text means the ledger records WHY instead of an empty
            # string that reads like a model that had nothing to say.
            text = no_answer_text(
                len(str(response_body["thinking"])),
                response_body.get("done_reason"),
                "Raise max_tokens or set think=False",
            )

        served = str(response_body.get("model", model_id))
        digest = self._digest(model_id)
        return Completion(
            text=text,
            model_id=model_id,
            # The tag plus the weights behind it, since a tag can be re-pulled onto new weights.
            model_version=f"{served}@{digest[:12]}" if digest else served,
            # A local model's serving configuration is the host, whether reasoning was switched,
            # and the context it was given, because each changes what is being measured. The same
            # weights on two machines, with reasoning toggled, or in a smaller window, are not the
            # same lane. "n/a" is a model with no reasoning to switch.
            fingerprint=(
                f"ollama@{self._host}#think={'n/a' if reasons is False else self._think}"
                f"#num_ctx={num_ctx}"
            ),
            input_tokens=int(response_body.get("prompt_eval_count", 0)),
            output_tokens=int(response_body.get("eval_count", 0)),
            latency_ms=latency_ms,
            pricing=Pricing(),  # local inference has no per-token price
        )

    def models(self) -> dict[str, Pricing]:
        """Whatever the local server has pulled. Queried, never assumed."""
        return {model["name"]: Pricing() for model in self._tags()}


class ChatCompletionsProvider(Provider):
    """A hosted model behind an OpenAI-shaped ``/chat/completions`` endpoint, over plain HTTP.

    No SDK, like the local lane. The vendors behind this shape each add fields no generic client
    knows about (a reasoning effort, a sampling switch), and each of those changes what is being
    measured, so a subclass writes its request out explicitly and says in its fingerprint which
    controls it actually exercised.

    Two behaviours are shared. A reasoning model bills its reasoning as output and spends
    ``max_tokens`` on it first, so a response that reasoned and stopped before answering is reported
    as that truncation rather than as an empty formalization. And an HTTP error keeps its body,
    because the body names the cause (an unknown model, an exhausted balance, a field the model
    does not take) and "HTTP 400" alone cannot be debugged from a ledger.
    """

    #: The environment variable holding the key, and the one that may override the endpoint.
    _KEY_ENV = ""
    _BASE_URL_ENV = ""
    _BASE_URL = ""
    _MODELS: dict[str, Pricing] = {}

    def __init__(
        self,
        api_key: str | None = None,
        effort: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 900.0,
    ) -> None:
        self._api_key = api_key or os.environ.get(self._KEY_ENV, "")
        if not self._api_key:
            raise ProviderError(
                f"no {self.name} API key: pass one, or set {self._KEY_ENV}. "
                "The key belongs in the environment, never in a committed file"
            )
        self._effort = effort or self._default_effort()
        self._base_url = (
            base_url or os.environ.get(self._BASE_URL_ENV) or self._BASE_URL
        ).rstrip("/")
        self._timeout_s = timeout_s

    def _default_effort(self) -> str:
        return "high"

    def request_body(
        self, prompt: str, *, model_id: str, temperature: float, max_tokens: int
    ) -> dict[str, object]:
        """The exact request, separated from the transport so a test can pin every field."""
        raise NotImplementedError

    def fingerprint(self, model_id: str, temperature: float) -> str:
        raise NotImplementedError

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

        body = self.request_body(
            prompt, model_id=model_id, temperature=temperature, max_tokens=max_tokens
        )
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            if error.code in (401, 403):
                # Rejected credentials are the harness failing to ask, not the model answering.
                raise ProviderUnreachable(
                    f"{self.name} refused the credentials: HTTP {error.code}: {detail}"
                ) from error
            raise ProviderError(f"{self.name} call failed: HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ProviderUnreachable(f"{self.name} could not be reached: {error}") from error
        except (TimeoutError, json.JSONDecodeError) as error:
            raise ProviderError(f"{self.name} call failed: {error}") from error
        latency_ms = (time.perf_counter() - started) * 1000

        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name} returned no choices: {str(payload)[:300]}")
        message = choices[0].get("message") or {}
        text = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        if not text and reasoning:
            text = no_answer_text(
                len(reasoning), choices[0].get("finish_reason"), "Raise max_tokens or lower the effort"
            )

        usage = payload.get("usage") or {}
        return Completion(
            text=text,
            model_id=model_id,
            # What the server says it ran, which is not always what was asked for: one endpoint
            # served GLM-5.3 to a request for GLM-5.2. The ledger keeps the served name.
            model_version=str(payload.get("model", model_id)),
            fingerprint=self.fingerprint(model_id, temperature),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            pricing=self._MODELS.get(model_id, Pricing()),
        )

    def models(self) -> dict[str, Pricing]:
        return dict(self._MODELS)


class ZaiProvider(ChatCompletionsProvider):
    """GLM models served by Z.AI.

    **Thinking.** GLM-5.3, GLM-5.3-Flash and GLM-4.7 always reason; GLM-5.2 and earlier decide per
    request. The depth is the top-level ``reasoning_effort`` (max, the API default, high, and low on
    the 5.3 family only), which exists from GLM-5.2 up. It is sent, and recorded, only to those
    models; the fingerprint of any other says the model decided.

    **Sampling.** The API defaults to temperature 1.0 and exposes no seed. A requested temperature
    of 0 is sent as ``do_sample: false``, the documented deterministic mode, rather than as a
    temperature the API describes as positive; any other value is sent as given. No seed is sent.

    **The endpoint depends on the plan.** The default is the pay-per-token endpoint. A GLM Coding
    Plan key is refused there (HTTP 429, "insufficient balance") and works on
    ``https://api.z.ai/api/coding/paas/v4``; ``ZAI_BASE_URL`` selects it. On that plan the calls are
    drawn from a quota, so the ledger's cost is the list-price equivalent, not what was billed. The
    plan does not cover every model: it refused GLM-4.7-FlashX for want of a balance.

    **The table is what is both priced and callable**, checked 2026-09-23, because neither source
    alone is the catalogue. The pricing page (docs.z.ai/guides/overview/pricing, USD per million
    tokens, uncached) prices models that ``/models`` does not list, and GLM-4.5-Flash, one of those,
    answered a call on both endpoints, free, with no balance at all. ``/models`` lists GLM-5-Turbo,
    which the page does not price, so it is left out and a sweep refuses it: a model the budget
    guard cannot price is a model it cannot bound. Prices move; re-check them before quoting a cost.
    """

    name = "zai"

    _KEY_ENV = "ZAI_API_KEY"
    _BASE_URL_ENV = "ZAI_BASE_URL"
    _BASE_URL = "https://api.z.ai/api/paas/v4"

    _MODELS = {
        "glm-5.3": Pricing(1.4, 4.4),
        "glm-5.3-flashx": Pricing(0.37, 1.25),
        "glm-5.3-flash": Pricing(0.15, 0.50),
        "glm-5.2": Pricing(1.4, 4.4),
        "glm-5.1": Pricing(1.4, 4.4),
        "glm-5": Pricing(1.0, 3.2),
        "glm-4.7": Pricing(0.6, 2.2),
        "glm-4.7-flashx": Pricing(0.07, 0.4),
        "glm-4.7-flash": Pricing(0.0, 0.0),
        "glm-4.6": Pricing(0.6, 2.2),
        "glm-4.5": Pricing(0.6, 2.2),
        "glm-4.5-air": Pricing(0.2, 1.1),
        "glm-4.5-flash": Pricing(0.0, 0.0),
    }

    #: ``reasoning_effort`` exists from GLM-5.2 up.
    _SUPPORTS_EFFORT = frozenset({"glm-5.3", "glm-5.3-flashx", "glm-5.3-flash", "glm-5.2"})

    def request_body(
        self, prompt: str, *, model_id: str, temperature: float, max_tokens: int
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if temperature <= 0:
            body["do_sample"] = False
        else:
            body["temperature"] = temperature
        if model_id in self._SUPPORTS_EFFORT:
            body["reasoning_effort"] = self._effort
        return body

    def fingerprint(self, model_id: str, temperature: float) -> str:
        sampling = "do_sample=false" if temperature <= 0 else f"temperature={temperature}"
        if model_id in self._SUPPORTS_EFFORT:
            effort = f"effort={self._effort}"
        else:
            effort = "effort=model-decides"
        return f"zai#{effort}#{sampling}#no-seed"


class DeepSeekProvider(ChatCompletionsProvider):
    """DeepSeek models, through the OpenAI-shaped endpoint the platform documents first.

    **Thinking is on by default**, and ``reasoning_effort`` (none, low, high, max; default high) is
    a top-level field that both switches it and sets its depth. It is sent explicitly so the ledger
    records a control that was exercised rather than a default that happened to apply.

    **Temperature has no effect in thinking mode**, by the API's own reference, so none is sent and
    the fingerprint says so instead of recording a pinned value nobody set. No seed exists.

    **Names are retired and re-pointed.** ``deepseek-v4-flash`` is still accepted and served by
    DeepSeek-V4.1-Flash. The ledger keeps the name the server reports, not the one requested. The
    table holds the two names ``/models`` listed on 2026-09-23.

    Pricing is configuration, set 2026-09-23 from api-docs.deepseek.com/quick_start/pricing, at the
    PEAK rate (cache miss), the higher of the two: off-peak is half, and a guard that errs should
    err towards stopping early.
    """

    name = "deepseek"

    _KEY_ENV = "DEEPSEEK_API_KEY"
    _BASE_URL_ENV = "DEEPSEEK_BASE_URL"
    _BASE_URL = "https://api.deepseek.com"

    _MODELS = {
        "deepseek-v4-pro": Pricing(1.32, 3.96),
        "deepseek-flash": Pricing(0.3, 1.2),
    }

    def request_body(
        self, prompt: str, *, model_id: str, temperature: float, max_tokens: int
    ) -> dict[str, object]:
        return {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
            "reasoning_effort": self._effort,
        }

    def fingerprint(self, model_id: str, temperature: float) -> str:
        return f"deepseek#effort={self._effort}#temperature-no-effect-in-thinking#no-seed"
