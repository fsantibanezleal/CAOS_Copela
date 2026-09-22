"""Gates for R-007, R-008 and R-009.

These run against a real solver, because a property relation tested with a stub solver tests the
arithmetic of the check and not the thing it is for.
"""

from __future__ import annotations

import pytest

from copela.oracles import properties
from copela.oracles.properties import Solution
from copela.verdicts import Outcome

pytest.importorskip("pyomo.environ", reason="the solvers extra is not installed")

from copela.solvers.highs import SolverUnavailable, make_solver  # noqa: E402

solve = make_solver()


def _require_solver(problem) -> None:
    try:
        solve(problem)
    except SolverUnavailable as reason:
        pytest.skip(str(reason))


def test_objective_scaling_preserves_argmin(blend) -> None:
    """R-007: multiplying the objective by a positive constant cannot move the argmin."""
    _require_solver(blend)

    base = solve(blend)
    scaled = solve(properties.scale_objective(blend, factor=7.0))

    assert base.feasible and scaled.feasible
    for name in base.values:
        assert base.values[name] == pytest.approx(scaled.values[name], abs=1e-6)
    # The optimum itself scales, which is what distinguishes this from the redundant-constraint case.
    assert scaled.objective == pytest.approx(base.objective * 7.0, rel=1e-6)


def test_tightening_cannot_improve_the_optimum(blend) -> None:
    """R-008: demanding more cannot make a minimisation cheaper."""
    _require_solver(blend)

    base = solve(blend)
    tightened = solve(properties.tighten_first_bound(blend, factor=1.5))

    assert tightened.objective >= base.objective - 1e-6
    ok, detail = properties._cannot_improve(base, tightened)
    assert ok, detail


def test_unevaluable_relation_is_not_a_pass(blend) -> None:
    """R-009: a relation that could not be evaluated reports not-applicable, never pass."""

    def never_solves(problem):
        raise RuntimeError("the candidate did not solve")

    layer, outcomes = properties.evaluate(blend, never_solves)
    assert layer.outcome is Outcome.NOT_APPLICABLE
    assert layer.outcome is not Outcome.PASS
    assert outcomes == ()
    assert "did not solve" in layer.detail


def test_an_infeasible_candidate_is_not_applicable_rather_than_passing() -> None:
    def infeasible(problem):
        return Solution(feasible=False, objective=None, values={}, detail="infeasible")

    from tests.conftest import make_blend

    layer, _ = properties.evaluate(make_blend(), infeasible)
    assert layer.outcome is Outcome.NOT_APPLICABLE


def test_a_relation_that_cannot_apply_does_not_count_either() -> None:
    """A relation with nothing to transform reports not-applicable per relation."""
    from tests.conftest import make_blend

    problem = make_blend()

    def constant_solution(p):
        return Solution(feasible=True, objective=900.0, values={"x": 1.0}, detail="optimal")

    only_tightening = (properties.OPTIMIZATION_RELATIONS[2],)
    layer, outcomes = properties.evaluate(problem, constant_solution, only_tightening)
    assert len(outcomes) == 1
    assert outcomes[0].relation == "tightening"


def test_the_relations_actually_catch_a_broken_solver(blend) -> None:
    """The negative control: a solver that ignores the objective must be caught.

    Without this, the property layer could be decoration that never fails anything. The SDD names
    that as the kill criterion, so it is tested rather than assumed.
    """
    calls = {"n": 0}

    def drifting(problem):
        # Returns a different argmin on the second call, which objective scaling forbids.
        calls["n"] += 1
        return Solution(
            feasible=True,
            objective=900.0,
            values={"x_a": 0.0 if calls["n"] == 1 else 100.0, "x_b": 100.0},
            detail="optimal",
        )

    layer, outcomes = properties.evaluate(
        blend, drifting, (properties.OPTIMIZATION_RELATIONS[0],)
    )
    assert layer.outcome is Outcome.FAIL
    assert "moved" in layer.detail


def test_a_redundant_constraint_must_not_move_the_optimum(blend) -> None:
    _require_solver(blend)
    base = solve(blend)
    with_probe = solve(properties.add_redundant_constraint(blend))
    assert with_probe.objective == pytest.approx(base.objective, rel=1e-9)


def test_every_relation_states_what_it_guarantees() -> None:
    """A relation with no stated guarantee cannot be reviewed, so it is not allowed to exist."""
    for relation in properties.OPTIMIZATION_RELATIONS:
        assert relation.guarantee.strip(), f"{relation.name} does not say what it guarantees"
        assert relation.name
