# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are `X.XX.XXX` in this file, the
git tag and any interface string, and the semver form with zeros dropped in `pyproject.toml`.

## [0.01.000] - 2026-09-22

First release. The harness, its four layers, the ledger, the budget guard and the optimization
property relations.

### Added

- **Four verdict layers, reported separately**: executable, structural, property, and judge. There
  is no combined score and a test fails if one is added, because a single number lets a high "it
  ran" rate conceal a low "it was right" rate.
- **The judge layer is labelled on every record** as a screening aggregate rather than an oracle,
  and it never contributes to the faithful rate.
- **Rates with Wilson intervals**, so a single run is never presented as a result and 5 of 5 is not
  reported as certainly 1.0.
- **The append-only JSONL ledger**: one record per call, carrying case, provider, model id, model
  version, temperature, seed, provider fingerprint, prompt digest, repeat index, latency, tokens,
  cost and every layer's verdict. A record missing its provenance is refused, and a duplicate key is
  refused. It doubles as the resume mechanism.
- **The provider seam**: Anthropic, Groq and local Ollama behind one interface, plus a scripted stub
  for dry runs. No vendor name appears in code outside `copela/providers/`, enforced by a test that
  scans the source.
- **Property relations for optimization**: objective scaling preserves the argmin, a redundant
  constraint cannot change the feasible set, and tightening cannot improve the optimum. A relation
  that could not be evaluated reports not-applicable, never pass.
- **The budget guard**: a declared ceiling checked before each call rather than after, plus a
  consecutive-failure kill criterion.
- **The sweep**: cases times models times repeats, resumable from its ledger, recording failures
  rather than discarding them, including a response that did not parse.
- **Solving through Pyomo with HiGHS**, with a real time limit and a distinction between a solver
  that is unavailable and a model that is infeasible.
- **The `copela` command**: `models`, `solve`, `sweep`, `report`. The sweep refuses to start without
  a declared budget.

[0.01.000]: https://github.com/fsantibanezleal/CAOS_Copela/releases/tag/v0.01.000
