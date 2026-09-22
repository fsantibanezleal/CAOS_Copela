"""Shared fixtures.

The blend problem is the same one `planteo` uses, so a reader following both repos sees one worked
example rather than two.
"""

from __future__ import annotations

import json

import pytest
from planteo import (
    Comparator,
    Compare,
    Dimension,
    Family,
    Narrative,
    Objective,
    Problem,
    Product,
    Quantity,
    Ref,
    Role,
    Sense,
    Sum,
)

TONNE = Dimension.of("t", mass=1)
PER_TONNE = Dimension.of("USD/t", currency=1, mass=-1)

NARRATIVE = (
    "A plant blends ore from two pits. Pit A costs 12 USD per tonne and pit B "
    "costs 9 USD per tonne. Together they must deliver at least 100 tonnes. "
    "Minimise the total cost."
)


def make_blend(demand: float = 100.0, cost_b: float = 9.0) -> Problem:
    text = Narrative(NARRATIVE)
    return Problem(
        narrative=text,
        family=Family.OPTIMIZATION,
        quantities=(
            Quantity("x_a", Role.VARIABLE, TONNE, lower=0.0),
            Quantity("x_b", Role.VARIABLE, TONNE, lower=0.0),
            Quantity("c_a", Role.PARAMETER, PER_TONNE, value=12.0),
            Quantity("c_b", Role.PARAMETER, PER_TONNE, value=cost_b),
            Quantity("demand", Role.PARAMETER, TONNE, value=demand),
        ),
        relations=(
            Compare(
                Sum((Ref("x_a"), Ref("x_b"))),
                Comparator.GE,
                _constant(demand),
                name="meet_demand",
            ),
        ),
        objectives=(
            Objective(
                Sense.MINIMISE,
                Sum(
                    (
                        Product((Ref("c_a"), Ref("x_a"))),
                        Product((Ref("c_b"), Ref("x_b"))),
                    )
                ),
                name="total_cost",
            ),
        ),
    )


def _constant(value: float):
    from planteo import Constant

    return Constant(value, TONNE)


@pytest.fixture
def blend() -> Problem:
    return make_blend()


@pytest.fixture
def blend_json(blend) -> str:
    return json.dumps(blend.to_json())


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "runs.jsonl"
