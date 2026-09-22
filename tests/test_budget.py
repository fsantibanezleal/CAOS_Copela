"""Gate for R-005."""

from __future__ import annotations

import json

import pytest

from copela import Budget, BudgetExceeded, Case, Ledger, StubProvider, Sweep, Target, estimate
from copela.providers import Pricing


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
        parse_response=lambda text: None,  # type: ignore[return-value]
        repeats=50,
        expected_output_tokens=1200,
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
