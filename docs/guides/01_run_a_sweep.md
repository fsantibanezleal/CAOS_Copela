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

A sweep also stops by itself when a call cannot reach the provider: a refused connection, a name
that does not resolve, or a key the provider rejects raises `ProviderUnreachable`, and that call is
not recorded, because it says nothing about the model. Fix the connection or the key and run it
again; it picks up at the call that failed. A provider's own error, an HTTP 500, is its answer to
that call and is recorded like any failure.

```python
sweep.run(cases, targets)   # 0 calls if nothing is left
```

## 7. What each record keeps

One JSON line per call:

- the provenance: model, version, temperature, seed, fingerprint, prompt digest and repeat;
- the cost and the tokens;
- every layer's verdict;
- the copela version that scored the call and its output cap (`harness`, `max_tokens`);
- an excerpt of the response when the call failed;
- from 0.5.0, the candidate's document whole whenever the response parsed (`candidate`).

The document is what lets a check written after the sweep be applied to what the model wrote, rather
than only to the verdicts about it:

```python
from planteo import Problem

for record in Ledger("runs.jsonl"):
    if record.candidate is not None:
        problem = Problem.from_json(record.candidate)   # the same problem the layers judged
```

A record from before 0.5.0 has no document, and reads `None`.

## 8. Read the gap

```bash
copela report runs.jsonl
```

```
gap report
============================================================

  ollama/gemma3:12b [optimization]  ran 0.158 [0.055, 0.376] over n=19  faithful 0.000 [0.000, 0.168] over n=19  gap +0.158  (1 unmeasured, the solver could not express them)
  ollama/deepseek-r1:8b [optimization]  ran 0.200 [0.081, 0.416] over n=20  faithful 0.100 [0.028, 0.301] over n=20  gap +0.100
  ollama/qwen3:14b [optimization]  ran 0.200 [0.081, 0.416] over n=20  faithful 0.100 [0.028, 0.301] over n=20  gap +0.100
  ollama/phi4:latest [optimization]  ran 0.350 [0.181, 0.567] over n=20  faithful 0.250 [0.112, 0.469] over n=20  gap +0.100
  anthropic/claude-sonnet-5 [optimization]  ran 0.550 [0.342, 0.742] over n=20  faithful 0.500 [0.299, 0.701] over n=20  gap +0.050
  anthropic/claude-haiku-4-5 [optimization]  ran 0.250 [0.112, 0.469] over n=20  faithful 0.200 [0.081, 0.416] over n=20  gap +0.050
  deepseek/deepseek-v4-pro [optimization]  ran 0.100 [0.028, 0.301] over n=20  faithful 0.100 [0.028, 0.301] over n=20  gap +0.000
  ollama/qwen2.5-coder:7b [optimization]  ran 0.050 [0.009, 0.236] over n=20  faithful 0.050 [0.009, 0.236] over n=20  gap +0.000
  zai/glm-4.5-flash [optimization]  ran 0.050 [0.009, 0.236] over n=20  faithful 0.050 [0.009, 0.236] over n=20  gap +0.000
  zai/glm-5.3 [optimization]  ran 0.350 [0.181, 0.567] over n=20  faithful 0.350 [0.181, 0.567] over n=20  gap +0.000
  ollama/gemma3:4b [optimization]  ran 0.000 [0.000, 0.161] over n=20  faithful 0.000 [0.000, 0.161] over n=20  gap UNDEFINED, nothing reached the faithfulness layers
  ollama/llama3.1:8b [optimization]  ran 0.000 [0.000, 0.161] over n=20  faithful 0.000 [0.000, 0.161] over n=20  gap UNDEFINED, nothing reached the faithfulness layers
  ollama/mistral:7b [optimization]  ran 0.000 [0.000, 0.161] over n=20  faithful 0.000 [0.000, 0.161] over n=20  gap UNDEFINED, nothing reached the faithfulness layers
  ollama/phi4-mini:latest [optimization]  ran 0.000 [0.000, 0.161] over n=20  faithful 0.000 [0.000, 0.161] over n=20  gap UNDEFINED, nothing reached the faithfulness layers
  ollama/qwen3:4b [optimization]  ran 0.000 [0.000, 0.161] over n=20  faithful 0.000 [0.000, 0.161] over n=20  gap UNDEFINED, nothing reached the faithfulness layers
  ollama/qwen3:8b [optimization]  ran 0.000 [0.000, 0.161] over n=20  faithful 0.000 [0.000, 0.161] over n=20  gap UNDEFINED, nothing reached the faithfulness layers
```

That is real output, from the ledger Enunciado publishes, in full: sixteen models, sorted by the
gap. This guide used to show two invented rows (n=50, a local model that was never run) with the
intervals elided, which in a tool whose subject is unverified numbers is the one thing a guide must
not do. A row reads `UNDEFINED` when nothing the model wrote ran, because a gap between two rates
that are both zero says nothing, and `unmeasured` counts the candidates the configured solver could
not express, which leave both rates rather than counting against the model.

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
