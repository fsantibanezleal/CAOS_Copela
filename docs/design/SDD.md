# copela, software design document

Written before any code, per ADR-0075. Status: draft for review. Date: 2026-09-22.

## 1. Problem

A language model turns a narrative into a formalization. Whether that formalization is *right* is
the open question, and the checks in current use answer a weaker one.

`copela` runs the translation across many models, scores the result with oracles that are not
language models, and reports the layers separately so the gap between them is visible.

The name is the cupel used in fire assay: the vessel that separates the metal from the lead. That is
the job, separating a formalization that is faithful from one that merely runs.

## 2. Non-goals

- **Not a formalizer.** It orchestrates models; it does not contain a better prompt as its product.
- **Not a representation.** The `Problem` object is `planteo`; this consumes it.
- **Not a trainer.** No fine-tuning, no gradient ever runs here. The harness measures models.
- **Not a leaderboard service.** It produces run ledgers and tables. Publishing them is elsewhere.
- **No bitwise reproducibility claim.** See section 7.

## 3. The core design decision: four layers, reported separately, never merged

| Layer | What it asks | Strength |
|---|---|---|
| 1. Executable | did it run, solve, compile | necessary, weak, the layer the field over-reports |
| 2. Structural | is it the same model as the reference | strong where it applies |
| 3. Property | do the invariants of this class hold | strong, catches what structure misses |
| 4. Judge | what would a model say | a labelled screening aggregate, never truth |

**These are never combined into one score.** A single number would hide exactly the gap the harness
exists to measure. The reported headline is `layer 1 pass rate` minus `layers 2 and 3 pass rate`.

Layer 4 is included because the literature reports it and comparability matters, and it is labelled
in every output because the study that calibrated it states plainly that LLM judging is a
human-calibrated conservative aggregate measure and not an equivalence oracle. A harness that
contradicted its own sources would be the failure it is measuring.

## 4. Property relations, authored once per class

Metamorphic testing is the recognised way past an absent oracle: instead of checking an exact output,
check how the output must change when the input changes in a controlled way. Its known limitation is
that the relations must be identified per problem class, which does not generalise to arbitrary
programs.

That limitation does not bite here, and the reason is the design: the target families are narrow
typed classes, not arbitrary programs, so the relations are authored once per class.

For optimization, available by construction:

| Relation | Expectation |
|---|---|
| scale the objective by `k > 0` | the argmin is unchanged |
| tighten a binding constraint | the optimum cannot improve |
| relax a constraint | the optimum cannot worsen |
| permute variable and constraint order | identical solution set |
| add a redundant constraint | the feasible set is unchanged |
| LP duality | the dual bound certifies the primal optimum |

A formalization that passes layer 1 and fails a property relation is wrong in a way no solver would
have reported.

## 5. The provider seam

One interface, several backends: Anthropic, Groq, and local open-weight models through Ollama. No
provider name appears anywhere outside `providers/`.

This is a requirement rather than tidiness. The simulation-modelling benchmark reports that **no
single model dominates across engine types**, so a result claimed from one model contradicts a
published finding.

## 6. The run ledger

Every call appends one JSONL record carrying: case id, family, provider, model id, model version,
temperature, seed, provider fingerprint, prompt digest, repeat index, latency, token counts,
estimated cost, the raw response digest, and every layer's verdict.

Append-only. A run is never edited, because a ledger that can be rewritten is not evidence.

## 7. What reproducibility means here, honestly

Temperature zero does not make inference deterministic. The dominant cause is the batch-size
dependence of reduction kernels rather than floating-point non-associativity, and bitwise determinism
costs roughly a third to two thirds of throughput and cannot be bought over a hosted API at all.

So the harness pins what it can (model, version, temperature, seed, fingerprint), records `n`
repeats per case, and reports a **rate with an interval**, never a single run presented as the
answer. Anything that claims exact reproduction of a hosted call is wrong.

## 8. Cost discipline

Every sweep declares a budget and a kill criterion before it runs. The ladder is cheap-first: local
models, then small hosted models, then frontier models on the reduced set. The ledger carries the
running cost and the sweep stops at the budget rather than after it.

## 9. Requirements

```
R-001  THE harness SHALL report the executable, structural and property layers as separate
       verdicts, and SHALL NOT emit a combined score.
       Gate: tests/test_report.py::test_layers_are_never_combined

R-002  WHEN a judge verdict is recorded, THE record SHALL carry the label identifying it as a
       screening aggregate rather than an oracle.
       Gate: tests/test_report.py::test_judge_verdict_is_labelled

R-003  WHEN a run is executed, THE ledger SHALL record model id, model version, temperature, seed,
       provider fingerprint, repeat index and prompt digest for every call.
       Gate: tests/test_ledger.py::test_every_call_pins_its_provenance

R-004  THE ledger SHALL be append-only; a write that would modify an existing record SHALL be
       refused.
       Gate: tests/test_ledger.py::test_ledger_refuses_to_rewrite

R-005  WHILE a sweep is running, THE harness SHALL stop before exceeding its declared budget.
       Gate: tests/test_budget.py::test_sweep_stops_before_the_budget

R-006  WHERE a provider is selected, THE harness SHALL reach it only through the provider interface,
       and no provider name SHALL appear outside the providers package.
       Gate: tests/test_providers.py::test_no_provider_name_leaks_outside_the_seam

R-007  WHEN the objective of a problem is scaled by a positive constant, THE property oracle SHALL
       require the argmin to be unchanged.
       Gate: tests/test_properties.py::test_objective_scaling_preserves_argmin

R-008  WHEN a constraint is tightened, THE property oracle SHALL require the optimum not to improve.
       Gate: tests/test_properties.py::test_tightening_cannot_improve_the_optimum

R-009  IF a property relation cannot be evaluated because the candidate failed to run, THEN THE
       oracle SHALL report not-applicable rather than pass.
       Gate: tests/test_properties.py::test_unevaluable_relation_is_not_a_pass

R-010  THE harness SHALL report a rate with an interval over n repeats, and SHALL NOT report a
       single run as the result.
       Gate: tests/test_report.py::test_rate_carries_an_interval

R-011  IF a provider returns a response that does not parse into a Problem, THEN THE harness SHALL
       record an executable-layer failure with the parse error, and SHALL NOT discard the run.
       Gate: tests/test_report.py::test_unparseable_response_is_a_recorded_failure

R-012  THE offline sweep SHALL be resumable from its ledger without repeating completed calls.
       Gate: tests/test_ledger.py::test_completed_calls_are_not_repeated

R-013  IF a model is infeasible, THEN THE solver wrapper SHALL return a result recording that,
       and SHALL NOT raise.
       Gate: tests/test_solvers.py::test_an_infeasible_model_returns_a_result_rather_than_raising

R-014  WHILE a sweep holds a ledger exclusively, THE harness SHALL refuse a second writer of that
       ledger.
       Gate: tests/test_ledger.py::test_two_sweeps_cannot_share_one_ledger

R-015  WHEN a call fails, THE ledger SHALL record a bounded excerpt of the response.
       Gate: tests/test_ledger.py::test_a_failing_response_is_excerpted_for_diagnosis

R-016  IF nothing reached the faithfulness layers, THEN THE report SHALL state the gap as
       UNDEFINED, and SHALL NOT report it as zero.
       Gate: tests/test_report.py::test_a_gap_with_nothing_running_is_undefined_not_zero
```

R-013 to R-016 were added after the fact, which is worth recording rather than tidying away. The corpus
contains deliberately contradictory cases, because noticing that a problem has no answer is part of
what is being measured. The first such case turned the correct verdict into a harness crash, and the
cause was subtle: the modelling layer copies its own `load_solutions` argument over the config
setting on every call, so suppressing the load through the config is silently discarded.

R-014 came from an incident during the first real sweep: a second sweep was started while an
earlier one was still alive, both appended to one ledger, and the file ended up interleaving
records from two versions of the code. Append-only does not catch that, because the two processes
write different keys and nothing collides. R-015 came from the same incident: diagnosing it was
impossible from a digest, and re-running does not reproduce a failure that inference is not
deterministic about.

R-016 came from the first completed sweep. A local model failed all ten calls and the report read
`gap +0.000`, which says "no gap" and means "no measurement". Confusing those two is the exact
failure this product exists to expose, so making it here would be unforgivable. The gap is now
undefined when nothing ran, and the text output says so in words.

## 10. Convergence

Recorded for 0.01.000 on 2026-09-22, per ADR-0075.

| Requirement | Result |
|---|---|
| R-001 to R-016 | all pass, no skips |
| The SDD gate | `scripts/check_sdd.py` passes; every named gate exists |
| Lint | ruff clean |

Two gates caught real defects during the build rather than after it, which is the evidence that they
measure something:

- the property layer's redundant-constraint relation emitted a constant comparison, which is not a
  constraint at all and which the modelling layer rejected as a trivial boolean; it now restates a
  variable's own bound
- the provider-seam test caught vendor names hardcoded as a default list in the command line; the
  list is now read from the registry

Out of scope and therefore not claimed: the judge layer has its label and its exclusion from the
faithful rate tested, but no judge implementation ships in this release; the dynamics, experiment
and learning property relations are specified in the docs and not implemented. Neither has
requirements here, which is the honest state rather than requirements marked pending.

## 11. Risks and kill criteria

- **The structural oracle is too weak.** `planteo`'s canonical form only proves equivalence, never
  difference. Mitigation: a `NOT_PROVEN_EQUIVALENT` result falls through to the property layer rather
  than being counted as a failure. Kill criterion: if most disagreements are canonicalisation
  artifacts rather than real differences, the layer moves to graph isomorphism.
- **Property relations turn out to be too few to catch anything.** Kill criterion: if the property
  layer never fails a candidate that the structural layer passed, it is decoration and is either
  strengthened or removed, not kept for appearances.
- **Cost.** Bounded by section 8, enforced by R-005.

## 12. Deploy driver

Not applicable. A library and a CLI, published to PyPI.
