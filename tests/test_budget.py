"""Gates for R-005, R-024 and R-025: the budget guard."""

from __future__ import annotations

import json

import pytest

from copela import (
    Budget,
    BudgetExceeded,
    Case,
    Ledger,
    StubProvider,
    Sweep,
    Target,
    UnpricedModel,
    estimate,
)
from copela.providers import Completion, Pricing


def test_sweep_stops_before_the_budget(ledger_path) -> None:
    """R-005: the sweep stops before exceeding the ceiling, not after.

    The guard runs before the call. A guard that noticed an overrun afterwards would be an
    accountant, not a guard.
    """
    expensive = Pricing(input_per_mtok=1000.0, output_per_mtok=1000.0)
    provider = StubProvider(default=json.dumps({"schema_version": "1.0"}), pricing=expensive)
    ledger = Ledger(ledger_path)

    budget = Budget(limit_usd=0.005)
    sweep = Sweep(
        ledger=ledger,
        budget=budget,
        providers={"stub": provider},
        build_prompt=lambda case: "formalize this narrative " * 40,
        parse_response=lambda text, case: None,  # type: ignore[return-value]
        repeats=50,
        max_tokens=1200,
    )

    made = sweep.run([Case("c1", "optimization", "n")], [Target("stub", "stub-small")])

    assert made < 50, "the sweep ran every call despite the ceiling"
    assert budget.spent_usd <= budget.limit_usd, (
        f"spent {budget.spent_usd} against a limit of {budget.limit_usd}"
    )
    assert len(ledger.records()) == made


def test_the_guard_refuses_the_call_that_would_exceed() -> None:
    budget = Budget(limit_usd=1.0)
    budget.charge(0.9)
    budget.check(0.05)
    with pytest.raises(BudgetExceeded) as caught:
        budget.check(0.2)
    assert "stopping before the budget" in str(caught.value)


def test_the_kill_criterion_stops_a_sweep_that_is_only_failing() -> None:
    budget = Budget(limit_usd=1000.0, max_consecutive_failures=3)
    for _ in range(3):
        budget.charge(0.0, failed=True)
    with pytest.raises(BudgetExceeded) as caught:
        budget.check(0.0)
    assert "kill criterion" in str(caught.value)


def test_a_success_resets_the_failure_run() -> None:
    budget = Budget(limit_usd=10.0, max_consecutive_failures=2)
    budget.charge(0.0, failed=True)
    budget.charge(0.0, failed=False)
    budget.charge(0.0, failed=True)
    budget.check(0.0)  # must not raise: the run was broken by the success


def test_the_estimate_is_conservative() -> None:
    """The estimate must not come in under the real cost, or the guard stops too late."""
    prompt = "x" * 4000
    expected_output = 1000
    estimated = estimate(prompt, expected_output, 3.0, 15.0)
    actual = Pricing(3.0, 15.0).cost(len(prompt) // 4, expected_output)
    assert estimated >= actual * 0.999


def test_a_negative_budget_is_refused() -> None:
    with pytest.raises(ValueError):
        Budget(limit_usd=-1.0)


def test_the_budget_describes_itself() -> None:
    budget = Budget(limit_usd=2.0)
    budget.charge(0.5)
    text = budget.describe()
    assert "0.5000" in text and "2.0000" in text and "1.5000" in text


def _sweep(ledger_path, provider, budget, **overrides) -> Sweep:
    return Sweep(
        ledger=Ledger(ledger_path),
        budget=budget,
        providers={"stub": provider},
        build_prompt=lambda case: "formalize this narrative " * 40,
        parse_response=lambda text, case: None,  # type: ignore[return-value]
        **overrides,
    )


def test_an_unpriced_model_is_refused_before_any_call(ledger_path) -> None:
    """R-024: a model the guard has no price for is refused before anything is spent.

    It used to be projected at zero and charged at zero, so the budget never moved while the calls
    were billed.
    """
    provider = StubProvider(default="{}")
    sweep = _sweep(ledger_path, provider, Budget(limit_usd=1.0))

    with pytest.raises(UnpricedModel) as caught:
        sweep.run([Case("c1", "optimization", "n")], [Target("stub", "stub-unlisted")])

    assert provider.calls == [], "a call was made to a model the guard could not price"
    assert Ledger(ledger_path).records() == []
    message = str(caught.value)
    assert "stub-unlisted" in message and "stub-small" in message, message


class _FillsItsCap(StubProvider):
    """A reasoning model, as billed: every call spends its whole output cap."""

    def complete(self, prompt, *, model_id, temperature=0.0, seed=None, max_tokens=4096):
        completion = super().complete(
            prompt, model_id=model_id, temperature=temperature, seed=seed, max_tokens=max_tokens
        )
        return Completion(
            text=completion.text,
            model_id=completion.model_id,
            model_version=completion.model_version,
            fingerprint=completion.fingerprint,
            input_tokens=completion.input_tokens,
            output_tokens=max_tokens,
            latency_ms=0.0,
            pricing=completion.pricing,
        )


def test_the_projection_bounds_a_call_that_fills_its_cap(ledger_path) -> None:
    """R-025: the guard projects each call at the most it can bill, its output cap.

    With the old projection, 1200 output tokens, three calls of 8.192 USD each pass a 20 USD
    ceiling and spend 24.576. The first two measured reasoning models spent 5206 and 7931 output
    tokens on one case, so this is the shape of a real overrun, not a contrived one.
    """
    provider = _FillsItsCap(default="{}", pricing=Pricing(input_per_mtok=0.0, output_per_mtok=1000.0))
    budget = Budget(limit_usd=20.0)
    sweep = _sweep(ledger_path, provider, budget, repeats=10, max_tokens=8192)

    made = sweep.run([Case("c1", "optimization", "n")], [Target("stub", "stub-small")])

    assert made == 2, f"made {made} calls of 8.192 USD against a 20 USD ceiling"
    assert budget.spent_usd <= budget.limit_usd, (
        f"spent {budget.spent_usd} against a limit of {budget.limit_usd}"
    )
