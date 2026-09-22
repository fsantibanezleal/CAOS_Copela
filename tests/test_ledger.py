"""Gates for R-003, R-004 and R-012."""

from __future__ import annotations

import json

import pytest

from copela import CallKey, Ledger, LedgerError, Record
from copela.ledger import REQUIRED_PROVENANCE


def make_record(**overrides) -> Record:
    base = dict(
        key=CallKey("case-001", "stub", "stub-small", 0),
        family="optimization",
        model_version="stub-small-stub",
        temperature=0.0,
        seed=20260922,
        provider_fingerprint="stub-fingerprint",
        prompt_digest="abc123",
        response_digest="def456",
        latency_ms=12.5,
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.0011,
    )
    base.update(overrides)
    return Record(**base)  # type: ignore[arg-type]


def test_every_call_pins_its_provenance(ledger_path) -> None:
    """R-003: model, version, temperature, fingerprint, prompt digest and repeat, on every record."""
    ledger = Ledger(ledger_path)
    ledger.append(make_record())

    written = json.loads(ledger_path.read_text(encoding="utf-8").strip())
    for name in REQUIRED_PROVENANCE:
        assert name in written, f"{name} missing from the record"
        assert written[name] not in (None, ""), f"{name} is empty"

    assert written["model_id"] == "stub-small"
    assert written["model_version"] == "stub-small-stub"
    assert written["provider_fingerprint"] == "stub-fingerprint"
    assert written["seed"] == 20260922
    assert written["recorded_at"]


@pytest.mark.parametrize("missing", ["model_version", "provider_fingerprint", "prompt_digest"])
def test_a_record_without_its_provenance_is_refused(ledger_path, missing) -> None:
    ledger = Ledger(ledger_path)
    with pytest.raises(LedgerError) as caught:
        ledger.append(make_record(**{missing: ""}))
    assert missing in str(caught.value)
    assert not ledger_path.exists() or not ledger_path.read_text(encoding="utf-8").strip()


def test_ledger_refuses_to_rewrite(ledger_path) -> None:
    """R-004: append-only. A second record for the same key is refused."""
    ledger = Ledger(ledger_path)
    ledger.append(make_record())

    with pytest.raises(LedgerError) as caught:
        ledger.append(make_record(cost_usd=99.0))
    assert "append-only" in str(caught.value)

    assert len(ledger.records()) == 1
    assert ledger.records()[0].cost_usd == pytest.approx(0.0011)


def test_a_different_repeat_is_a_different_call(ledger_path) -> None:
    ledger = Ledger(ledger_path)
    ledger.append(make_record(key=CallKey("case-001", "stub", "stub-small", 0)))
    ledger.append(make_record(key=CallKey("case-001", "stub", "stub-small", 1)))
    assert len(ledger.records()) == 2


def test_completed_calls_are_not_repeated(ledger_path) -> None:
    """R-012: a sweep resumes from the ledger without repeating finished work."""
    import json as _json

    from copela import Budget, Case, StubProvider, Sweep, Target
    from tests.conftest import make_blend

    provider = StubProvider(default=_json.dumps(make_blend().to_json()))
    ledger = Ledger(ledger_path)

    sweep = Sweep(
        ledger=ledger,
        budget=Budget(limit_usd=1.0),
        providers={"stub": provider},
        build_prompt=lambda case: f"formalize: {case.narrative}",
        parse_response=lambda text, case: __import__("planteo").Problem.from_json(_json.loads(text)),
        repeats=2,
    )
    cases = [Case("case-001", "optimization", "a narrative")]
    targets = [Target("stub", "stub-small")]

    first = sweep.run(cases, targets)
    assert first == 2
    assert len(provider.calls) == 2

    second = sweep.run(cases, targets)
    assert second == 0, "a resumed sweep repeated work that was already in the ledger"
    assert len(provider.calls) == 2
    assert len(ledger.records()) == 2


def test_a_corrupt_line_is_reported_with_its_position(ledger_path) -> None:
    ledger = Ledger(ledger_path)
    ledger.append(make_record())
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    with pytest.raises(LedgerError) as caught:
        ledger.records()
    assert ":2" in str(caught.value)


def test_total_cost_sums_the_ledger(ledger_path) -> None:
    ledger = Ledger(ledger_path)
    ledger.append(make_record(key=CallKey("a", "stub", "m", 0), cost_usd=0.10))
    ledger.append(make_record(key=CallKey("b", "stub", "m", 0), cost_usd=0.25))
    assert ledger.total_cost_usd == pytest.approx(0.35)
