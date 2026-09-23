# The four layers, and why they are never merged

## The measurement

```
gap = ran rate - faithful rate
```

`ran` is what the field reports. `faithful` is what was asked. The subtraction is the product.

A candidate is `faithful` when it ran, neither strong layer (structural, property) FAILED, and at
least one of them PASSED (`Verdicts.faithful`). The last clause matters: a candidate on which both
strong layers are UNDECIDED has not been shown faithful, and is not counted as such.

It only exists while the layers are kept apart. Any weighting that produced one number would let a
high executable rate conceal a low faithfulness rate, which is the exact failure being measured. So
`CandidateVerdict` has no `score` property, `Cell` has none, `Report` has none, and
`tests/test_report.py::test_layers_are_never_combined` fails if anyone adds one.

## Layer 1, executable

Did it validate, did it solve, did it compile.

Necessary and weak. This is the layer the field over-reports, and treating it as correctness is the
problem: a formulation can reach the reference objective through compensating errors, which the
optimization-modelling survey states directly.

A candidate that never ran is still an observation. It stays in the denominator of both rates.
Dropping failures would inflate the faithful rate by quietly shrinking what it is a fraction of, and
`test_a_failed_run_stays_in_the_denominator` holds that line.

## Layer 2, structural

Is this the same model as the reference.

Implemented by `planteo`'s canonical form, which normalises names, term order and comparator
orientation. Equal canonical form proves equivalence.

**Unequal canonical form proves nothing**, so it is never a failure on its own. But it is not the
end of the comparison either, and treating it as the end was a real defect here.

Two formalizations of the *same case* that solve to **different optima** are not the same model.
That direction is conclusive, and it is the only way this layer can fail a candidate:

| Canonical form | Optima | Verdict |
|---|---|---|
| equal | (not consulted) | `PASS`, equivalence proven |
| differ | differ | `FAIL`, they are different models |
| differ | agree | `UNDECIDED`, agreement does not prove equivalence |

The optima are compared in the minimising sense: a maximum is negated first. Maximising f and
minimising -f are the same model with optimal values of opposite sign, and before 0.02.001 the raw
comparison refuted that rewrite as a different optimum (R-020). The tolerance is relative, 1e-6 of
the reference's optimum, so the last bit of two solves by different paths is not read as a defect,
and a comparison that cannot be made (either side does not solve) returns nothing rather than a
verdict.

The asymmetry in the last two rows is the honest part. A matching optimum never promotes a verdict
to `PASS`, because **compensating errors reach the right number**, which is precisely the failure
the anchor survey documents.

**Why this exists.** The first version of this layer stopped at `UNDECIDED`, and on the first real
frontier measurement it returned `UNDECIDED` on *every single* candidate that ran. The whole
faithfulness rate therefore rested on internal invariants that had never failed anything, and the
reported gap was exactly `+0.000`. A rate carried by a check that cannot fail is not a measurement.
With refutation added, the published measurement (twenty cases, two models, forty calls) holds two
refutations: a Haiku 4.5 candidate that solves to 16 where its reference solves to 16.667, and a
Sonnet 5 candidate that solves to 8080 against 8200. Each model's gap is `+0.050`. The layer still
returned `PASS` on none of the sixteen candidates that ran, so the other fourteen faithful verdicts
rest on the property layer.

If a case has no reference formalization, this layer reports `NOT_APPLICABLE` instead of inventing
an opinion.

## Layer 3, property

Do the invariants of this class hold. See
[`02_property_relations.md`](02_property_relations.md).

## Layer 4, judge

What a language model says about the formalization.

Present for one reason: the literature reports judge-based scores, and a harness that cannot produce
a comparable number is harder to place against published work.

It is **not** an oracle, and it never contributes to the faithful rate
(`test_the_judge_layer_never_counts_towards_faithful`). Every judge verdict carries a label saying
so, and `LayerResult` refuses to construct a judge verdict without one.

The reason is not caution, it is a citation: the study that calibrated a strict two-judge consensus
against human majority judgments, reaching 89.7% agreement with a 95% interval of 82.1 to 94.3,
concludes that LLM judging is useful as a human-calibrated conservative aggregate measure and not as
an equivalence oracle. A harness built on a model grading itself would contradict its own source.

## Outcomes

| Outcome | Means |
|---|---|
| `PASS` | the check ran and the candidate satisfied it |
| `FAIL` | the check ran and the candidate violated it |
| `UNDECIDED` | the check ran and could not decide (structural inequality) |
| `NOT_APPLICABLE` | the check could not be evaluated at all |

`NOT_APPLICABLE` exists so that an unevaluated check is never counted as a pass. That distinction is
the difference between reporting a measurement and reporting a number.

## Rates

Every figure is a rate over `n` repeats with a Wilson interval.

Wilson rather than the normal approximation because the boundaries are where this matters: 5 of 5
must not be reported as certainly 1.0, and 0 of 5 must not be reported as certainly 0.0. Both are
tested.

A single run is not a result, because hosted inference is not deterministic even at temperature
zero. The dominant cause is the batch-size dependence of reduction kernels rather than
floating-point non-associativity, and bitwise determinism costs roughly a third to two thirds of
throughput and cannot be purchased over a hosted API at all. So the harness pins what it can, and
reports uncertainty instead of pretending.
