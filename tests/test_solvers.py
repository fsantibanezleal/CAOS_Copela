"""Gate for R-013: an infeasible model is a result, not an error."""

from __future__ import annotations

import pytest

pytest.importorskip("pyomo.environ", reason="the solvers extra is not installed")

from copela.solvers.highs import SolverUnavailable, make_solver  # noqa: E402

solve = make_solver()


def _skip_without_solver(problem) -> None:
    try:
        solve(problem)
    except SolverUnavailable as reason:
        pytest.skip(str(reason))


def test_an_infeasible_model_returns_a_result_rather_than_raising() -> None:
    """R-013.

    Pyomo's appsi interface raises when asked to load a solution that does not exist, and it
    overwrites config.load_solution from its own keyword on every call, so suppressing the load
    through the config alone is silently discarded. The corpus contains deliberately contradictory
    cases, because noticing that a problem has no answer is part of what is being measured, so an
    infeasible model has to come back as a verdict.
    """
    import dataclasses

    from planteo import Comparator, Compare, Constant, Dimension, Ref
    from tests.conftest import make_blend

    TONNE = Dimension.of("t", mass=1)
    problem = make_blend()
    contradiction = Compare(
        left=Ref("x_a"),
        comparator=Comparator.LE,
        right=Constant(1.0, TONNE),
        name="x_a_tiny",
    )
    also = Compare(
        left=Ref("x_b"),
        comparator=Comparator.LE,
        right=Constant(1.0, TONNE),
        name="x_b_tiny",
    )
    # Demand is 100 tonnes and neither source may exceed 1 tonne.
    impossible = dataclasses.replace(
        problem, relations=problem.relations + (contradiction, also)
    )

    _skip_without_solver(make_blend())

    solution = solve(impossible)
    assert solution.feasible is False
    assert solution.objective is None
    assert "infeasible" in solution.detail.lower()


def test_a_feasible_model_still_loads_its_values() -> None:
    """Suppressing the load must not break the ordinary path."""
    from tests.conftest import make_blend

    problem = make_blend()
    _skip_without_solver(problem)

    solution = solve(problem)
    assert solution.feasible
    assert solution.objective == pytest.approx(900.0)
    assert solution.values, "values were not loaded after a successful solve"
    assert solution.values["x_b"] == pytest.approx(100.0)


def test_an_unavailable_solver_is_distinct_from_an_infeasible_model() -> None:
    from tests.conftest import make_blend

    with pytest.raises(SolverUnavailable):
        from copela.solvers.highs import solve as solve_with

        solve_with(make_blend(), solver_name="a_solver_that_does_not_exist")
