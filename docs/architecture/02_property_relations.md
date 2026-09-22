# Property relations

## The oracle problem, and the way around it

A formalization is correct when it means what the narrative said. There is no general decision
procedure for that, and the two cheap substitutes both fail: the executable check misses most of the
gap, and a language-model judge is not an equivalence oracle by its own authors' statement.

Metamorphic testing is the recognised route around an absent oracle. Instead of checking an exact
output, check how the output **must** change when the input changes in a controlled way.

Its standard limitation is that the relations have to be identified per problem class, which is
human work and does not generalise to arbitrary programs.

**That limitation is why this works here.** These targets are not arbitrary programs. They are
narrow typed classes, so the relations are authored once per class and then apply to every case in
it. The objection in the literature becomes the design.

## The optimization relations

| Relation | Guarantee | Why a violation is damning |
|---|---|---|
| `objective-scaling` | scaling the objective by `k > 0` cannot move the argmin | if the argmin moves, the objective is not what the model thinks it is |
| `redundant-constraint` | restating a variable's own bound cannot change the feasible set | if the optimum moves, the model is sensitive to something that says nothing |
| `tightening` | demanding more cannot improve a minimum | if the optimum falls, a constraint is not binding the way the model claims |

A candidate that solves and then fails one of these is wrong in a way **no solver would have
reported**, which is the entire point.

## Two details that were wrong first, and are worth stating

**A redundant constraint must contain a variable.** The obvious version, `0 <= 1`, is not a
constraint at all: it collapses to a boolean and a modelling layer rejects it. The relation has to
add a row the solver actually carries while changing nothing, so it restates an existing variable's
bound. This was caught by the test suite rather than by review.

**Tightening into infeasibility is allowed.** Demanding more until nothing satisfies it is a
legitimate outcome, not a violated guarantee, so `_cannot_improve` returns a pass in that case. A
check that flagged it would fail correct candidates on hard instances.

## Not-applicable is not a pass

If the candidate never solved, no relation could be evaluated, and the layer reports
`NOT_APPLICABLE`. If a specific relation has nothing to transform, that relation reports
`NOT_APPLICABLE` and the others continue.

Counting either as a pass would report a number that was never measured. This is R-009 and it has
its own gate.

## The kill criterion

A property layer that never fails anything is decoration.

The SDD states the criterion plainly: if the property layer never fails a candidate that the
structural layer passed, it is either strengthened or removed, not kept for appearances. The
negative control (`test_the_relations_actually_catch_a_broken_solver`) proves the machinery can
fail, which is the minimum evidence that a green result from it means anything.

That is also the rule for contributions: a new relation ships with a test proving it catches a
violation, not only a test proving it passes on a correct candidate.

## Adding a relation for a new family

Each family gets its own set, authored once:

- **dynamics**: dimensional consistency, conservation, known limiting cases, invariance under unit
  change, monotonicity where the physics requires it.
- **experiment design**: a control exists, every hypothesis has a test that can reject it, the metric
  is a function of the stated outcome, the randomisation unit and the analysis unit agree.
- **learning**: the target is computable from data available at prediction time, the split is
  leakage-safe against the stated grouping, label permutation destroys performance.

The last one in each list is a negative control, and it is the most valuable item in the set.
