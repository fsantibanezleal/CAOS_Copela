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

    # Do not let the interface load a solution it may not have. An infeasible model is an ordinary
    # outcome here (the corpus contains deliberately contradictory cases, because noticing that a
    # problem has no answer is part of what is being measured), and an interface that raises on it
    # would turn the correct result into a harness error.
    results = _solve_without_loading(solver, model)
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

    # The solution exists but was not loaded, because loading was suppressed above.
    _load_solution(solver, model)

    values = {
        variable.name: float(pyo.value(variable))
        for variable in model.component_data_objects(pyo.Var, active=True)
    }
    objectives = list(model.component_data_objects(pyo.Objective, active=True))
    objective = float(pyo.value(objectives[0])) if objectives else None

    return Solution(
        feasible=True, objective=objective, values=values, detail=condition
    )


def _solve_without_loading(solver, model):
    """Solve without loading a solution, across the two Pyomo solver interfaces.

    The appsi interfaces take ``config.load_solution``; the legacy ones take a ``load_solutions``
    keyword. Neither is universal, so both are tried and the plain call is the fallback. The plain
    call is the one that raises on an infeasible model, so it is last.
    """
    import inspect

    # The keyword comes FIRST. Pyomo's appsi legacy wrapper copies its own ``load_solutions``
    # argument over ``config.load_solution`` on every call, so setting the config beforehand is
    # silently discarded. That is the kind of thing only a failing infeasible case reveals.
    try:
        parameters = inspect.signature(solver.solve).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "load_solutions" in parameters:
        return solver.solve(model, load_solutions=False)

    config = getattr(solver, "config", None)
    if config is not None and hasattr(config, "load_solution"):
        previous = config.load_solution
        config.load_solution = False
        try:
            return solver.solve(model)
        finally:
            config.load_solution = previous

    return solver.solve(model)


def _load_solution(solver, model) -> None:
    """Load a solution that was deliberately not loaded during the solve."""
    try:
        solver.load_vars()
        return
    except (AttributeError, RuntimeError):
        pass
    try:
        model.solutions.load_from(solver._last_results_object)  # noqa: SLF001, no public path
    except Exception:  # noqa: BLE001, a failed load is reported by the caller's empty values
        pass


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
