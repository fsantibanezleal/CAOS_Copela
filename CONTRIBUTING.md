# Contributing

## The rules that are unusual here

**1. Every requirement names the gate that verifies it.** A change that adds behaviour adds an EARS
requirement to `docs/design/SDD.md`, and that requirement names the test that fails when the
behaviour is violated:

```
R-0NN  WHEN <trigger>, THE <component> SHALL <behaviour>.
       Gate: tests/test_<file>.py::test_<name>
```

"Tested" is not a gate. The name of the failing test is. `scripts/check_sdd.py` checks that the
named gate exists, and it is itself verified against negative controls.

**2. No combined score, ever.** The four layers stay separate. A pull request that adds a `score`,
`overall` or `aggregate` to a verdict, a cell or a report will be declined, and
`tests/test_report.py::test_layers_are_never_combined` fails on it. The distance between "it ran"
and "it was right" is the product; a single number destroys it.

**3. No vendor name outside `copela/providers/`.** Enforced by
`tests/test_providers.py::test_no_provider_name_leaks_outside_the_seam`, which scans the source.
Adding a provider means adding a module in that package and a registry entry, nothing else.

**4. A check that could not be evaluated is never a pass.** `Outcome.NOT_APPLICABLE` exists for
that, and using `PASS` in its place is how a harness reports a number it did not measure.

## Before you open a pull request

```bash
python -m venv .venv
./.venv/Scripts/python -m pip install -e "../CAOS_Planteo[pyomo]"
./.venv/Scripts/python -m pip install -e ".[dev,solvers]"
./.venv/Scripts/python -m pytest -rs
./.venv/Scripts/python -m ruff check .
./.venv/Scripts/python scripts/check_sdd.py .
```

Run the suite with `-rs`. A skipped test is not a passing test, and several gates here depend on a
real solver being present: if they skip in your environment, the thing they check went unchecked.

## Adding a property relation

A relation needs three things, and the third is the one people skip:

1. a `transform`, which changes the problem in a controlled way
2. a `check`, which compares the two solutions
3. a **negative control test** proving it catches a violation

Without the third, a relation that never fails anything looks exactly like a relation that works.
The SDD names that as the kill criterion for the whole layer, so it is tested rather than assumed.
See `tests/test_properties.py::test_the_relations_actually_catch_a_broken_solver`.

## Style

English only, in code, comments, docs and commit messages. No em-dash and no emoji in any content.
Line length 100.

## Versioning

`X.XX.XXX` in `VERSION`, the `CHANGELOG`, the tag and any interface string; the semver form with
zeros dropped in `pyproject.toml`. Bump by the nature of the change, not by commit count.
