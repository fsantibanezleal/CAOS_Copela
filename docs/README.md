# copela documentation

| Theme | What it covers |
|---|---|
| [`design/`](design/) | The software design document, written before the code. Forty-four requirements, each naming its test. |
| [`architecture/`](architecture/) | The four layers, the property relations, the dynamics layers, and why each is shaped that way. |
| [`guides/`](guides/) | How to run a sweep, and how to add a property relation. |

## Where to start

- To run something: [`guides/01_run_a_sweep.md`](guides/01_run_a_sweep.md).
- To understand the design: [`architecture/01_the_four_layers.md`](architecture/01_the_four_layers.md).
- To see how a family with no optimum is scored: [`architecture/03_dynamics.md`](architecture/03_dynamics.md).
- To extend it: [`architecture/02_property_relations.md`](architecture/02_property_relations.md#adding-a-relation-for-a-new-family)
  and [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

## What this is, and is not

**It is** a harness: it runs a translation across models, scores it with oracles that are not models,
and writes an auditable ledger.

**It is not** a formalizer (the prompt strategy is an argument, not the product), a representation
(that is `planteo`), a trainer (nothing here fits a model), or a leaderboard service.

It is also not an equivalence oracle, and the judge layer says so on every record it writes.
