---
name: run-sweep
description: >-
  Run a narrative-to-formal sweep with copela: many models, one authored corpus,
  an append-only ledger, and a report that keeps "it ran" apart from "it was the
  model the statement described". Use when measuring how faithfully language models
  formalize problem statements, when adding a model or a repeat to an existing
  measurement, or when resuming an interrupted sweep. Ships a runner that makes every
  refusal before anything is spent and never records a call that did not reach the
  model.
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
metadata:
  version: 0.1.0
---

# Run a narrative-to-formal sweep

A sweep asks each model to formalize each case, scores every answer with oracles that are not
language models, and appends one record per call to a ledger. The number it produces is the **gap**
between how often a formalization ran and how often it was also faithful. Everything in this skill
comes from running Enunciado's measurement (sixteen models, four providers, two repeats) and from
what went wrong while doing it.

## What you need

- `pip install "copela[solvers]"` (the solvers extra brings Pyomo and HiGHS).
- A **study** file: `cases()`, `build_prompt(case)`, `parse_response(text, case)`, and optionally
  `solver()`. [`assets/example_study.py`](assets/example_study.py) is a working one.
- For a hosted model, its API key in the environment (`ANTHROPIC_API_KEY`, `ZAI_API_KEY`,
  `DEEPSEEK_API_KEY`, `GROQ_API_KEY`); for a local one, an Ollama server with the model pulled.

## Procedure

### 1. Author the corpus before any model sees it

Every case carries its reference formalization, and the reference is written and committed **before**
any model's answer is read. A reference edited after reading answers measures the author's agreement
with the model. If a case turns out to be ambiguous after answers exist, do not edit it: publish what
the refutation rests on, and fix the next corpus version, written blind.

### 2. Declare the protocol, then keep it

Fix and write down: the output cap (`--max-tokens`), the repeats, temperature or the provider's
greedy switch, the seed, the reasoning effort. One ledger per protocol: the ledger's key is (case,
provider, model, repeat), so a second cap in the same file would be skipped as already done or would
silently change what a row means. Put a second cap in a second ledger, named for it.

### 3. Run it with the runner

```bash
python skills/run-sweep/scripts/run_sweep.py --study my_study.py \
    --provider anthropic --model claude-haiku-4-5 \
    --ledger data/runs/optimization.jsonl --budget-usd 1.00 --repeats 1
```

The runner refuses, **before it takes the ledger's lock**, when the model has no price (the budget
could not bound it), when a paid model has no `--budget-usd`, and when one unrecorded **probe call**
fails. The probe exists because a key read wrong once raised on every call before it left the
machine, and the sweep recorded nineteen "call failed" rows against the model: rows about a key file.
Then, during the sweep, a call that never reaches the provider (a refused connection, a name that
does not resolve, a 401) stops it with exit code 4 and is **not recorded**; run the same command
again once the connection is back, and it resumes at that call. A provider's own error, an HTTP 500,
is its answer to the call and is recorded like any failure.

### 4. Resume, do not restart

Calls already in the ledger are skipped, so an interrupted sweep continues where it stopped. To add a
second repeat, run with `--repeats 2`: repeat 0 is skipped and repeat 1 is new.

### 5. Read the report, and what it rests on

```bash
copela report data/runs/optimization.jsonl
```

Read the **gap**, never the ran rate alone, and read each rate with its Wilson interval: at 20 calls a
rate of 0.5 spans about 0.40, so two models whose intervals overlap cannot be ranked. Then check what
the headline rests on:

- **The cap.** Count the calls that billed exactly the cap. A reasoning model can spend the whole
  cap reasoning and answer nothing; at 8192 tokens DeepSeek-V4-Pro was faithful on 2 of 20 and at
  32768 on 11 of 20. Such a failure is about the cap, not the formalization.
- **The refutations.** A refutation says the candidate and the reference are different models. When
  the statement leaves a choice open (whole units or fractions, for one), the reference made that
  choice, and a candidate that made the other is refuted for a reading the statement allowed. Both
  Claude gaps in Enunciado's measurement turned out to rest on exactly that.
- **The repeats.** A later repeat is a second sample only if it can differ. At temperature 0 with a
  fixed seed a local model can return its first response byte for byte; compare the response digests
  before trusting an interval over the doubled count.

## What never to do

- **Never edit or delete a published record.** The ledger is append-only evidence. A record that is
  wrong stays, and the report classes it and says so.
- **Never let two sweeps write one ledger.** The runner takes an exclusive lock; if a stopped run left
  it behind, check no process holds it before deleting the lock file.
- **Never read a key file whole.** Extract the token; a file with notes above the key produces an
  illegal header, which the probe now catches.
- **Never run a model that has not loaded.** A local model that times out on its first call writes a
  row of call failures about the machine; load-test it once, outside the ledger.
- **Never merge the layers into one score.** The report keeps them apart on purpose.
