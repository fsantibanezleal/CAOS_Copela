"""Solving a planteo Problem, through Pyomo, with HiGHS by default.

This is the executable layer and the engine the property relations run on. It is deliberately thin:
`planteo` owns the translation, so nothing here reinterprets a model, and a bug in this file can
make a run fail but cannot make it silently mean something else.

HiGHS is the default because it is MIT-licensed, actively developed, and the usual recommendation
for LP and ordinary MILP. The solver is a parameter, so a case that needs CP-SAT or SCIP changes one
string rather than a code path.
"""

from __future__ import annotations

from planteo import Problem

from ..oracles.properties import Solution

DEFAULT_SOLVER = "appsi_highs"


class SolverUnavailable(RuntimeError):
    """The requested solver is not installed. Distinct from a model that failed to solve."""


def solve(
    problem: Problem,
    solver_name: str = DEFAULT_SOLVER,
    time_limit_s: float | None = 60.0,
) -> Solution:
    """Emit the problem and solve it.

    Returns a ``Solution`` for anything the solver reached a verdict on, including infeasible.
    Raises only when the machinery itself is unavailable or the problem cannot be emitted, because
    those are different from a model that legitimately has no solution, and collapsing them would
    make an infeasible case look like a broken harness.
    """
    try:
        import pyomo.environ as pyo
    except ImportError as error:
        raise SolverUnavailable(
            "solving needs Pyomo: pip install 'copela[solvers]'"
        ) from error

    from planteo.emit import pyomo as emit

    model = emit.build_model(problem)

    solver = pyo.SolverFactory(solver_name)
    if not solver.available(exception_flag=False):
        raise SolverUnavailable(
            f"{solver_name!r} is not available in this environment. "
            "A sweep that silently skipped it would report a rate it did not measure"
        )

    if time_limit_s is not None:
        _apply_time_limit(solver, solver_name, time_limit_s)

    results = solver.solve(model)
    condition = str(results.solver.termination_condition)

    if condition in {"infeasible", "infeasibleOrUnbounded"}:
        return Solution(feasible=False, objective=None, values={}, detail=condition)
    if condition == "unbounded":
        return Solution(
            feasible=True, objective=None, values={}, detail="unbounded"
        )
    if condition not in {"optimal", "feasible", "locallyOptimal", "globallyOptimal"}:
        return Solution(
            feasible=False,
            objective=None,
            values={},
            detail=f"solver stopped: {condition}",
        )

    values = {
        variable.name: float(pyo.value(variable))
        for variable in model.component_data_objects(pyo.Var, active=True)
    }
    objectives = list(model.component_data_objects(pyo.Objective, active=True))
    objective = float(pyo.value(objectives[0])) if objectives else None

    return Solution(
        feasible=True, objective=objective, values=values, detail=condition
    )


def _apply_time_limit(solver, solver_name: str, seconds: float) -> None:
    """Set a time limit. The option name differs per solver, so a failure here is not fatal.

    A sweep without a time limit is how one pathological case consumes an afternoon, but a solver
    whose option name we guessed wrong should still run.
    """
    for attempt in ("time_limit", "timelimit", "sec", "TimeLimit"):
        try:
            solver.options[attempt] = seconds
            return
        except Exception:  # noqa: BLE001, option tables vary and none of this is worth failing on
            continue


def make_solver(solver_name: str = DEFAULT_SOLVER, time_limit_s: float | None = 60.0):
    """Return a ``Solve`` callable bound to one solver, for the property relations."""

    def _solve(problem: Problem) -> Solution:
        return solve(problem, solver_name=solver_name, time_limit_s=time_limit_s)

    return _solve
