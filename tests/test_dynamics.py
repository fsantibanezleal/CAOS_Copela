"""The dynamics layers, R-037 to R-040.

The reference is a mixing tank with a closed-form answer: 100 L of brine hold 2 kg of salt, brine at
0.4 kg/L flows in at 5 L/min and drains at the same rate, so x(t) = 40 - 38 exp(-t/20) and the salt
after 20 minutes is 40 - 38/e. Every stated number cites the words it came from.
"""

from __future__ import annotations

import dataclasses
import json
import math
from fractions import Fraction

import pytest

pytest.importorskip("scipy.integrate", reason="the dynamics layers integrate with SciPy")

from planteo import (  # noqa: E402
    Comparator,
    Compare,
    Constant,
    Dimension,
    Domain,
    Family,
    Narrative,
    Objective,
    Power,
    Problem,
    Product,
    Quantity,
    Query,
    Rate,
    Ref,
    Role,
    Sense,
    Span,
    Sum,
)
from planteo.expressions import BigSum  # noqa: E402

from copela import Budget, Case, Ledger, Outcome, StubProvider, Sweep, Target  # noqa: E402
from copela.oracles import dynamics  # noqa: E402

KG = Dimension.of("kg", mass=1)
LITRE = Dimension.of("L", length=3)
MINUTE = Dimension.of("min", time=1)
CONCENTRATION = Dimension.of("kg/L", mass=1, length=-3)
FLOW = Dimension.of("L/min", length=3, time=-1)
KG_PER_MIN = Dimension.of("kg/min", mass=1, time=-1)
NONE = Dimension.dimensionless()

TEXT = Narrative(
    "A tank holds 100 L of brine containing 2 kg of salt. Brine with 0.4 kg of salt per litre flows "
    "in at 5 L/min, and the mixed solution drains at the same rate. How many kilograms of salt are in "
    "the tank after 20 minutes?"
)
ANALYTIC = 40 - 38 * math.exp(-1)

QUANTITIES = (
    Quantity("t", Role.INDEPENDENT, MINUTE, lower=0.0, upper=30.0),
    Quantity("x", Role.STATE, KG, value=2.0, span=Span.find(TEXT, "2 kg")),
    Quantity("V", Role.PARAMETER, LITRE, value=100.0, span=Span.find(TEXT, "100 L")),
    Quantity("c_in", Role.PARAMETER, CONCENTRATION, value=0.4, span=Span.find(TEXT, "0.4 kg")),
    Quantity("q", Role.PARAMETER, FLOW, value=5.0, span=Span.find(TEXT, "5 L/min")),
)
INFLOW = Product((Ref("c_in"), Ref("q")))


def outflow(coefficient: float = -1.0) -> Product:
    return Product((Constant(coefficient, NONE), Ref("x"), Power(Ref("V"), Fraction(-1)), Ref("q")))


def tank(rate=None, **overrides) -> Problem:
    fields = dict(
        narrative=TEXT,
        family=Family.DYNAMICS,
        quantities=QUANTITIES,
        relations=(Rate("x", "t", rate if rate is not None else Sum((INFLOW, outflow()))),),
        queries=(Query(Ref("x"), 20.0, name="salt_after_20_min"),),
    )
    fields.update(overrides)
    return Problem(**fields)  # type: ignore[arg-type]


def run(problem: Problem) -> dynamics.Simulation:
    result, simulation = dynamics.executable(problem)
    assert result.outcome is Outcome.PASS, result.detail
    assert simulation is not None
    return simulation


def test_the_reference_integrates_to_its_closed_form() -> None:
    """R-037: the executable layer passes a system that reaches every query with a finite value."""
    assert run(tank()).value("salt_after_20_min", 20.0) == pytest.approx(ANALYTIC, rel=1e-7)  # type: ignore[misc]


def test_a_system_that_diverges_before_the_asked_time_does_not_run() -> None:
    """R-037: x' = x^2 from 2 kg runs off to infinity at half a minute, so there is no salt at 20.
    LSODA alone retries the overflowing step forever; the oracle stops it."""
    per_kg_min = Dimension.of("1/(kg min)", mass=-1, time=-1)
    result, simulation = dynamics.executable(tank(Product((Ref("x"), Ref("x"), Constant(1.0, per_kg_min)))))
    assert result.outcome is Outcome.FAIL and simulation is None, result.detail
    assert "diverges" in result.detail


def test_what_the_instrument_cannot_compute_is_unmeasured(monkeypatch) -> None:
    """R-040: an indexed sum has no scalar value, and an integration that outruns its evaluation
    budget has not been shown wrong. Both are the instrument's limit, not the model's."""
    items = Quantity("items", Role.SET, NONE, domain=Domain.SET)
    indexed = tank(BigSum("i", "items", INFLOW), quantities=(*QUANTITIES, items))
    result, simulation = dynamics.executable(indexed)
    assert result.outcome is Outcome.NOT_APPLICABLE and simulation is None, result.detail
    assert "not measured" in result.detail

    monkeypatch.setattr(dynamics, "BUDGET", 5)
    result, simulation = dynamics.executable(tank())
    assert result.outcome is Outcome.NOT_APPLICABLE and "evaluations" in result.detail, result.detail


def test_equal_forms_pass_and_a_different_outflow_is_refuted() -> None:
    """R-038: the canonical form is blind to order; a doubled outflow follows another trajectory."""
    reference = tank()
    reference_run = run(reference)

    reordered = tank(quantities=tuple(reversed(QUANTITIES)))
    assert dynamics.structural(reordered, reference, run(reordered), reference_run).outcome is Outcome.PASS

    doubled = tank(Sum((INFLOW, outflow(-2.0))))
    result = dynamics.structural(doubled, reference, run(doubled), reference_run)
    assert result.outcome is Outcome.FAIL and "different models" in result.detail, result.detail


def test_the_right_number_at_the_asked_time_is_not_enough() -> None:
    """R-038: a tank that holds the asked answer from the start is right at 20 minutes and wrong at
    every other time. Execution accuracy would count it; the trajectory refutes it."""
    reference = tank()
    reference_run = run(reference)
    held = tank(
        Constant(0.0, KG_PER_MIN),
        quantities=tuple(dataclasses.replace(q, value=ANALYTIC) if q.name == "x" else q for q in QUANTITIES),
    )
    held_run = run(held)
    assert held_run.value("salt_after_20_min", 20.0) == pytest.approx(ANALYTIC, rel=1e-7)  # type: ignore[misc]
    result = dynamics.structural(held, reference, held_run, reference_run)
    assert result.outcome is Outcome.FAIL, result.detail


def test_the_same_trajectory_in_another_form_decides_nothing() -> None:
    """R-038: naming the inflow as a derived quantity changes the form, not the system."""
    reference = tank()
    derived = tank(
        quantities=(*QUANTITIES, Quantity("inflow", Role.DERIVED, KG_PER_MIN)),
        relations=(
            Compare(Ref("inflow"), Comparator.EQ, INFLOW),
            Rate("x", "t", Sum((Ref("inflow"), outflow()))),
        ),
    )
    result = dynamics.structural(derived, reference, run(derived), run(reference))
    assert result.outcome is Outcome.UNDECIDED, result.detail


def test_a_candidate_that_responds_the_wrong_way_to_a_stated_number_is_refuted() -> None:
    """R-039: raising the stated concentration raises the reference's salt. A candidate that divides
    by it lowers its own, and is refuted whatever its value at the asked time."""
    reference = tank()
    reference_run = run(reference)
    assert dynamics.provenance(reference, reference, reference_run, reference_run).outcome is Outcome.PASS

    # 0.16 kg^2/L^2 over c_in is 0.4 kg/L at the stated value: the same number, the opposite response.
    squared = Dimension.of("kg2/L2", mass=2, length=-6)
    inverted = tank(
        Sum((Product((Constant(0.16, squared), Power(Ref("c_in"), Fraction(-1)), Ref("q"))), outflow()))
    )
    inverted_run = run(inverted)
    assert inverted_run.value("salt_after_20_min", 20.0) == pytest.approx(ANALYTIC, rel=1e-7)  # type: ignore[misc]
    result = dynamics.provenance(inverted, reference, inverted_run, reference_run)
    assert result.outcome is Outcome.FAIL and "0.4 kg" in result.detail, result.detail


def test_without_a_number_cited_by_both_the_relation_does_not_apply() -> None:
    """R-039: the relation is derived from shared provenance; with none it abstains and says so."""
    reference = tank()
    uncited = tank(quantities=tuple(dataclasses.replace(q, span=None) for q in QUANTITIES))
    result = dynamics.provenance(uncited, reference, run(uncited), run(reference))
    assert result.outcome is Outcome.NOT_APPLICABLE, result.detail


def _sweep_one(ledger_path, reply: Problem, reference: Problem):
    ledger = Ledger(ledger_path)
    Sweep(
        ledger=ledger,
        budget=Budget(limit_usd=1.0),
        providers={"stub": StubProvider(default=json.dumps(reply.to_json()))},
        build_prompt=lambda case: case.narrative,
        parse_response=lambda text, case: Problem.from_json(json.loads(text)),
        repeats=1,
    ).run([Case("tank", "dynamics", TEXT.text, reference=reference)], [Target("stub", "stub-small")])
    (record,) = Ledger(ledger_path).records()
    return record


def test_a_sweep_scores_a_dynamics_reply_with_the_dynamics_layers(ledger_path) -> None:
    """R-037 to R-039 through the sweep, with no optimization solver injected."""
    record = _sweep_one(ledger_path, tank(), tank())
    assert [(v["layer"], v["outcome"]) for v in record.verdicts] == [
        ("executable", "pass"),
        ("structural", "pass"),
        ("property", "pass"),
    ], record.verdicts


def test_a_reply_of_the_wrong_family_does_not_run(ledger_path) -> None:
    """An optimization problem as the answer to a dynamics case runs as nothing the case asked."""
    wrong = Problem(
        narrative=TEXT,
        family=Family.OPTIMIZATION,
        quantities=(Quantity("u", Role.VARIABLE, KG, lower=0.0), *QUANTITIES[2:]),
        objectives=(Objective(Sense.MINIMISE, Ref("u")),),
    )
    record = _sweep_one(ledger_path, wrong, tank())
    assert [v["outcome"] for v in record.verdicts] == ["fail"], record.verdicts
    assert "family is optimization" in record.verdicts[0]["detail"]


def _restated(**changes) -> tuple[Quantity, ...]:
    """The tank's quantities with some restated: name to (unit symbol, value)."""
    out = []
    for q in QUANTITIES:
        if q.name in changes:
            symbol, value = changes[q.name]
            dimension = Dimension(q.dimension.exponents, symbol=symbol)
            if q.role is Role.INDEPENDENT:
                q = dataclasses.replace(q, dimension=dimension, upper=value)
            else:
                q = dataclasses.replace(q, dimension=dimension, value=value)
        out.append(q)
    return tuple(out)


def test_a_candidate_in_other_units_is_compared_in_si() -> None:
    """R-042: counting time in hours, or salt in grams, is the same system. Both are paired with
    the reference's question and agree along the whole range, so the structural layer cannot refute
    them and the property layer passes them."""
    reference = tank()
    reference_run = run(reference)
    in_hours = tank(
        quantities=_restated(t=("h", 0.5), q=("L/h", 300.0)),
        queries=(Query(Ref("x"), 1 / 3, name="salt_after_20_min"),),
    )
    in_grams = tank(quantities=_restated(x=("g", 2000.0), c_in=("g/L", 400.0)))
    for candidate in (in_hours, in_grams):
        candidate_run = run(candidate)
        result = dynamics.structural(candidate, reference, candidate_run, reference_run)
        assert result.outcome is Outcome.UNDECIDED and "agree" in result.detail, result.detail
        result = dynamics.provenance(candidate, reference, candidate_run, reference_run)
        assert result.outcome is Outcome.PASS, result.detail


def test_a_conversion_left_undone_is_refuted_in_si() -> None:
    """R-042: hours on the clock with the flow still at 5 per hour is a tank sixty times slower."""
    reference = tank()
    slow = tank(
        quantities=_restated(t=("h", 0.5), q=("L/h", 5.0)),
        queries=(Query(Ref("x"), 1 / 3, name="salt_after_20_min"),),
    )
    result = dynamics.structural(slow, reference, run(slow), run(reference))
    assert result.outcome is Outcome.FAIL and "in the reference's units" in result.detail, result.detail


def test_a_clock_that_cannot_be_read_is_compared_raw() -> None:
    """R-042: a symbol outside the vocabulary never converts; the raw times are compared as before,
    so a question asked at 20 of an unknown unit is paired with the reference's 20 minutes."""
    reference = tank()
    # Another form (the inflow named), so the verdict comes from pairing the trajectories rather than
    # from the canonical form, which ignores unit symbols.
    unknown = tank(
        quantities=(*_restated(t=("ticks", 30.0)), Quantity("inflow", Role.DERIVED, KG_PER_MIN)),
        relations=(
            Compare(Ref("inflow"), Comparator.EQ, INFLOW),
            Rate("x", "t", Sum((Ref("inflow"), outflow()))),
        ),
    )
    result = dynamics.structural(unknown, reference, run(unknown), run(reference))
    assert result.outcome is Outcome.UNDECIDED and "agree" in result.detail, result.detail
    assert dynamics.provenance(unknown, reference, run(unknown), run(reference)).outcome is Outcome.PASS
