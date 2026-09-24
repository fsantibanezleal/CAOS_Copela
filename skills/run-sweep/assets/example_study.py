"""A minimal study for run_sweep.py: one authored case, a prompt, and a strict parser.

It is small on purpose: the runner is what the skill ships, and a study is what a user writes. A real
study replaces `cases()` with its corpus, each case carrying the reference formalization the
structural layer compares against, and replaces the prompt with its own strategy.

    python ../scripts/run_sweep.py --study example_study.py --provider stub --model stub-small \\
        --ledger runs.jsonl --budget-usd 0.01
"""

from __future__ import annotations

import json
from pathlib import Path

from planteo import Problem

from copela import Case

HERE = Path(__file__).resolve().parent


def cases() -> list[Case]:
    """The authored cases. The reference is the formalization the answer is compared against."""
    document = json.loads((HERE / "example_blend.json").read_text(encoding="utf-8"))
    reference = Problem.from_json(document)
    return [Case("blend-001", "optimization", reference.narrative.text, reference=reference)]


def build_prompt(case: Case) -> str:
    """What the model is asked. A study varies this; the harness records its digest."""
    return (
        "Formalize the optimization problem below as a planteo document: one JSON object with "
        "'schema_version', 'family', 'narrative', 'quantities', 'relations' and 'objectives'. Every "
        "quantity names its role (variable, parameter or derived) and its dimension, and cites the "
        "span of the narrative it comes from. Reply with the JSON object only.\n\n"
        f"Problem: {case.narrative}"
    )


def parse_response(text: str, case: Case) -> Problem:
    """Strict: the first JSON object in the reply, validated by planteo. A reply that is not one
    raises, and copela records that as an executable-layer failure with its excerpt."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"the response contains no JSON object. It began: {text[:120]!r}")
    return Problem.from_json(json.loads(text[start : end + 1]))
