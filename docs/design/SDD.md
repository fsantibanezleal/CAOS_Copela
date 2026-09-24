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

One interface, several backends: Anthropic and Groq through their SDKs; Z.AI and DeepSeek over
their OpenAI-shaped endpoints in plain HTTP; and local open-weight models through Ollama. No provider
name appears anywhere outside `providers/`.

Two behaviours are the seam's rather than any one vendor's, because they decide what a ledger row
means. A reasoning model that spends its output cap on reasoning and answers nothing is reported as
that truncation, with the length of the reasoning, never as an empty response (R-022). And the model
recorded is the one the server says it ran, which is not always the one requested: an endpoint
served GLM-5.3 to a request for GLM-5.2 (R-023).

This is a requirement rather than tidiness. The simulation-modelling benchmark reports that **no
single model dominates across engine types**, so a result claimed from one model contradicts a
published finding.

## 6. The run ledger

Every call appends one JSONL record carrying: case id, family, provider, model id, model version,
temperature, seed, provider fingerprint, prompt digest, repeat index, latency, token counts,
estimated cost, the raw response digest, every layer's verdict, and, from schema 1.1, the copela
version that scored it and the output cap it ran at (R-033), and, from schema 1.2, the candidate's
document whole whenever the response parsed (R-034).

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

The guard can only bound what it can price, and only as tightly as its projection. So a target
with no price is refused before the first call (R-024), and each call is projected at the most it
can bill, its output cap, rather than at a typical length (R-025).

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

R-017  WHEN a candidate and its reference solve the same case to different optima, THE structural
       layer SHALL report FAIL.
       Gate: tests/test_sweep.py::test_a_different_optimum_refutes_equivalence

R-018  WHEN a candidate and its reference solve to the same optimum but differ in canonical form,
       THE structural layer SHALL report UNDECIDED, and SHALL NOT report PASS.
       Gate: tests/test_sweep.py::test_a_matching_optimum_does_not_prove_equivalence

R-019  IF the configured solver cannot express a candidate, THEN THE report SHALL exclude that call
       from both rates and count it as unmeasured.
       Gate: tests/test_report.py::test_an_unmeasurable_run_leaves_the_rates_rather_than_counting_against_the_model

R-020  WHEN a candidate states the reference's objective in the opposite sense with its expression
       negated, THE structural layer SHALL NOT report FAIL.
       Gate: tests/test_sweep.py::test_a_sense_flipped_rewrite_is_not_refuted

R-021  IF a candidate's executable layer did not pass, THEN THE verdict SHALL NOT be faithful, whatever
       the strong layers report.
       Gate: tests/test_report.py::test_a_candidate_that_never_ran_cannot_be_faithful

R-022  IF a model returns reasoning and no answer, THEN THE provider SHALL return a text stating that
       truncation and the length of the reasoning, and SHALL NOT return an empty response.
       Gate: tests/test_providers.py::test_reasoning_with_no_answer_is_a_truncation_on_every_lane

R-023  WHEN a server reports the model it ran, THE completion SHALL carry that name as the model
       version, whatever name was requested.
       Gate: tests/test_chat_providers.py::test_the_served_model_name_is_kept_when_it_differs_from_the_request

R-024  IF a target's provider has no price for its model, THEN THE sweep SHALL refuse to start, before
       any call is made.
       Gate: tests/test_budget.py::test_an_unpriced_model_is_refused_before_any_call

R-025  WHILE a sweep is running, THE budget guard SHALL project each call at its output cap, and SHALL
       NOT project it at a typical output length.
       Gate: tests/test_budget.py::test_the_projection_bounds_a_call_that_fills_its_cap

R-026  WHEN the local lane makes a call, THE provider SHALL request a context that holds the prompt and
       the whole output cap, and IF the model's window cannot, THEN THE provider SHALL refuse the call.
       Gate: tests/test_providers.py::test_the_local_lane_sizes_its_context_to_hold_the_cap

R-027  WHERE a local model does not reason, THE provider SHALL NOT send or record a reasoning switch.
       Gate: tests/test_providers.py::test_a_model_that_does_not_reason_gets_no_reasoning_switch

R-028  WHEN the local lane makes a call, THE completion SHALL carry the digest of the weights behind
       the tag as part of the model version.
       Gate: tests/test_providers.py::test_the_local_lane_records_the_weights_it_ran

R-029  WHEN a candidate and its reference are both infeasible and differ in canonical form, THE
       structural layer SHALL report UNDECIDED, and its detail SHALL say both are infeasible rather
       than name an optimum.
       Gate: tests/test_sweep.py::test_two_infeasible_models_are_described_as_infeasible_not_as_one_optimum

R-030  IF a candidate with an objective is unbounded, THEN THE executable layer SHALL NOT pass it.
       Gate: tests/test_sweep.py::test_an_unbounded_candidate_does_not_run

R-031  WHEN a candidate is unbounded and its reference has an optimum, or the reverse, THE structural
       layer SHALL report FAIL.
       Gate: tests/test_sweep.py::test_an_unbounded_candidate_is_refuted_against_a_reference_with_an_optimum

R-032  IF a candidate is unbounded, THEN THE property layer SHALL report not-applicable, and SHALL NOT
       report FAIL.
       Gate: tests/test_sweep.py::test_an_unbounded_candidate_leaves_the_relations_unevaluated

R-033  WHEN a sweep records a call, THE record SHALL carry the copela version that scored it and the
       output cap the call ran at.
       Gate: tests/test_ledger.py::test_a_sweep_records_its_harness_and_its_cap

R-034  WHEN a response parses into a problem, THE record SHALL carry the problem's document whole, and
       SHALL carry none for a response that did not parse.
       Gate: tests/test_ledger.py::test_a_sweep_records_the_candidate_document
```

R-013 to R-033 were added after the fact, which is worth recording rather than tidying away. The corpus
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

R-017 and R-018 came from auditing the first real frontier measurement against the kill criterion
in section 11. Haiku 4.5 reported a gap of exactly zero, and the audit found why: the structural
layer returned UNDECIDED on **every** candidate that ran, so the entire faithfulness rate rested on
internal invariants that had never failed anything. A rate carried by a check that cannot fail is
not a measurement.

The fix is the one conclusive direction that was missing. Canonical inequality proves nothing, but
two formalizations of the same case that solve to different optima are not the same model, and that
IS conclusive. The asymmetry is deliberate and is the honest part: a matching optimum never promotes
a verdict to PASS, because compensating errors reach the right number, which is the failure the
anchor survey documents.

R-020 came from documenting R-017 against the code. The comparison took the two optimal values raw,
so a candidate that maximises the negative of the cost where the reference minimises the cost, the
same model written the other way round, solves to -z against z and was refuted as a different
optimum. That is a false FAIL on a style rewrite, the exact error the layer's asymmetry exists to
avoid. Both values are now read in the minimising sense before they are compared. A candidate that
optimises the same expression the wrong way is still refuted, unless its optimum is exactly the
negative of the reference's, in which case it reads as UNDECIDED, never as PASS. Neither refutation
in the published ledger changes: both compare values of the same sign, which differ under either
reading. The calls that did not fail keep no document, so whether any of them would now be refuted
cannot be re-checked; one would have had to optimise in the opposite sense and still land exactly on
the reference's value.

R-022 to R-025 came from adding the first providers outside Anthropic, and all four from smoke runs
rather than from reading. R-022 generalises what the local lane already did after qwen3.5:4b spent
every call on reasoning and answered nothing: the hosted reasoning models bill reasoning as output
under the same cap, so the same truncation had to be reported the same way. R-023 came from the Z.AI
coding endpoint answering a request for GLM-5.2 with GLM-5.3. R-024 and R-025 are one finding about
the guard, which had been correct only for the models it was written against. It projected a call at
1200 output tokens, and the first two reasoning models measured spent 5206 and 7931 on one case, so
it could pass a call it should have refused. And a model missing from a price table was projected at
zero and then charged at zero, so the budget never moved while the calls were billed; Z.AI's own
catalogue lists a model its pricing page does not price, so that was one typo away.

R-026 to R-028 came from preparing the first sweep of a local fleet, and R-026 is the one that
matters. The local lane never set a context, so the server chose one from the GPU's memory, 4096
tokens on an 8 GB card, whatever `max_tokens` said. A generation that outgrows the window is not
stopped: the server shifts the context and the model goes on writing with the start of its prompt
gone. Measured on qwen3:4b and the first corpus case, the default window gave 942 prompt tokens and
6109 generated, finishing "stop" with an answer a fifth the length of a formalization; a window that
held the cap gave all 8192 tokens of reasoning and no answer. The two are different measurements,
and only the second is the one the protocol states. The local lane's earlier result, about 3100
tokens of reasoning and no answer per call on qwen3.5:4b, ran in the default window, so it says
nothing about the cap it was blamed on. R-027 came from the same preparation: the server accepts a
reasoning switch on a model with no reasoning and ignores it, so recording `think=False` there
claimed a control that did not exist. R-028 because a tag is a name that can be re-pulled onto
other weights, and the ledger kept only the name.

R-029 came from classifying the first sweeps outside Anthropic. On Enunciado's contradictory case,
opt-019, both Claude candidates were infeasible, like the reference, and the structural detail read
"both solve to the same optimum" for a pair with no optimum at all.

R-030 to R-032 came from checking the first property-layer refutation the ledger had ever recorded,
before publishing it as one. It was not one. deepseek-r1:8b's candidate for opt-006 was unbounded:
the solver wrapper reports that as a feasible point with no objective value, so the executable layer
passed it, the structural layer fell through to "both solve to the same optimum" against a
reference that solves to 16.667, and the objective-scaling relation, finding no argmin to compare,
reported FAIL. Three layers were wrong about one record, each in a way that looked like a finding.
Running now means reaching an optimum, or a feasible point for a model with no objective; an
unbounded candidate against a reference with an optimum is refuted, which is conclusive; and the
relations report that they had nothing to compare.

R-033 came from the same day. Enunciado's one ledger held records scored by copela 0.2.0, 0.3.0 and
0.3.2, which judge an unbounded candidate differently after 0.3.3, and nothing in a record said which
one had scored it; and its report had to assume the output cap, because a record could not state
its own. Records now carry both. A record written before schema 1.1 loads with both empty, which a
reader must take as unknown.

R-034 came from Enunciado's finished measurement. The ledger kept a digest of every response and an
excerpt of the failed ones, so 30 of its 34 faithful verdicts rested on the property layer alone with
no way to apply a stronger check to them later, and two refutations turned out to be candidates that
counted in whole units against a continuous reference, which could be established only because the
excerpts of those failures happened to keep the declarations. A record now carries the document the
verdicts were reached on.

## 10. Convergence

Recorded for 0.01.000 on 2026-09-22, per ADR-0075.

| Requirement | Result |
|---|---|
| R-001 to R-033 | all pass, no skips (0.04.000) |
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
- **A contradictory case cannot be passed.** The executable layer counts only a feasible optimum
  as a run, so a candidate that proves a contradictory case infeasible, which is the right answer,
  is recorded as a failure to run, and no strong layer can then pass it: agreeing on infeasibility
  proves no more than agreeing on a value (R-029). Counting proven infeasibility as a run would need
  a structural check able to pass such a case, such as comparing irreducible infeasible subsystems
  through provenance, or it would move a correct answer into the gap. Open, and a decision rather
  than a fix, because either change moves published rates.

## 12. Deploy driver

Not applicable. A library and a CLI, published to PyPI.
