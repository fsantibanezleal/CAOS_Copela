"""The command line.

Four commands, and the only one that spends money refuses to start without a declared budget.

    copela models                     what each provider can serve, and what it costs
    copela solve  <problem.json>      solve one formalization, no model involved
    copela sweep  <cases.json> ...    run the sweep
    copela report <ledger.jsonl>      the gap, from a ledger
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __display_version__
from .budget import Budget
from .ledger import Ledger
from .providers import ProviderError, get


def _selectable_providers() -> list[str]:
    """Every registered provider except the scripted stub, which is for dry runs."""
    from .providers import REGISTRY

    return [name for name in sorted(REGISTRY) if name != "stub"]


def _cmd_models(args: argparse.Namespace) -> int:
    for name in args.providers:
        try:
            provider = get(name)
            models = provider.models()
        except ProviderError as error:
            print(f"{name}: unavailable ({error})")
            continue
        print(f"{name}:")
        for model_id, pricing in sorted(models.items()):
            if pricing.input_per_mtok or pricing.output_per_mtok:
                cost = f"{pricing.input_per_mtok:g} in / {pricing.output_per_mtok:g} out per MTok"
            else:
                cost = "no per-token price"
            print(f"  {model_id:<40} {cost}")
    return 0


def _cmd_solve(args: argparse.Namespace) -> int:
    from planteo import Problem, validate

    problem = Problem.from_json(json.loads(Path(args.problem).read_text(encoding="utf-8")))
    report = validate(problem)
    if not report.ok:
        print(report)
        return 1

    from .solvers.highs import SolverUnavailable, solve

    try:
        solution = solve(problem, solver_name=args.solver)
    except SolverUnavailable as error:
        print(error)
        return 2

    print(f"status: {solution.detail}")
    if solution.objective is not None:
        print(f"objective: {solution.objective:.6g}")
    for name, value in sorted(solution.values.items()):
        print(f"  {name} = {value:.6g}")
    return 0 if solution.feasible else 1


def _cmd_sweep(args: argparse.Namespace) -> int:
    # A sweep is the only command that spends. It refuses to start without a budget rather than
    # defaulting to one, because a default budget is a number nobody chose.
    if args.budget_usd is None:
        print(
            "a sweep needs a declared budget: pass --budget-usd. "
            "Every sweep states its ceiling and its kill criterion before it runs",
            file=sys.stderr,
        )
        return 2

    print(
        f"sweep configured: budget {args.budget_usd} USD, "
        f"{args.repeats} repeat(s), ledger {args.ledger}"
    )
    print(
        "Assembling cases and targets is done from Python: the prompt strategy and the response "
        "parser are what a study varies, so they are arguments rather than flags. "
        "See docs/guides/01_run_a_sweep.md"
    )
    Budget(limit_usd=args.budget_usd)  # validates the ceiling now rather than mid-run
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from .report import build

    ledger = Ledger(args.ledger)
    if not Path(args.ledger).exists():
        print(f"no ledger at {args.ledger}", file=sys.stderr)
        return 2

    report = build(ledger)
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(report.to_text())
        print(f"\nledger: {len(ledger.records())} call(s), {ledger.total_cost_usd:.4f} USD")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="copela",
        description=(
            "Run narrative-to-formal translation across many models and score it with oracles "
            "that are not language models."
        ),
    )
    parser.add_argument("--version", action="version", version=f"copela {__display_version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    models = subparsers.add_parser("models", help="list what each provider can serve")
    models.add_argument(
        "providers",
        nargs="*",
        # Read from the registry rather than written out here. A hardcoded list would put vendor
        # names outside the seam, which R-006 forbids and a test enforces.
        default=_selectable_providers(),
        help="provider names",
    )
    models.set_defaults(func=_cmd_models)

    solve = subparsers.add_parser("solve", help="solve one formalization, no model involved")
    solve.add_argument("problem", help="a planteo Problem as JSON")
    solve.add_argument("--solver", default="appsi_highs")
    solve.set_defaults(func=_cmd_solve)

    sweep = subparsers.add_parser("sweep", help="run a sweep")
    sweep.add_argument("--ledger", default="runs.jsonl")
    sweep.add_argument("--budget-usd", type=float, default=None, help="required; the hard ceiling")
    sweep.add_argument("--repeats", type=int, default=3)
    sweep.set_defaults(func=_cmd_sweep)

    report = subparsers.add_parser("report", help="the gap, from a ledger")
    report.add_argument("ledger")
    report.add_argument("--json", action="store_true")
    report.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
