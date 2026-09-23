# Guide: run a sweep

## What a sweep is

Cases times models times repeats. Each cell is one call, scored by the four layers and written to
the ledger as one record.

## 1. Declare the budget first

```python
from copela import Budget

budget = Budget(limit_usd=5.00, max_consecutive_failures=10)
```

This is not optional and the CLI refuses to start without it. The guard checks **before** each call,
so the sweep stops below the ceiling rather than reporting an overrun afterwards. The
consecutive-failure count is the kill criterion: a sweep whose calls are all failing is buying
nothing, and running it to the ceiling is waste.

Each call is projected at the most it can bill, `max_tokens` of output, so a sweep of reasoning
models stops earlier than their typical spend would suggest. That is the point: they bill their
reasoning as output, and a projection at a typical length let through calls it should have refused.
A model the provider has no price for is refused before the first call, with the list of the models
it does price.

## 2. Choose the targets, plural

```python
from copela.providers import get
from copela import Target

providers = {
    "ollama": get("ollama"),        # local, free, run it first
    "zai": get("zai"),              # hosted; GLM-4.5-Flash is free
    "groq": get("groq"),            # cheap hosted
    "deepseek": get("deepseek"),    # hosted reasoning
    "anthropic": get("anthropic"),  # frontier, on the reduced set
}

targets = [
    Target("ollama", "qwen3:8b"),
    Target("zai", "glm-4.5-flash"),
    Target("groq", "openai/gpt-oss-120b"),
    Target("deepseek", "deepseek-v4-pro"),
    Target("anthropic", "claude-sonnet-5"),
]
```

`copela models` prints what each provider prices. Keys come from the environment, never from a
file in the repo. A Z.AI GLM Coding Plan key is refused by the pay-per-token endpoint; set
`ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4` for it, and read the ledger's cost as the
list-price equivalent of calls drawn from the plan's quota.

Cheap first is the ladder: local, then small hosted, then frontier on the reduced case set. And
plural is the requirement, not a preference, because no single model dominates across engine types.

## 3. Supply the prompt strategy and the parser

```python
def build_prompt(case):
    return PROMPT_TEMPLATE.format(narrative=case.narrative)

def parse_response(text):
    from planteo import Problem
    import json
    return Problem.from_json(json.loads(_extract_json(text)))
```

Both are arguments rather than fixed behaviour. The prompt strategy is exactly what a study varies,
and freezing it inside the harness would make the most interesting variable inaccessible.

`parse_response` should raise on anything it cannot read. A response that does not parse is an
executable-layer failure, it is recorded with the parse error, and the run is kept.

## 4. Build the cases

```python
from copela import Case

cases = [
    Case(
        case_id="blend-001",
        family="optimization",
        narrative="A plant blends ore from two pits...",
        reference=reference_problem,   # optional
        tier=1,
    ),
]
```

A case without a `reference` still runs: it gets an executable and a property verdict, and the
structural layer reports not-applicable rather than guessing.

## 5. Run it

```python
from copela import Ledger, Sweep
from copela.solvers.highs import make_solver

sweep = Sweep(
    ledger=Ledger("runs.jsonl"),
    budget=budget,
    providers=providers,
    build_prompt=build_prompt,
    parse_response=parse_response,
    solve=make_solver(),
    repeats=5,
    temperature=0.0,
    seed=20260922,
)

made = sweep.run(cases, targets)
print(f"{made} call(s), {budget.describe()}")
```

## 6. Resume

Run it again. Calls already in the ledger are skipped, so an interrupted sweep continues where it
stopped and costs nothing for the work already done.

```python
sweep.run(cases, targets)   # 0 calls if nothing is left
```

## 7. Read the gap

```bash
copela report runs.jsonl
```

```
gap report
============================================================

  anthropic/claude-sonnet-5 [optimization]  ran 0.550 [0.342, 0.742] over n=20  faithful 0.500 [0.299, 0.701] over n=20  gap +0.050
  anthropic/claude-haiku-4-5 [optimization]  ran 0.250 [0.112, 0.469] over n=20  faithful 0.200 [0.081, 0.416] over n=20  gap +0.050
```

That is real output, from the ledger Enunciado publishes. This guide used to show two invented
rows (n=50, a local model that was never run) with the intervals elided, which in a tool whose
subject is unverified numbers is the one thing a guide must not do.

Read the gap, not the ran rate. The ran rate is the number that is already reported everywhere and
it is the one that overstates.

## A dry run that costs nothing

```python
from copela import StubProvider

providers = {"stub": StubProvider(default=json.dumps(reference.to_json()))}
sweep.run(cases, [Target("stub", "stub-small")])
```

The stub ships in the package rather than the test tree, because exercising the whole loop before
spending anything is worth having in the tool.
