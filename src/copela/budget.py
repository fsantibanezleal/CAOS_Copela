"""The budget guard: stop before the limit, not after it.

A sweep is cases times models times repeats, and each cell costs money. The guard exists because the
failure it prevents has happened on this account: an unattended job consumed a week of quota in
about a day.

The rule is that the guard refuses the call that *would* exceed the budget, rather than noticing
afterwards. A guard that reports an overrun is an accountant, not a guard.
"""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """Raised when a call would take the sweep past its declared budget."""


class UnpricedModel(RuntimeError):
    """Raised before a sweep's first call when a target has no price to bound it with.

    A model with no price is projected at zero and charged at zero, so a guard asked to bound it
    would never stop anything. Refusing is the only behaviour that keeps the promise.
    """


@dataclass
class Budget:
    """A spend ceiling and a kill criterion, both declared before the sweep runs.

    ``limit_usd`` is the hard ceiling. ``max_consecutive_failures`` is the kill criterion: a sweep
    whose calls are all failing is buying nothing, and continuing to the ceiling is waste.
    """

    limit_usd: float
    max_consecutive_failures: int = 10
    spent_usd: float = 0.0
    consecutive_failures: int = 0
    calls: int = 0

    def __post_init__(self) -> None:
        if self.limit_usd < 0:
            raise ValueError("a budget cannot be negative")

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def check(self, estimated_usd: float) -> None:
        """Raise if this call would exceed the ceiling. Call BEFORE spending."""
        if self.spent_usd + estimated_usd > self.limit_usd:
            raise BudgetExceeded(
                f"this call is estimated at {estimated_usd:.4f} USD and "
                f"{self.spent_usd:.4f} of {self.limit_usd:.4f} is already spent; "
                "stopping before the budget rather than after it"
            )
        if self.consecutive_failures >= self.max_consecutive_failures:
            raise BudgetExceeded(
                f"{self.consecutive_failures} consecutive failures reached the kill criterion; "
                "a sweep that is failing every call is buying nothing"
            )

    def charge(self, actual_usd: float, *, failed: bool = False) -> None:
        """Record what a completed call actually cost."""
        self.spent_usd += actual_usd
        self.calls += 1
        self.consecutive_failures = self.consecutive_failures + 1 if failed else 0

    def describe(self) -> str:
        return (
            f"{self.spent_usd:.4f} of {self.limit_usd:.4f} USD over {self.calls} call(s), "
            f"{self.remaining_usd:.4f} remaining"
        )


def estimate(
    prompt: str,
    output_tokens: int,
    input_per_mtok: float,
    output_per_mtok: float,
) -> float:
    """A cost estimate before the call: the prompt from a crude token count, the output at a bound.

    The sweep passes the call's ``max_tokens`` as ``output_tokens``, the most the call can bill,
    and not a typical length. A typical length is what an earlier version used, 1200 tokens, and
    reasoning models bill their reasoning as output: the first two measured spent 5206 and 7931
    tokens on one case, four to seven times the projection, so the guard could pass a call it
    should have refused.

    Four characters per prompt token is a rough English average and it is deliberately not
    refined: the estimate exists to keep the guard conservative, and a guard that under-estimates
    is worse than one that stops slightly early.
    """
    input_tokens = max(1, len(prompt) // 4)
    return (input_tokens * input_per_mtok + output_tokens * output_per_mtok) / 1_000_000
