"""Verdicts, layers, and the rule that they are never merged.

The whole point of this harness is a number the field does not report: the distance between "the
artifact ran" and "the artifact is right". That distance only exists while the layers are kept apart.
A combined score, however carefully weighted, is a single number in which a high executable rate
conceals a low faithfulness rate, which is the exact failure being measured.

So there is no combined score here, and `LayerResult` deliberately offers no arithmetic that would
produce one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Layer(str, Enum):
    """The four layers, in increasing strength.

    ``JUDGE`` is included because the literature reports it and comparability matters. It is not an
    oracle, and every record carries a label saying so: the study that calibrated a two-judge
    consensus against human majority (reaching 89.7% agreement, 95% CI 82.1 to 94.3) states plainly
    that LLM judging is a human-calibrated conservative aggregate measure, not an equivalence
    oracle.
    """

    EXECUTABLE = "executable"
    STRUCTURAL = "structural"
    PROPERTY = "property"
    JUDGE = "judge"


#: What a judge verdict is, carried in every record that holds one. R-002.
JUDGE_LABEL = (
    "screening aggregate, not an equivalence oracle; reported for comparability with the "
    "literature and never used as ground truth"
)


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    #: The check could not be evaluated. Distinct from PASS on purpose: a relation that could not be
    #: evaluated because the candidate never ran has established nothing, and counting it as a pass
    #: is how a harness reports a number it did not measure.
    NOT_APPLICABLE = "not-applicable"
    #: The check ran and could not decide. For the structural layer this is the honest result of
    #: canonical inequality, which proves nothing.
    UNDECIDED = "undecided"


@dataclass(frozen=True, slots=True)
class LayerResult:
    layer: Layer
    outcome: Outcome
    detail: str = ""
    #: For the judge layer only, and mandatory there.
    label: str = ""

    def __post_init__(self) -> None:
        if self.layer is Layer.JUDGE and not self.label:
            raise ValueError(
                "a judge verdict must carry its label; see JUDGE_LABEL and R-002"
            )

    @classmethod
    def judge(cls, outcome: Outcome, detail: str = "") -> LayerResult:
        return cls(Layer.JUDGE, outcome, detail, JUDGE_LABEL)

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {
            "layer": self.layer.value,
            "outcome": self.outcome.value,
            "detail": self.detail,
        }
        if self.label:
            out["label"] = self.label
        return out


@dataclass(frozen=True, slots=True)
class CandidateVerdict:
    """Every layer's verdict for one candidate formalization.

    There is no ``score`` property and there will not be one. See the module docstring.
    """

    results: tuple[LayerResult, ...] = ()

    def of(self, layer: Layer) -> LayerResult | None:
        for result in self.results:
            if result.layer is layer:
                return result
        return None

    def passed(self, layer: Layer) -> bool:
        result = self.of(layer)
        return result is not None and result.outcome is Outcome.PASS

    @property
    def ran(self) -> bool:
        """Layer 1 only: did the artifact execute. The weak claim, named weakly."""
        return self.passed(Layer.EXECUTABLE)

    @property
    def faithful(self) -> bool:
        """Layers 2 and 3 together, and only when they actually decided.

        Structural ``UNDECIDED`` does not block: canonical inequality proves nothing, so the
        property layer carries the decision in that case. A candidate is called faithful when it
        ran, nothing that could decide against it did, and at least one strong layer decided for
        it.

        The first clause was missing (R-021). The sweep never produces a structural or property
        verdict for a candidate that did not run, so no recorded rate was affected, but the
        property is public API and a verdict built by hand could be "faithful" without running,
        which the report's own comment rules out.
        """
        if not self.ran:
            return False
        structural = self.of(Layer.STRUCTURAL)
        prop = self.of(Layer.PROPERTY)
        for result in (structural, prop):
            if result is not None and result.outcome is Outcome.FAIL:
                return False
        decided = [
            r
            for r in (structural, prop)
            if r is not None and r.outcome is Outcome.PASS
        ]
        return bool(decided)

    def to_json(self) -> list[dict[str, object]]:
        return [result.to_json() for result in self.results]


@dataclass(frozen=True, slots=True)
class Rate:
    """A proportion over n observations, with an interval.

    A single run is not a result. Hosted inference is not deterministic even at temperature zero
    (the dominant cause is the batch-size dependence of reduction kernels, not floating-point
    non-associativity), so a rate over repeats with an interval is the honest unit of reporting.

    The interval is Wilson, which behaves at 0 and 1 where the normal approximation does not. A
    harness that reported 0.0 plus or minus 0.0 after five failures would be claiming certainty it
    has not got.
    """

    passed: int
    total: int
    confidence: float = 0.95

    def __post_init__(self) -> None:
        if self.total < 0 or self.passed < 0 or self.passed > self.total:
            raise ValueError(f"impossible rate: {self.passed} of {self.total}")

    @property
    def value(self) -> float:
        return self.passed / self.total if self.total else float("nan")

    @property
    def interval(self) -> tuple[float, float]:
        """Wilson score interval. Returns ``(nan, nan)`` when there is nothing to report."""
        if self.total == 0:
            return (float("nan"), float("nan"))
        z = 1.959963984540054 if abs(self.confidence - 0.95) < 1e-9 else _z(self.confidence)
        n = self.total
        p = self.value
        denominator = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denominator
        spread = (z / denominator) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
        return (max(0.0, centre - spread), min(1.0, centre + spread))

    def describe(self) -> str:
        if self.total == 0:
            return "no observations"
        low, high = self.interval
        return f"{self.value:.3f} [{low:.3f}, {high:.3f}] over n={self.total}"

    def to_json(self) -> dict[str, object]:
        low, high = self.interval
        return {
            "passed": self.passed,
            "total": self.total,
            "value": self.value,
            "interval_low": low,
            "interval_high": high,
            "confidence": self.confidence,
        }


def _z(confidence: float) -> float:
    """Inverse normal CDF at ``(1 + confidence) / 2``, by bisection.

    Bisection rather than a closed-form approximation because this is called once per reported rate
    and correctness matters more than speed here.
    """
    target = (1 + confidence) / 2
    low, high = 0.0, 10.0
    for _ in range(200):
        mid = (low + high) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2
