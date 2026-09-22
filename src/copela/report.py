"""Reporting: the gap, and nothing that hides it.

The headline this harness exists to produce is a subtraction:

    ran rate  minus  faithful rate

The first is what the field reports. The second is what was asked. The measured distance between
them is 3 to 29 percentage points in the one field where it has been quantified carefully, and it is
not reported at all across families.

Everything here follows from keeping that subtraction possible. There is no combined score, and
there is no single-run result: every figure is a rate over repeats with an interval, because hosted
inference is not deterministic even at temperature zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .ledger import Ledger, Record
from .verdicts import CandidateVerdict, Layer, LayerResult, Outcome, Rate


def _verdict_of(record: Record) -> CandidateVerdict:
    results: list[LayerResult] = []
    for raw in record.verdicts:
        layer = Layer(str(raw["layer"]))
        results.append(
            LayerResult(
                layer=layer,
                outcome=Outcome(str(raw["outcome"])),
                detail=str(raw.get("detail", "")),
                label=str(raw.get("label", "")),
            )
        )
    return CandidateVerdict(tuple(results))


@dataclass(frozen=True, slots=True)
class Cell:
    """One model on one family: the two rates and the gap between them."""

    provider: str
    model_id: str
    family: str
    ran: Rate
    faithful: Rate

    @property
    def gap(self) -> float:
        """The headline. Positive means the artifact ran more often than it was right.

        ``nan`` when nothing ran, because the gap is then UNDEFINED rather than zero. A model that
        failed every call would otherwise be reported as ``gap +0.000``, which reads as "no gap"
        and means "no measurement". That is the exact confusion this product exists to prevent, so
        making it here would be unforgivable.
        """
        if self.ran.total == 0 or self.ran.passed == 0:
            return float("nan")
        return self.ran.value - self.faithful.value

    @property
    def gap_is_defined(self) -> bool:
        return self.ran.passed > 0

    def describe(self) -> str:
        gap = (
            f"gap {self.gap:+.3f}"
            if self.gap_is_defined
            else "gap UNDEFINED, nothing reached the faithfulness layers"
        )
        return (
            f"{self.provider}/{self.model_id} [{self.family}]  "
            f"ran {self.ran.describe()}  faithful {self.faithful.describe()}  {gap}"
        )

    def to_json(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "family": self.family,
            "ran": self.ran.to_json(),
            "faithful": self.faithful.to_json(),
            "gap": self.gap if self.gap_is_defined else None,
            "gap_is_defined": self.gap_is_defined,
        }


@dataclass(frozen=True, slots=True)
class Report:
    cells: tuple[Cell, ...]
    #: Judge verdicts, kept apart from everything above on purpose.
    judge: tuple[tuple[str, str, Rate], ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "cells": [cell.to_json() for cell in self.cells],
            "judge": [
                {
                    "provider": provider,
                    "model_id": model_id,
                    "rate": rate.to_json(),
                    "label": _JUDGE_NOTE,
                }
                for provider, model_id, rate in self.judge
            ],
            "note": _REPORT_NOTE,
        }

    def to_text(self) -> str:
        lines = ["gap report", "=" * 60, ""]
        # Undefined gaps sort last rather than crashing the comparison on nan.
        for cell in sorted(
            self.cells,
            key=lambda c: (c.family, 0 if c.gap_is_defined else 1, -c.gap if c.gap_is_defined else 0),
        ):
            lines.append("  " + cell.describe())
        if self.judge:
            lines += ["", "judge layer (screening aggregate, not an oracle):"]
            for provider, model_id, rate in self.judge:
                lines.append(f"  {provider}/{model_id}  {rate.describe()}")
        lines += ["", _REPORT_NOTE]
        return "\n".join(lines)


_REPORT_NOTE = (
    "The layers are reported separately by design. There is no combined score: a single number "
    "would let a high 'it ran' rate conceal a low 'it was right' rate, which is the distance this "
    "report exists to show. Rates are over repeats with a Wilson interval; hosted inference is not "
    "deterministic at temperature zero, so a single run is not a result."
)

_JUDGE_NOTE = (
    "screening aggregate, not an equivalence oracle; reported for comparability with the "
    "literature and never used as ground truth"
)


def build(ledger: Ledger) -> Report:
    """Summarise a ledger into per-model, per-family cells."""
    ran: dict[tuple[str, str, str], list[bool]] = defaultdict(list)
    faithful: dict[tuple[str, str, str], list[bool]] = defaultdict(list)
    judged: dict[tuple[str, str], list[bool]] = defaultdict(list)

    for record in ledger:
        key = (record.key.provider, record.key.model_id, record.family)
        verdict = _verdict_of(record)
        ran[key].append(verdict.ran)
        # A candidate that never ran cannot be faithful, and it counts as an observation: dropping
        # it would inflate the faithful rate by quietly shrinking its denominator.
        faithful[key].append(verdict.faithful)
        judge = verdict.of(Layer.JUDGE)
        if judge is not None and judge.outcome in (Outcome.PASS, Outcome.FAIL):
            judged[(record.key.provider, record.key.model_id)].append(
                judge.outcome is Outcome.PASS
            )

    cells = tuple(
        Cell(
            provider=provider,
            model_id=model_id,
            family=family,
            ran=Rate(sum(ran[(provider, model_id, family)]), len(ran[(provider, model_id, family)])),
            faithful=Rate(
                sum(faithful[(provider, model_id, family)]),
                len(faithful[(provider, model_id, family)]),
            ),
        )
        for (provider, model_id, family) in sorted(ran)
    )

    judge = tuple(
        (provider, model_id, Rate(sum(values), len(values)))
        for (provider, model_id), values in sorted(judged.items())
    )
    return Report(cells, judge)
