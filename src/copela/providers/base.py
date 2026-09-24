"""The provider seam.

One interface, several backends. No provider name, SDK import or model string appears anywhere in
this package outside ``copela/providers/``, and a test enforces that.

This is a requirement rather than tidiness. The modelling-and-simulation benchmark reports that no
single language model dominates across engine types, with task-specific tradeoffs between speed and
accuracy. A harness wired to one provider cannot report that, and a ranking claimed from one model
contradicts a published finding.

Each provider reports a ``fingerprint``: whatever the backend gives that identifies the serving
configuration behind a response. It goes in the ledger because it is the only handle on the part of
nondeterminism that no seed controls.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Pricing:
    """Cost per million tokens, for the budget guard.

    Prices move. These are configuration, not knowledge: a provider reads them from its model
    registry, and a stale price makes the budget guard wrong, not the harness.
    """

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000


@dataclass(frozen=True, slots=True)
class Completion:
    """What every provider returns, whatever its SDK looks like."""

    text: str
    model_id: str
    model_version: str
    fingerprint: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    pricing: Pricing = field(default_factory=Pricing)

    @property
    def cost_usd(self) -> float:
        return self.pricing.cost(self.input_tokens, self.output_tokens)


class ProviderError(RuntimeError):
    """A call failed. Carried into the ledger as an executable-layer failure, never swallowed."""


class ProviderUnreachable(ProviderError):
    """The call never reached the model: the connection failed before any response, or the provider
    refused the credentials. It says nothing about the model, so a sweep stops on it and records
    nothing (R-035).

    The distinction is the response. An HTTP 500 is the provider's answer to this call and is
    recorded like any failure; a connection refused, a name that did not resolve, a TLS failure or a
    401 is the harness failing to ask. Recording those wrote rows about a network or a key file into
    an append-only ledger, as rows about the model.
    """


#: The exception names, in the SDKs that copela does not depend on, that mean the request never got
#: an answer about the model: a transport failure, or rejected credentials.
UNREACHABLE_NAMES = frozenset(
    {"APIConnectionError", "APITimeoutError", "AuthenticationError", "PermissionDeniedError"}
)


def unreachable(error: BaseException) -> bool:
    """Whether an SDK exception means the call never reached the model. Read by class name along the
    exception's MRO, so a subclass counts and no SDK has to be imported to ask."""
    return any(cls.__name__ in UNREACHABLE_NAMES for cls in type(error).__mro__)


class Provider(abc.ABC):
    """The only way the harness reaches a language model."""

    #: Short stable name recorded in the ledger.
    name: str = ""

    @abc.abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        model_id: str,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        """Run one completion.

        ``temperature`` and ``seed`` are pinned and recorded. Neither buys determinism over a hosted
        API, and the harness does not pretend otherwise: it reports a rate over repeats with an
        interval. See the reporting module.
        """

    @abc.abstractmethod
    def models(self) -> dict[str, Pricing]:
        """The model ids this provider can serve, with their pricing."""

    def supports(self, model_id: str) -> bool:
        return model_id in self.models()


class StubProvider(Provider):
    """A scripted provider for tests and dry runs.

    It is in the package rather than the test tree on purpose: a dry run that exercises the whole
    sweep without spending anything is worth having in the shipped tool, and it is how the budget
    guard and the resume path are tested without a network.
    """

    name = "stub"

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        default: str = "",
        pricing: Pricing | None = None,
        fail_on: set[str] | None = None,
        unreachable_after: int | None = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default
        self._pricing = pricing or Pricing(input_per_mtok=1.0, output_per_mtok=5.0)
        self._fail_on = fail_on or set()
        #: After this many calls, every further call fails to reach the provider, as a network does
        #: when it drops in the middle of a sweep.
        self._unreachable_after = unreachable_after
        self.calls: list[tuple[str, str, float, int | None]] = []

    def complete(
        self,
        prompt: str,
        *,
        model_id: str,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int = 4096,
    ) -> Completion:
        if self._unreachable_after is not None and len(self.calls) >= self._unreachable_after:
            raise ProviderUnreachable("stub configured to lose its connection")
        self.calls.append((prompt, model_id, temperature, seed))
        if model_id in self._fail_on:
            raise ProviderError(f"stub configured to fail for {model_id!r}")
        text = self._responses.get(prompt, self._default)
        return Completion(
            text=text,
            model_id=model_id,
            model_version=f"{model_id}-stub",
            fingerprint="stub-fingerprint",
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            latency_ms=0.0,
            pricing=self._pricing,
        )

    def models(self) -> dict[str, Pricing]:
        return {"stub-small": self._pricing, "stub-large": self._pricing}
