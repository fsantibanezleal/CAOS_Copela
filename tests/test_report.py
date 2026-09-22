"""Gates for R-001, R-002, R-010 and R-011."""

from __future__ import annotations

import json

import pytest

from copela import (
    JUDGE_LABEL,
    Budget,
    CallKey,
    CandidateVerdict,
    Case,
    Layer,
    LayerResult,
    Ledger,
    Outcome,
    Rate,
    Record,
    StubProvider,
    Sweep,
    Target,
    build,
)
from copela.report import Cell


def test_layers_are_never_combined() -> None:
    """R-001: there is no combined score, on the verdict, the cell or the report.

    A single number would let a high 'it ran' rate conceal a low 'it was right' rate, which is the
    distance the whole harness exists to show. This test fails if anyone adds one.
    """
    verdict = CandidateVerdict(
        (
            LayerResult(Layer.EXECUTABLE, Outcome.PASS),
            LayerResult(Layer.STRUCTURAL, Outcome.UNDECIDED),
            LayerResult(Layer.PROPERTY, Outcome.PASS),
        )
    )
    forbidden = {"score", "total", "overall", "combined", "aggregate_score"}
    for owner in (verdict, Cell("p", "m", "optimization", Rate(1, 1), Rate(1, 1))):
        present = forbidden & set(dir(owner))
        assert not present, f"{type(owner).__name__} exposes a combined score: {present}"

    # The two rates stay addressable and separate.
    assert verdict.ran is True
    assert verdict.faithful is True


def test_judge_verdict_is_labelled() -> None:
    """R-002: a judge verdict carries its label, and cannot be built without one."""
    labelled = LayerResult.judge(Outcome.PASS, "two-judge consensus")
    assert labelled.label == JUDGE_LABEL
    assert "not an equivalence oracle" in labelled.label
    assert "label" in labelled.to_json()

    with pytest.raises(ValueError) as caught:
        LayerResult(Layer.JUDGE, Outcome.PASS)
    assert "label" in str(caught.value)


def test_the_judge_layer_never_counts_towards_faithful() -> None:
    """A judge pass alone does not make a candidate faithful."""
    only_judged = CandidateVerdict(
        (
            LayerResult(Layer.EXECUTABLE, Outcome.PASS),
            LayerResult.judge(Outcome.PASS),
        )
    )
    assert only_judged.ran is True
    assert only_judged.faithful is False


def test_rate_carries_an_interval() -> None:
    """R-010: a rate reports an interval over n, and a single run is not a result."""
    rate = Rate(passed=7, total=10)
    low, high = rate.interval
    assert low < rate.value < high
    assert "n=10" in rate.describe()
    assert "interval_low" in rate.to_json()

    # Wilson behaves at the boundaries, where the normal approximation would claim certainty.
    perfect = Rate(5, 5)
    assert perfect.value == 1.0
    assert perfect.interval[0] < 1.0, "5 of 5 must not be reported as certainly 1.0"

    none_passed = Rate(0, 5)
    assert none_passed.interval[1] > 0.0, "0 of 5 must not be reported as certainly 0.0"


def test_a_single_run_still_reports_its_uncertainty() -> None:
    single = Rate(1, 1)
    low, high = single.interval
    assert low < 0.5, "one observation cannot establish a rate"
    assert high == pytest.approx(1.0)


def test_the_gap_is_the_headline(ledger_path) -> None:
    ledger = Ledger(ledger_path)
    for repeat, (ran, faithful) in enumerate(
        [(True, True), (True, False), (True, False), (False, False)]
    ):
        verdicts = [LayerResult(Layer.EXECUTABLE, Outcome.PASS if ran else Outcome.FAIL)]
        if ran:
            verdicts.append(
                LayerResult(
                    Layer.PROPERTY, Outcome.PASS if faithful else Outcome.FAIL
                )
            )
        ledger.append(
            Record(
                key=CallKey("case-001", "stub", "stub-small", repeat),
                family="optimization",
                model_version="v",
                temperature=0.0,
                seed=1,
                provider_fingerprint="f",
                prompt_digest="p",
                response_digest="r",
                latency_ms=1.0,
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.0,
                verdicts=[v.to_json() for v in verdicts],
            )
        )

    report = build(ledger)
    assert len(report.cells) == 1
    cell = report.cells[0]
    assert cell.ran.passed == 3 and cell.ran.total == 4
    assert cell.faithful.passed == 1 and cell.faithful.total == 4
    assert cell.gap == pytest.approx(0.5)
    assert "gap" in report.to_text()
    assert "no combined score" in report.to_json()["note"]


def test_a_failed_run_stays_in_the_denominator(ledger_path) -> None:
    """Dropping failures would inflate the faithful rate by shrinking its denominator."""
    ledger = Ledger(ledger_path)
    ledger.append(
        Record(
            key=CallKey("c", "stub", "m", 0),
            family="optimization",
            model_version="v",
            temperature=0.0,
            seed=1,
            provider_fingerprint="f",
            prompt_digest="p",
            response_digest="",
            latency_ms=0.0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            verdicts=[LayerResult(Layer.EXECUTABLE, Outcome.FAIL, "call failed").to_json()],
            error="boom",
        )
    )
    cell = build(ledger).cells[0]
    assert cell.ran.total == 1 and cell.ran.passed == 0
    assert cell.faithful.total == 1 and cell.faithful.passed == 0


def test_unparseable_response_is_a_recorded_failure(ledger_path) -> None:
    """R-011: a response that does not parse is an executable failure, and the run is kept."""
    provider = StubProvider(default="I think the answer is about 900 dollars.")
    ledger = Ledger(ledger_path)

    def parse(text: str, case):
        from planteo import Problem

        return Problem.from_json(json.loads(text))

    sweep = Sweep(
        ledger=ledger,
        budget=Budget(limit_usd=1.0),
        providers={"stub": provider},
        build_prompt=lambda case: "formalize this",
        parse_response=parse,
        repeats=1,
    )
    made = sweep.run([Case("c1", "optimization", "narrative")], [Target("stub", "stub-small")])

    assert made == 1
    records = ledger.records()
    assert len(records) == 1, "the run was discarded instead of recorded"
    assert records[0].error
    verdicts = records[0].verdicts
    assert verdicts[0]["layer"] == "executable"
    assert verdicts[0]["outcome"] == "fail"
    assert "did not parse" in str(verdicts[0]["detail"])


def test_a_provider_failure_is_recorded_rather_than_raised(ledger_path) -> None:
    provider = StubProvider(default="{}", fail_on={"stub-small"})
    ledger = Ledger(ledger_path)
    sweep = Sweep(
        ledger=ledger,
        budget=Budget(limit_usd=1.0),
        providers={"stub": provider},
        build_prompt=lambda case: "formalize this",
        parse_response=lambda text, case: None,  # type: ignore[return-value]
        repeats=1,
    )
    sweep.run([Case("c1", "optimization", "n")], [Target("stub", "stub-small")])
    records = ledger.records()
    assert len(records) == 1
    assert "stub configured to fail" in records[0].error


def test_a_gap_with_nothing_running_is_undefined_not_zero(ledger_path) -> None:
    """R-016: a model that failed every call has an UNDEFINED gap, never +0.000.

    Measured on a real sweep: a local model failed all ten calls and the report read
    "gap +0.000", which says "no gap" and means "no measurement". Confusing those two is the exact
    failure this product exists to expose, so making it here would be unforgivable.
    """
    import math

    ledger = Ledger(ledger_path)
    for repeat in range(4):
        ledger.append(
            Record(
                key=CallKey("c", "stub", "m", repeat),
                family="optimization",
                model_version="v",
                temperature=0.0,
                seed=1,
                provider_fingerprint="f",
                prompt_digest="p",
                response_digest="r",
                latency_ms=1.0,
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.0,
                verdicts=[LayerResult(Layer.EXECUTABLE, Outcome.FAIL, "nope").to_json()],
            )
        )

    cell = build(ledger).cells[0]
    assert cell.ran.passed == 0
    assert cell.gap_is_defined is False
    assert math.isnan(cell.gap)
    assert "UNDEFINED" in cell.describe()
    assert build(ledger).to_json()["cells"][0]["gap"] is None
    assert "UNDEFINED" in build(ledger).to_text()


def test_an_unmeasurable_run_leaves_the_rates_rather_than_counting_against_the_model(
    ledger_path,
) -> None:
    """R-019: a call the harness could not measure is excluded from both rates.

    Measured on a real sweep: a model produced a formalization the chosen linear solver could not
    express. Recording that as a model failure blames the subject for the instrument, which is the
    exact error this product exists to expose.
    """
    ledger = Ledger(ledger_path)

    def add(repeat: int, outcome: Outcome, detail: str = "") -> None:
        ledger.append(
            Record(
                key=CallKey("c", "stub", "m", repeat),
                family="optimization",
                model_version="v",
                temperature=0.0,
                seed=1,
                provider_fingerprint="f",
                prompt_digest="p",
                response_digest="r",
                latency_ms=1.0,
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.0,
                verdicts=[LayerResult(Layer.EXECUTABLE, outcome, detail).to_json()],
            )
        )

    add(0, Outcome.PASS)
    add(1, Outcome.FAIL)
    add(2, Outcome.NOT_APPLICABLE, "not measured: the solver cannot express this model")

    cell = build(ledger).cells[0]
    assert cell.ran.total == 2, "the unmeasurable run stayed in the denominator"
    assert cell.ran.passed == 1
    assert cell.unmeasured == 1
    assert "1 unmeasured" in cell.describe()
    assert build(ledger).to_json()["cells"][0]["unmeasured"] == 1
