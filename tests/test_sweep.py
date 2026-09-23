"""Gates for R-017, R-018 and R-020: the structural layer must be able to refute, and only then."""

from __future__ import annotations

import dataclasses
import json

import pytest

from copela import Budget, Case, Layer, Ledger, Outcome, StubProvider, Sweep, Target

pytest.importorskip("pyomo.environ", reason="the solvers extra is not installed")

from copela.solvers.highs import SolverUnavailable, make_solver  # noqa: E402


def _parse(text: str, case):
    from planteo import Problem

    return Problem.from_json(json.loads(text))


def _run(ledger_path, reference, candidate):
    """Run one case where the model returns `candidate` and the case carries `reference`."""
    solve = make_solver()
    try:
        solve(reference)
    except SolverUnavailable as reason:
        pytest.skip(str(reason))

    ledger = Ledger(ledger_path)
    sweep = Sweep(
        ledger=ledger,
        budget=Budget(limit_usd=1.0),
        providers={"stub": StubProvider(default=json.dumps(candidate.to_json()))},
        build_prompt=lambda case: "formalize this",
        parse_response=_parse,
        solve=solve,
        repeats=1,
    )
    sweep.run(
        [Case("c1", "optimization", reference.narrative.text, reference=reference)],
        [Target("stub", "stub-small")],
    )
    verdicts = ledger.records()[0].verdicts
    return {v["layer"]: v for v in verdicts}


def test_a_different_optimum_refutes_equivalence(ledger_path) -> None:
    """R-017.

    Two formalizations of the same case that solve to different optima are not the same model.
    That direction IS conclusive, and it is the only way this layer can ever fail a candidate.
    """
    from planteo import Comparator, Compare, Constant, Dimension, Ref, Sum

    from tests.conftest import make_blend

    TONNE = Dimension.of("t", mass=1)
    reference = make_blend()  # demand 100, optimum 900

    # Same shape, wrong demand: solves to 2250 instead of 900.
    candidate = dataclasses.replace(
        reference,
        relations=(
            Compare(
                Sum((Ref("x_a"), Ref("x_b"))),
                Comparator.GE,
                Constant(250.0, TONNE),
                name="meet_demand",
            ),
        ),
    )

    layers = _run(ledger_path, reference, candidate)
    structural = layers.get(Layer.STRUCTURAL.value)
    assert structural is not None
    assert structural["outcome"] == Outcome.FAIL.value, structural
    assert "different models" in structural["detail"]


def test_a_matching_optimum_does_not_prove_equivalence(ledger_path) -> None:
    """R-018.

    The asymmetry is the honest part. Compensating errors reach the right number, which is exactly
    the failure the anchor survey documents, so agreement can only ever refute, never confirm.
    """
    from planteo import Comparator, Compare, Dimension, Ref

    from tests.conftest import make_blend

    TONNE = Dimension.of("t", mass=1)
    reference = make_blend()

    # A different canonical form that still solves to 900: an extra redundant row.
    from planteo import Constant

    candidate = dataclasses.replace(
        reference,
        relations=reference.relations
        + (
            Compare(
                Ref("x_a"),
                Comparator.GE,
                Constant(0.0, TONNE),
                name="redundant",
            ),
        ),
    )

    layers = _run(ledger_path, reference, candidate)
    structural = layers.get(Layer.STRUCTURAL.value)
    assert structural is not None
    assert structural["outcome"] == Outcome.UNDECIDED.value, structural
    assert structural["outcome"] != Outcome.PASS.value
    assert "compensating errors" in structural["detail"]


def test_an_identical_model_proves_equivalence(ledger_path) -> None:
    """The one case where PASS is earned: the canonical forms are equal."""
    from tests.conftest import make_blend

    reference = make_blend()
    layers = _run(ledger_path, reference, make_blend())
    structural = layers.get(Layer.STRUCTURAL.value)
    assert structural["outcome"] == Outcome.PASS.value, structural


def test_a_feasibility_difference_also_refutes(ledger_path) -> None:
    """An infeasible candidate against a feasible reference is not the same model."""
    from planteo import Comparator, Compare, Constant, Dimension, Ref

    from tests.conftest import make_blend

    TONNE = Dimension.of("t", mass=1)
    reference = make_blend()
    impossible = dataclasses.replace(
        reference,
        relations=reference.relations
        + (
            Compare(Ref("x_a"), Comparator.LE, Constant(1.0, TONNE), name="a_tiny"),
            Compare(Ref("x_b"), Comparator.LE, Constant(1.0, TONNE), name="b_tiny"),
        ),
    )
    layers = _run(ledger_path, reference, impossible)
    structural = layers.get(Layer.STRUCTURAL.value)
    assert structural["outcome"] == Outcome.FAIL.value, structural
    assert "not" in structural["detail"]


def test_a_sense_flipped_rewrite_is_not_refuted(ledger_path) -> None:
    """R-020.

    Maximising the negative of the cost is the reference's model written the other way round. Its
    optimum is -900 where the reference's is 900, and comparing those raw values called it "a
    different optimum": a style rewrite refuted as a wrong model. Read in the minimising sense the
    two agree, and the layer says UNDECIDED, which is all an agreeing answer can ever earn.
    """
    from planteo import DIMENSIONLESS, Constant, Objective, Product, Sense

    from tests.conftest import make_blend

    reference = make_blend()
    original = reference.objectives[0]
    flipped = dataclasses.replace(
        reference,
        objectives=(
            Objective(
                Sense.MAXIMISE,
                Product((Constant(-1.0, DIMENSIONLESS), original.expression)),
                name=original.name,
            ),
        ),
    )

    layers = _run(ledger_path, reference, flipped)
    structural = layers.get(Layer.STRUCTURAL.value)
    assert structural is not None
    assert structural["outcome"] == Outcome.UNDECIDED.value, structural
    assert structural["outcome"] != Outcome.FAIL.value
