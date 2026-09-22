"""Property relations: the layer that catches what structure misses.

Metamorphic testing is the recognised route around an absent oracle. Rather than checking an exact
output, it checks how the output must change when the input changes in a controlled way. Its known
limitation is that the relations have to be identified per problem class, which does not generalise
to arbitrary programs.

That limitation is why this works here. The target families are narrow typed classes, not arbitrary
programs, so the relations are authored once per class and then apply to every case in it. The
objection in the literature becomes the design.

Each relation transforms a problem, re-solves, and compares against what the transformation
guarantees. A candidate that solves and then fails one of these is wrong in a way no solver would
have reported, which is exactly the gap this harness measures.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass

from planteo import (
    Comparator,
    Compare,
    Constant,
    Objective,
    Problem,
    Product,
    Ref,
)

from ..verdicts import Layer, LayerResult, Outcome

#: Solving is injected rather than imported, so the relations are testable without a solver and the
#: solver choice stays a runtime decision.
Solve = Callable[[Problem], "Solution"]


@dataclass(frozen=True, slots=True)
class Solution:
    """What a solver returns, reduced to what the relations need."""

    feasible: bool
    objective: float | None
    values: dict[str, float]
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Relation:
    name: str
    #: What it guarantees, in one sentence, for the report and the docs.
    guarantee: str
    transform: Callable[[Problem], Problem]
    check: Callable[[Solution, Solution], tuple[bool, str]]


TOLERANCE = 1e-6


def _close(left: float, right: float, tolerance: float = TOLERANCE) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


# -- the transformations ------------------------------------------------------------------


def scale_objective(problem: Problem, factor: float = 3.0) -> Problem:
    """Multiply every objective by a positive constant."""
    scaled = tuple(
        Objective(
            sense=objective.sense,
            expression=Product(
                (Constant(factor, _dimensionless_of(objective)), objective.expression)
            ),
            name=objective.name,
            span=objective.span,
        )
        for objective in problem.objectives
    )
    return dataclasses.replace(problem, objectives=scaled)


def _dimensionless_of(objective: Objective):
    from planteo import Dimension

    return Dimension.dimensionless()


def add_redundant_constraint(problem: Problem) -> Problem:
    """Restate a variable's own bound as a constraint. The feasible set must not move.

    The obvious version of this relation, a constant comparison like ``0 <= 1``, does not work: it
    carries no variable, so it is not a constraint at all and a modelling layer rightly rejects it
    as a trivial boolean. The relation has to add something the solver must actually carry while
    changing nothing, and a variable's existing bound restated as a row is exactly that.
    """
    from planteo import Role

    for quantity in problem.quantities:
        if quantity.role is not Role.VARIABLE:
            continue
        if quantity.lower is not None:
            probe = Compare(
                left=Ref(quantity.name),
                comparator=Comparator.GE,
                right=Constant(quantity.lower, quantity.dimension),
                name="redundant_probe",
            )
        elif quantity.upper is not None:
            probe = Compare(
                left=Ref(quantity.name),
                comparator=Comparator.LE,
                right=Constant(quantity.upper, quantity.dimension),
                name="redundant_probe",
            )
        else:
            continue
        return dataclasses.replace(problem, relations=problem.relations + (probe,))

    raise Unapplicable(
        "no bounded decision variable whose bound can be restated as a redundant row"
    )


def tighten_first_bound(problem: Problem, factor: float = 1.25) -> Problem:
    """Tighten the first inequality by moving its right-hand constant.

    Tightening means demanding more, so for a minimisation the optimum cannot get better. The
    direction is computed from the comparator and the sense rather than assumed, because assuming it
    is how a relation silently checks the opposite of what it claims.
    """
    relations = list(problem.relations)
    for index, relation in enumerate(relations):
        if not isinstance(relation, Compare):
            continue
        if relation.comparator not in (Comparator.GE, Comparator.LE):
            continue
        if not isinstance(relation.right, Constant):
            continue
        constant = relation.right
        if relation.comparator is Comparator.GE:
            moved = constant.value * factor  # demand more
        else:
            moved = constant.value / factor  # allow less
        relations[index] = dataclasses.replace(
            relation, right=Constant(moved, constant.unit)
        )
        return dataclasses.replace(problem, relations=tuple(relations))
    raise Unapplicable("no inequality with a constant right-hand side to tighten")


class Unapplicable(Exception):
    """The relation does not apply to this problem. Not a pass and not a failure."""


# -- the checks ---------------------------------------------------------------------------


def _argmin_unchanged(base: Solution, other: Solution) -> tuple[bool, str]:
    if not base.feasible or not other.feasible:
        return False, "feasibility changed under a transformation that cannot change it"
    shared = set(base.values) & set(other.values)
    if not shared:
        return False, "no shared variables to compare"
    for name in sorted(shared):
        if not _close(base.values[name], other.values[name]):
            return (
                False,
                f"{name} moved from {base.values[name]:.6g} to {other.values[name]:.6g} "
                "under objective scaling, which cannot move the argmin",
            )
    return True, "argmin unchanged"


def _feasible_set_unchanged(base: Solution, other: Solution) -> tuple[bool, str]:
    if base.feasible != other.feasible:
        return False, "a redundant constraint changed feasibility"
    if base.objective is None or other.objective is None:
        return base.feasible == other.feasible, "both infeasible"
    if not _close(base.objective, other.objective):
        return (
            False,
            f"optimum moved from {base.objective:.6g} to {other.objective:.6g} "
            "under a constraint that adds nothing",
        )
    return True, "optimum unchanged"


def _cannot_improve(base: Solution, other: Solution) -> tuple[bool, str]:
    """After tightening, a minimisation optimum must not fall, and a maximisation must not rise."""
    if not other.feasible:
        # Tightening a constraint until the problem is infeasible is legitimate, not a violation.
        return True, "tightened into infeasibility, which is allowed"
    if base.objective is None or other.objective is None:
        return False, "an optimum is missing, so the comparison cannot be made"
    if other.objective < base.objective - TOLERANCE * max(1.0, abs(base.objective)):
        return (
            False,
            f"optimum improved from {base.objective:.6g} to {other.objective:.6g} "
            "after tightening, which is impossible",
        )
    return True, f"optimum {base.objective:.6g} to {other.objective:.6g}, did not improve"


OPTIMIZATION_RELATIONS: tuple[Relation, ...] = (
    Relation(
        name="objective-scaling",
        guarantee="scaling the objective by a positive constant cannot move the argmin",
        transform=scale_objective,
        check=_argmin_unchanged,
    ),
    Relation(
        name="redundant-constraint",
        guarantee="adding an always-true constraint cannot change the feasible set",
        transform=add_redundant_constraint,
        check=_feasible_set_unchanged,
    ),
    Relation(
        name="tightening",
        guarantee="tightening a constraint cannot improve the optimum",
        transform=tighten_first_bound,
        check=_cannot_improve,
    ),
)


@dataclass(frozen=True, slots=True)
class RelationOutcome:
    relation: str
    outcome: Outcome
    detail: str


def evaluate(
    problem: Problem,
    solve: Solve,
    relations: tuple[Relation, ...] = OPTIMIZATION_RELATIONS,
) -> tuple[LayerResult, tuple[RelationOutcome, ...]]:
    """Run every relation. Returns the layer verdict and the per-relation detail.

    A relation that could not be evaluated is ``NOT_APPLICABLE``, never a pass. Counting an
    unevaluated check as a pass is how a harness reports a number it did not measure, and it is the
    specific failure R-009 exists to prevent.
    """
    try:
        base = solve(problem)
    except Exception as error:
        return (
            LayerResult(
                Layer.PROPERTY,
                Outcome.NOT_APPLICABLE,
                f"the candidate did not solve, so no relation could be evaluated: {error}",
            ),
            (),
        )

    if not base.feasible:
        return (
            LayerResult(
                Layer.PROPERTY,
                Outcome.NOT_APPLICABLE,
                "the candidate is infeasible, so the relations have nothing to compare against",
            ),
            (),
        )

    outcomes: list[RelationOutcome] = []
    for relation in relations:
        try:
            transformed = relation.transform(problem)
            other = solve(transformed)
        except Unapplicable as reason:
            outcomes.append(
                RelationOutcome(relation.name, Outcome.NOT_APPLICABLE, str(reason))
            )
            continue
        except Exception as error:
            outcomes.append(
                RelationOutcome(
                    relation.name,
                    Outcome.NOT_APPLICABLE,
                    f"could not evaluate: {error}",
                )
            )
            continue
        ok, detail = relation.check(base, other)
        outcomes.append(
            RelationOutcome(
                relation.name, Outcome.PASS if ok else Outcome.FAIL, detail
            )
        )

    failed = [o for o in outcomes if o.outcome is Outcome.FAIL]
    evaluated = [o for o in outcomes if o.outcome in (Outcome.PASS, Outcome.FAIL)]

    if failed:
        summary = "; ".join(f"{o.relation}: {o.detail}" for o in failed)
        return LayerResult(Layer.PROPERTY, Outcome.FAIL, summary), tuple(outcomes)
    if not evaluated:
        return (
            LayerResult(
                Layer.PROPERTY,
                Outcome.NOT_APPLICABLE,
                "no relation applied to this problem",
            ),
            tuple(outcomes),
        )
    return (
        LayerResult(
            Layer.PROPERTY,
            Outcome.PASS,
            f"{len(evaluated)} relation(s) held",
        ),
        tuple(outcomes),
    )
