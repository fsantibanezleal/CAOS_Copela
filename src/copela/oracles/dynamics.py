"""The dynamics family's layers: it integrates, it follows the system described, and it responds to
the statement's numbers the way the described system does.

A dynamics candidate is a system of ODEs with queries (planteo's dynamics family). The layers mirror
the optimization family's, with the answer being a trajectory rather than an optimum:

**Executable.** The system integrates (SciPy's LSODA, which switches between stiff and non-stiff
methods) to every query time with finite values.

**Structural.** Equal canonical forms prove equivalence. Otherwise every query the candidate shares
with the reference (asked at the same time, of the same dimension) is compared **along the whole
shared range**, not only at the asked time: two formalizations of one case cannot follow two
trajectories, so a difference anywhere refutes. A single number at the asked time is what execution
accuracy compares, and compensating errors reach it; agreement along the whole range still decides
nothing, for the same reason as an equal optimum.

**Property, through provenance.** Every quantity a statement's number produced cites the words it
came from. For each number cited by the reference and by the candidate alike, both are raised by the
same small factor and the queries' responses compared: a candidate whose answer moves the other way
when the statement's inflow is raised is not the system described, whatever its value at the asked
time. The relation is derived from the reference, not authored per case.

Units are the documented limit. Values are compared in each document's own units, so a candidate that
counts time in hours where the reference counts minutes asks at a different time and is not compared,
and one that reports grams where the reference reports kilograms is refuted. The corpus's statements
state the units they ask for.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from dataclasses import dataclass

from planteo import NotEvaluable, Problem, Role, compare, system

from ..verdicts import Layer, LayerResult, Outcome

RTOL, ATOL = 1e-9, 1e-12
#: Relative agreement between two trajectories, far above the integrator's error.
AGREE = 1e-5
#: Points on the shared range at which queries are compared, plus the asked times.
GRID = 61
#: The factor a cited number is raised by in the provenance relation.
NUDGE = 1.05
#: A response smaller than this, relative to the query's scale, has no sign worth comparing.
QUIET = 1e-7
#: Right-hand-side evaluations one integration may spend. The corpus's references need a few hundred;
#: an integration that needs more than this is stopped and reported as not measured, because the
#: instrument gave up, not because the model was shown wrong.
BUDGET = 100_000


class _Diverged(ArithmeticError):
    """The rate of change stopped being a finite number."""


class _OverBudget(RuntimeError):
    """The integration spent its evaluation budget before reaching the last query."""


@dataclass(frozen=True)
class Simulation:
    ok: bool
    detail: str
    t_span: tuple[float, float] = (0.0, 0.0)
    #: Query name to (the time it asks at, its dimension's exponents).
    asks: dict[str, tuple[float, tuple]] = dataclasses.field(default_factory=dict)
    #: A query's value at any time in the range.
    value: Callable[[str, float], float] | None = None


def simulate(problem: Problem) -> Simulation:
    """Integrate a valid dynamics problem over its range. Raises NotEvaluable for a construct the
    evaluator cannot compute, which the caller reports as unmeasured."""
    from scipy.integrate import solve_ivp

    built = system(problem)
    scope = problem.scope
    asks = {q.name: (q.at, tuple(q.dimension(scope).exponents)) for q in problem.queries}
    spent = [0]

    def rhs(t: float, y) -> list[float]:
        # LSODA does not stop on its own when a state overflows: it retries the step forever at the
        # last finite value. A state that runs off to infinity before the asked time has no answer
        # there, so the model fails; a finite system that needs an unbounded number of steps is the
        # instrument's limit, so the model is not measured.
        spent[0] += 1
        if spent[0] > BUDGET:
            raise _OverBudget(t)
        # A state that is not finite makes a rate that is not, so the rate is the one check.
        rates = built.rhs(t, y)
        if not all(math.isfinite(v) for v in rates):
            raise _Diverged(f"the rate of change is not finite at t = {t:.6g}")
        return rates

    try:
        solution = solve_ivp(
            rhs, built.t_span, list(built.y0), method="LSODA", dense_output=True, rtol=RTOL, atol=ATOL
        )
    except NotEvaluable:
        raise
    except _OverBudget as stopped:
        raise NotEvaluable(
            f"the integration spent {BUDGET} evaluations of the right-hand side and stopped at "
            f"t = {stopped.args[0]:.6g}, before the last query"
        ) from None
    except _Diverged as failure:
        return Simulation(False, f"the system diverges: {failure}, before the query it must answer")
    except (ArithmeticError, OverflowError, ValueError) as failure:
        return Simulation(False, f"the integration failed: {failure}")
    if not solution.success:
        return Simulation(False, f"the integration failed: {solution.message}")
    last = max(at for at, _ in asks.values())
    if solution.t[-1] < last - 1e-9 * max(1.0, abs(last)):
        return Simulation(False, f"the integration stopped at {solution.t[-1]:.6g}, before the query at {last:.6g}")

    functions = {name: fn for name, (_, fn) in built.queries.items()}

    def value(name: str, t: float) -> float:
        return float(functions[name](t, solution.sol(t)))

    for name, (at, _) in asks.items():
        try:
            got = value(name, at)
        except (ArithmeticError, OverflowError, ValueError) as failure:
            return Simulation(False, f"{name!r} could not be evaluated at {at:.6g}: {failure}")
        if not math.isfinite(got):
            return Simulation(False, f"{name!r} is not finite at {at:.6g}")
    return Simulation(True, "integrated to every query time", built.t_span, asks, value)


def executable(candidate: Problem) -> tuple[LayerResult, Simulation | None]:
    try:
        run = simulate(candidate)
    except NotEvaluable as failure:
        return LayerResult(Layer.EXECUTABLE, Outcome.NOT_APPLICABLE, f"not measured: {failure}"), None
    return LayerResult(Layer.EXECUTABLE, Outcome.PASS if run.ok else Outcome.FAIL, run.detail), (run if run.ok else None)


def _pairs(candidate: Simulation, reference: Simulation) -> list[tuple[str, str, float]]:
    """(candidate query, reference query, asked time) for every question both ask."""
    out = []
    for ref_name, (at, dims) in reference.asks.items():
        for cand_name, (cand_at, cand_dims) in candidate.asks.items():
            if abs(cand_at - at) <= 1e-9 * max(1.0, abs(at)) and cand_dims == dims:
                out.append((cand_name, ref_name, at))
                break
    return out


def _close(a: float, b: float, scale: float) -> bool:
    return abs(a - b) <= AGREE * max(scale, abs(a), abs(b), 1e-12)


def structural(candidate: Problem, reference: Problem, cand: Simulation, ref: Simulation) -> LayerResult:
    if compare(reference, candidate).equivalent:
        return LayerResult(Layer.STRUCTURAL, Outcome.PASS, "canonical forms are equal")
    pairs = _pairs(cand, ref)
    if not pairs:
        return LayerResult(
            Layer.STRUCTURAL,
            Outcome.UNDECIDED,
            "no candidate query asks what the reference asks, at the same time and of the same dimension",
        )
    low = max(cand.t_span[0], ref.t_span[0])
    high = min(cand.t_span[1], ref.t_span[1])
    for cand_name, ref_name, at in pairs:
        times = sorted({low + (high - low) * i / (GRID - 1) for i in range(GRID)} | {at})
        reference_values = [ref.value(ref_name, t) for t in times]  # type: ignore[misc]
        scale = max(abs(v) for v in reference_values)
        for t, expected in zip(times, reference_values, strict=True):
            got = cand.value(cand_name, t)  # type: ignore[misc]
            if not _close(got, expected, scale):
                return LayerResult(
                    Layer.STRUCTURAL,
                    Outcome.FAIL,
                    f"{ref_name!r} is {got:.6g} at {t:.6g} where the reference's is {expected:.6g}; the same "
                    "case cannot follow two trajectories, so these are different models",
                )
    return LayerResult(
        Layer.STRUCTURAL,
        Outcome.UNDECIDED,
        "canonical forms differ and the queries agree along the whole shared range, which does not "
        "establish equivalence: compensating errors can reach the same trajectory",
    )


def _cited(problem: Problem) -> list:
    """The quantities a stated number produced: parameters with a value, and states' initial values,
    each with the span it cites."""
    return [
        q
        for q in problem.quantities
        if q.span is not None and q.value is not None and q.role in (Role.PARAMETER, Role.STATE)
    ]


def _overlaps(a, b) -> bool:
    return a.start < b.end and b.start < a.end


def _nudged(problem: Problem, name: str) -> Problem:
    quantities = tuple(
        dataclasses.replace(q, value=q.value * NUDGE) if q.name == name else q for q in problem.quantities
    )
    return dataclasses.replace(problem, quantities=quantities)


def provenance(candidate: Problem, reference: Problem, cand: Simulation, ref: Simulation) -> LayerResult:
    pairs = _pairs(cand, ref)
    matched = []
    for ref_quantity in _cited(reference):
        for cand_quantity in _cited(candidate):
            if _overlaps(ref_quantity.span, cand_quantity.span):
                matched.append((ref_quantity, cand_quantity))
                break
    if not pairs or not matched:
        return LayerResult(
            Layer.PROPERTY,
            Outcome.NOT_APPLICABLE,
            "no number the statement states is cited by both, or no question is asked by both",
        )
    compared = 0
    for ref_quantity, cand_quantity in matched:
        try:
            ref_after = simulate(_nudged(reference, ref_quantity.name))
            cand_after = simulate(_nudged(candidate, cand_quantity.name))
        except NotEvaluable:
            continue
        if not (ref_after.ok and cand_after.ok):
            continue
        for cand_name, ref_name, at in pairs:
            before_ref, before_cand = ref.value(ref_name, at), cand.value(cand_name, at)  # type: ignore[misc]
            moved_ref = ref_after.value(ref_name, at) - before_ref  # type: ignore[misc]
            moved_cand = cand_after.value(cand_name, at) - before_cand  # type: ignore[misc]
            scale = max(abs(before_ref), 1e-12)
            if abs(moved_ref) <= QUIET * scale:
                continue
            compared += 1
            if abs(moved_cand) <= QUIET * max(abs(before_cand), 1e-12) or (moved_cand > 0) != (moved_ref > 0):
                cited = ref_quantity.span.text
                return LayerResult(
                    Layer.PROPERTY,
                    Outcome.FAIL,
                    f"raising the stated {cited!r} moves {ref_name!r} by {moved_cand:+.4g} where the "
                    f"reference moves by {moved_ref:+.4g}: the candidate does not respond as the system described",
                )
    if not compared:
        return LayerResult(
            Layer.PROPERTY,
            Outcome.NOT_APPLICABLE,
            "no cited number moves a shared question in the reference, so none can be compared",
        )
    return LayerResult(
        Layer.PROPERTY,
        Outcome.PASS,
        f"{compared} response(s) to a stated number agree in direction with the reference",
    )


def score(candidate: Problem, reference: Problem | None) -> list[LayerResult]:
    """The three layers for a validated dynamics candidate."""
    run, simulation = executable(candidate)
    results = [run]
    if simulation is None:
        return results
    if reference is None:
        results.append(
            LayerResult(Layer.STRUCTURAL, Outcome.NOT_APPLICABLE, "the case carries no reference formalization")
        )
        return results
    reference_run = simulate(reference)
    if not reference_run.ok:
        results.append(
            LayerResult(Layer.STRUCTURAL, Outcome.NOT_APPLICABLE, f"the reference did not integrate: {reference_run.detail}")
        )
        return results
    results.append(structural(candidate, reference, simulation, reference_run))
    results.append(provenance(candidate, reference, simulation, reference_run))
    return results


__all__ = ["Simulation", "executable", "provenance", "score", "simulate", "structural"]
