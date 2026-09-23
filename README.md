# copela

[![PyPI](https://img.shields.io/pypi/v/copela.svg)](https://pypi.org/project/copela/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Run narrative-to-formal translation across many language models, and score the result with oracles
that are **not** language models.

The name is the cupel used in fire assay: the vessel that separates the metal from the lead. That is
the job here, separating a formalization that is faithful from one that merely runs.

## The number this produces

```
gap report
============================================================

  anthropic/claude-sonnet-5 [optimization]  ran 0.550 [0.342, 0.742] over n=20  faithful 0.500 [0.299, 0.701] over n=20  gap +0.050
  anthropic/claude-haiku-4-5 [optimization]  ran 0.250 [0.112, 0.469] over n=20  faithful 0.200 [0.081, 0.416] over n=20  gap +0.050
```

That is the published measurement, re-derived by this release from its committed ledger with
`copela report`: twenty authored optimization cases, two models, one repeat each, forty calls,
1.23 USD, measured 2026-09-22 ([Enunciado](https://enunciado.fasl-work.com/benchmark)). **ran**
is what the field reports. **faithful** is what was asked for. The gap between them is the
output, and no source found reports it across target families.

An earlier README showed a Haiku 4.5 pass over the same corpus at ran 0.350 and gap +0.100. That
run was real and is superseded: Enunciado keeps it as the ledger from before an instrument fix,
and the distance between the two passes fits inside their intervals, which is what the interval
is for.

Twenty cases at one repeat is a wide interval. It is enough to see a gap and not enough to rank
close models, which is exactly why the interval is printed next to the number.

That gap is not hypothetical. Where it has been measured carefully, in natural-language to Lean
formalization, it runs [3.0 to 29.0 percentage points](https://arxiv.org/abs/2606.31002), and the
strongest system measured had the largest gap: 89.5% compiling, 60.5% faithful.

## Four layers, never merged

| Layer | Asks | Strength |
|---|---|---|
| **executable** | did it run, solve, compile | necessary, weak, the layer the field over-reports |
| **structural** | is it the same model as the reference | the only layer that can refute |
| **property** | do the invariants of this class hold | strong, catches what structure misses |
| **judge** | what would a model say | a labelled screening aggregate, never truth |

There is deliberately **no combined score**, and a test fails if anyone adds one. A single number
lets a high "it ran" rate conceal a low "it was right" rate, which is the distance this exists to
show.

The judge layer is reported because the literature reports it and comparability matters. It carries
a label on every record saying it is not an oracle, because the study that calibrated a two-judge
consensus against human majority states exactly that.

**The structural layer is the one that can say no.** Canonical equality proves equivalence; unequal
canonical form proves nothing; but two formalizations of the same case that solve to *different
optima* are not the same model, and that is conclusive. A matching optimum never promotes a verdict
to pass, because compensating errors reach the right number. Without that direction the whole
faithfulness rate rests on internal invariants that cannot fail, which is a rubber stamp with an
interval printed on it.

## The property layer

Metamorphic relations: instead of checking an exact output, check how the output **must** change
when the input changes in a controlled way.

| Relation | Guarantee |
|---|---|
| scale the objective by `k > 0` | the argmin cannot move |
| add a redundant constraint | the feasible set cannot change |
| tighten a constraint | the optimum cannot improve |

The standard objection to metamorphic testing is that the relations must be authored per problem
class and so do not generalise to arbitrary programs. That is the design here: the target families
are narrow typed classes, so the relations are written once per class.

A candidate that solves and then fails one of these is wrong in a way no solver would have reported.

## Install

```bash
pip install copela                    # the harness
pip install "copela[solvers]"         # plus Pyomo and HiGHS
pip install "copela[all]"             # plus the provider SDKs
```

## Use

```python
from copela import Budget, Case, Ledger, Sweep, Target, build
from copela.providers import get
from copela.solvers.highs import make_solver

sweep = Sweep(
    ledger=Ledger("runs.jsonl"),
    budget=Budget(limit_usd=5.00, max_consecutive_failures=10),
    providers={"anthropic": get("anthropic"), "ollama": get("ollama")},
    build_prompt=my_prompt,        # the prompt strategy is what a study varies
    parse_response=my_parser,
    solve=make_solver(),
    repeats=5,
)

sweep.run(cases, [Target("anthropic", "claude-sonnet-5"),
                  Target("ollama", "qwen3:8b")])

print(build(Ledger("runs.jsonl")).to_text())
```

From the shell:

```bash
copela models                      # what each provider serves, and what it costs
copela solve problem.json          # solve one formalization, no model involved
copela report runs.jsonl           # the gap
```

## Why many models, not one

Because a benchmark of AI-assisted modelling and simulation reports that
[no single model dominates across engine types](https://arxiv.org/abs/2605.28994), with
task-specific tradeoffs between speed and accuracy. A ranking claimed from one model contradicts a
published result, so the provider seam is a requirement rather than tidiness: Anthropic, Groq,
Z.AI, DeepSeek and local models through Ollama, behind one interface, with no vendor name anywhere
outside `copela/providers/`. A test enforces that.

| Provider | Key | What it pins |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | effort where the model takes it; no temperature or seed exists |
| `groq` | `GROQ_API_KEY` | temperature, seed, and the system fingerprint the server returns |
| `zai` | `ZAI_API_KEY`, and `ZAI_BASE_URL` for a coding-plan key | effort from GLM-5.2 up, greedy decoding for temperature 0, no seed |
| `deepseek` | `DEEPSEEK_API_KEY` | effort; temperature has no effect in thinking mode, no seed |
| `ollama` | none (`OLLAMA_HOST`) | temperature, seed, the reasoning switch where the model has one, the context it was given, and the digest of the weights |

Each records what it actually pinned, and the model the server says it ran, which is not always the
one requested. A reasoning model that spends its whole output cap on reasoning is recorded as that
truncation, with the length of the reasoning, never as an empty answer.

The local lane asks for a context that holds the prompt and the whole cap. Left to itself the server
picks one from the GPU's memory, 4096 tokens on an 8 GB card, and when a generation outgrows it the
server does not stop: it shifts the context and the model writes on without the start of its prompt.

## What reproducibility means here

Temperature zero does not make hosted inference deterministic. The dominant cause is the batch-size
dependence of reduction kernels rather than floating-point non-associativity, and bitwise
determinism costs a third to two thirds of throughput and cannot be bought over a hosted API.

So the harness pins what it can and records **what it actually pinned**, which is not the same set
for every provider: current Claude models accept no `temperature` and no `seed` at all, so a ledger
row for them says `no-temperature` and records the effort level instead of a sampling parameter
nobody set. It records `n` repeats and reports a **rate with a Wilson interval**, never presents a
single run as the result, and does not report 5 of 5 as certainly 1.0.

## The ledger

One append-only JSONL record per call, carrying its full provenance, including the copela version
that scored it and the output cap it ran at. A record is never edited, because a ledger that can be
rewritten is not evidence. It is also the resume mechanism: a sweep
reads it and skips the calls already done.

## Cost

Every sweep declares a budget and a kill criterion before it runs, and the guard refuses the call
that **would** exceed the ceiling rather than noticing afterwards.

It projects each call at the most that call can bill, its output cap, because reasoning models bill
their reasoning as output: the first two measured spent 5206 and 7931 tokens on one case. And it
refuses to start a sweep of a model it has no price for, because it would count those calls as free.

## Documentation

The wiki is in [`docs/`](docs/). The design document, written before the code, is
[`docs/design/SDD.md`](docs/design/SDD.md); each of its thirty-three requirements names the test
that verifies it.

## Related

[`planteo`](https://github.com/fsantibanezleal/CAOS_Planteo) is the representation this consumes: a
typed problem with dimensions on every quantity and provenance on every element.

## License

MIT. See [LICENSE](LICENSE).
