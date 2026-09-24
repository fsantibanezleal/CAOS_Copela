#!/usr/bin/env python3
"""Run one narrative-to-formal sweep with copela, with every refusal made before anything is spent.

A study is a Python file that says what a sweep varies and nothing else:

    cases()                        -> list[copela.Case]
    build_prompt(case)             -> str
    parse_response(text, case)     -> planteo.Problem       (raise on anything it cannot read)
    solver()                       -> callable or None      (optional; defaults to HiGHS if installed)

Everything a study must not decide is decided here, in this order, and each refusal comes before the
ledger's lock is taken, so a refused run never leaves a lock behind:

1. the provider exists and prices the model (an unpriced model could not be bounded by the budget);
2. a paid model has a declared budget;
3. one unrecorded probe call reaches the provider, so a key read wrong or a network that is down
   produces a refusal and not a row of call failures in an append-only ledger;
4. the ledger is taken exclusively, so two sweeps never interleave in one file;
5. the sweep runs; a call that never reaches the provider stops it (copela's ProviderUnreachable),
   recording nothing for that call, and the same command resumes there.

    python run_sweep.py --study study.py --provider anthropic --model claude-haiku-4-5 \\
        --ledger runs.jsonl --budget-usd 1.00 --repeats 1

Exit codes: 0 done, 2 refused before starting, 3 the ledger is busy, 4 stopped because the provider
could not be reached (resume with the same command).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from copela import Budget, Ledger, Sweep, Target
from copela.ledger import LedgerBusy
from copela.providers import ProviderError, ProviderUnreachable, get
from copela.report import build


def load_study(path: Path):
    spec = importlib.util.spec_from_file_location("study", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load a study from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)
    for name in ("cases", "build_prompt", "parse_response"):
        if not callable(getattr(module, name, None)):
            raise SystemExit(f"{path} defines no {name}(); a study needs cases, build_prompt and parse_response")
    return module


def default_solver():
    try:
        from copela.solvers.highs import make_solver
    except ImportError:
        return None
    return make_solver()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--study", type=Path, required=True, help="a Python file: cases, build_prompt, parse_response")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--budget-usd", type=float, default=None, help="required for a paid model")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=10,
        help="the kill criterion; raise it to the corpus size only when the failures ARE the measurement",
    )
    parser.add_argument("--think", choices=["on", "off", "default"], default="off", help="local reasoning models only")
    parser.add_argument("--limit-cases", type=int, default=None, help="a smoke run over the first N cases")
    parser.add_argument("--no-probe", action="store_true", help="skip the unrecorded probe call")
    args = parser.parse_args(argv)

    study = load_study(args.study)
    try:
        provider = get(args.provider, think={"on": True, "off": False, "default": None}[args.think]) if args.provider == "ollama" else get(args.provider)
        pricing = provider.models().get(args.model)
    except ProviderError as error:
        print(f"refused: the provider is unavailable: {error}", file=sys.stderr)
        return 2
    if pricing is None:
        print(f"refused: {args.provider} has no price for {args.model!r}, so the budget could not bound it", file=sys.stderr)
        return 2
    free = pricing.input_per_mtok == 0 and pricing.output_per_mtok == 0
    if args.budget_usd is None and not free:
        print(f"refused: {args.provider}/{args.model} is paid and no --budget-usd was declared", file=sys.stderr)
        return 2
    if args.budget_usd is None:
        budget = Budget(limit_usd=0.0001, max_consecutive_failures=args.max_consecutive_failures)
        budget.limit_usd = float("inf")
    else:
        budget = Budget(limit_usd=args.budget_usd, max_consecutive_failures=args.max_consecutive_failures)

    if not args.no_probe:
        try:
            provider.complete("Reply with the single word ok.", model_id=args.model, temperature=0.0, seed=0, max_tokens=16)
        except ProviderError as error:
            print(f"refused: the probe call failed, so nothing was started or recorded: {error}", file=sys.stderr)
            return 2

    try:
        ledger = Ledger(args.ledger, exclusive=True)
    except LedgerBusy as error:
        print(error, file=sys.stderr)
        return 3

    cases = list(study.cases())
    if args.limit_cases:
        cases = cases[: args.limit_cases]
    solve = study.solver() if callable(getattr(study, "solver", None)) else default_solver()
    sweep = Sweep(
        ledger=ledger,
        budget=budget,
        providers={args.provider: provider},
        build_prompt=study.build_prompt,
        parse_response=study.parse_response,
        solve=solve,
        repeats=args.repeats,
        temperature=0.0,
        max_tokens=args.max_tokens,
    )
    print(f"sweeping {len(cases)} case(s) x {args.repeats} repeat(s) of {args.provider}/{args.model}")
    print(f"  budget: {'no per-token cost' if free else budget.describe()}; kill criterion {args.max_consecutive_failures}")
    try:
        made = sweep.run(cases, [Target(args.provider, args.model)])
    except ProviderUnreachable as error:
        print(f"stopped: {error}. That call was not recorded; run the same command again to resume", file=sys.stderr)
        return 4
    finally:
        ledger.release()

    print(f"\n{made} call(s) made. {budget.describe()}\n")
    print(build(ledger).to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
