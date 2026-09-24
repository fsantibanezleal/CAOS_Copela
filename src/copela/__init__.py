"""copela: run narrative-to-formal translation across many models, and score it with oracles
that are not language models.

The name is the cupel used in fire assay, the vessel that separates the metal from the lead. That is
the job here: separating a formalization that is faithful from one that merely runs.

Four layers, reported separately and never merged into one score:

1. executable, did it run, solve, compile
2. structural, is it the same model as the reference
3. property, do the invariants of this class hold
4. judge, what a model says, recorded as a labelled screening aggregate and never as truth

The headline is the subtraction: how often the artifact ran, minus how often it was right.
"""

from __future__ import annotations

from .budget import Budget, BudgetExceeded, UnpricedModel, estimate
from .ledger import CallKey, Ledger, LedgerError, Record
from .providers import Provider, ProviderError, ProviderUnreachable, StubProvider
from .report import Cell, Report, build
from .sweep import Case, Sweep, Target
from .verdicts import (
    JUDGE_LABEL,
    CandidateVerdict,
    Layer,
    LayerResult,
    Outcome,
    Rate,
)

__version__ = "0.10.0"
__display_version__ = "0.04.000"

__all__ = [
    "JUDGE_LABEL",
    "Budget",
    "BudgetExceeded",
    "CallKey",
    "CandidateVerdict",
    "Case",
    "Cell",
    "Layer",
    "LayerResult",
    "Ledger",
    "LedgerError",
    "Outcome",
    "Provider",
    "ProviderError",
    "ProviderUnreachable",
    "Rate",
    "Record",
    "Report",
    "StubProvider",
    "Sweep",
    "Target",
    "UnpricedModel",
    "__display_version__",
    "__version__",
    "build",
    "estimate",
]
