"""R-045: a recorded candidate scores again with the layers a sweep used.

The record carries the document (R-034) so that a check written later can be applied to it. This
proves the path: the verdicts a sweep stored come back from ``Sweep.score`` on the stored document,
with nothing called. A dynamics case, so no solver extra is needed.
"""

from __future__ import annotations

import json
from fractions import Fraction

import pytest

pytest.importorskip("scipy.integrate", reason="the dynamics layers integrate with SciPy")

from planteo import (  # noqa: E402
    Constant,
    Dimension,
    Family,
    Narrative,
    Power,
    Problem,
    Product,
    Quantity,
    Query,
    Rate,
    Ref,
    Role,
    Span,
    Sum,
)

from copela import Budget, Case, Ledger, StubProvider, Sweep, Target  # noqa: E402

WORDS = Narrative("A 50 L vat holds 3 kg of dye, and clean water flushes it at 2 L/min. How much dye after 10 min?")


def vat(flow: float) -> Problem:
    litre_per_min = Dimension.of("L/min", length=3, time=-1)
    return Problem(
        narrative=WORDS,
        family=Family.DYNAMICS,
        quantities=(
            Quantity("t", Role.INDEPENDENT, Dimension.of("min", time=1), lower=0.0, upper=10.0),
            Quantity("x", Role.STATE, Dimension.of("kg", mass=1), value=3.0, span=Span.find(WORDS, "3 kg")),
            Quantity("V", Role.PARAMETER, Dimension.of("L", length=3), value=50.0, span=Span.find(WORDS, "50 L")),
            Quantity("q", Role.PARAMETER, litre_per_min, value=flow, span=Span.find(WORDS, "2 L/min")),
        ),
        relations=(
            Rate("x", "t", Product((Constant(-1.0, Dimension.dimensionless()), Ref("q"), Ref("x"), Power(Ref("V"), Fraction(-1))))),
        ),
        queries=(Query(Ref("x"), 10.0, name="dye_after_10_min"),),
    )


def test_a_recorded_candidate_scores_to_its_stored_verdicts(ledger_path) -> None:
    reference = vat(2.0)
    case = Case("vat", "dynamics", WORDS.text, reference=reference)
    for reply in (vat(2.0), vat(4.0)):  # the reference itself, and a flush twice as fast
        ledger = Ledger(ledger_path.with_name(f"flow-{reply.quantities[3].value}.jsonl"))
        sweep = Sweep(
            ledger=ledger,
            budget=Budget(limit_usd=1.0),
            providers={"stub": StubProvider(default=json.dumps(reply.to_json()))},
            build_prompt=lambda case: case.narrative,
            parse_response=lambda text, case: Problem.from_json(json.loads(text)),
            repeats=1,
        )
        sweep.run([case], [Target("stub", "stub-small")])
        (record,) = Ledger(ledger.path).records()
        again = sweep.score(Problem.from_json(record.candidate), case)
        assert [(v.layer.value, v.outcome.value, v.detail) for v in again] == [
            (v["layer"], v["outcome"], v["detail"]) for v in record.verdicts
        ]
    # The second is refuted, so the comparison covered a failure as well as a pass.
    assert record.verdicts[1]["outcome"] == "fail"
