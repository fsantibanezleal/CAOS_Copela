# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are `X.XX.XXX` in this file, the
git tag and any interface string, and the semver form with zeros dropped in `pyproject.toml`.

## [0.03.001] - 2026-09-23

### Fixed

- **The local lane ran in a 4096-token window, whatever `max_tokens` said (R-026).** It never set a
  context, so the server chose one from the GPU's memory, 4096 tokens on an 8 GB card. A generation
  that outgrows the window is not stopped: the server shifts the context, silently, and the model
  writes on without the start of its prompt. Measured on qwen3:4b and the first Enunciado case: in
  the default window, 942 prompt tokens and 6109 generated, finishing "stop" with an answer a fifth
  the length of a formalization; in a window that held the cap, all 8192 tokens of reasoning and no
  answer. Every call now requests a context that holds the prompt and the whole cap, in 4096-token
  steps so a corpus lands on one size, and refuses a model whose window cannot. The local lane's
  earlier result on qwen3.5:4b ran in the default window and says nothing about the cap.
- **The reasoning switch was sent and recorded for models with no reasoning (R-027).** The server
  accepts `think` on such a model and ignores it. The lane now asks the server what the model can do
  and records `think=n/a` for one that cannot reason.
- The local lane records the digest of the weights behind a tag (R-028), since a tag can be
  re-pulled onto other weights, and the context it requested, in the fingerprint.
- `OLLAMA_HOST` in Ollama's own form, without a scheme (`127.0.0.1:11435`), no longer fails.
- A local call's HTTP error keeps its body, and the local timeout is an hour: a model larger than
  the GPU runs partly on the CPU, and a full cap can outlast fifteen minutes.

## [0.03.000] - 2026-09-23

### Added

- **Two providers, `zai` (GLM models) and `deepseek`**, over their OpenAI-shaped endpoints in plain
  HTTP, with no SDK. Each writes its request out explicitly and says in its fingerprint which
  controls it exercised: Z.AI sends greedy decoding for temperature 0 and an effort only to the
  models that take one; DeepSeek sends its effort and no temperature, which its thinking mode
  ignores. Neither exposes a seed, and neither claims one. An HTTP error keeps its body, because the
  body names the cause. `ZAI_BASE_URL` selects the coding-plan endpoint, the only one a GLM Coding
  Plan key works on.
- The Z.AI table holds what is both priced and callable, checked 2026-09-23. The pricing page prices
  models that `/models` does not list, and one of them, GLM-4.5-Flash, answered calls free with no
  balance at all. `/models` lists GLM-5-Turbo, which nothing prices, so it is left out.
- `UnpricedModel`, exported.

### Changed

- **The budget guard projects a call at its output cap (R-025)**, not at 1200 tokens. Reasoning
  models bill their reasoning as output, and the first two measured spent 5206 and 7931 tokens on
  one case, so the guard could pass a call it should have refused. `Sweep.expected_output_tokens`
  is removed, since any value below the cap re-opens the overrun, and the second argument of
  `estimate` is renamed `output_tokens`. A sweep of reasoning models now stops earlier than its
  typical spend suggests, which is the intended direction.
- **A sweep refuses a model it has no price for (R-024)**, before its first call, naming the models
  the provider does price. The guard used to project such a model at zero and the provider charged
  it at zero, so the budget never moved while the calls were billed. A local model not yet pulled is
  refused the same way instead of failing every call.
- `copela models` prints "no per-token price" for a free model, not "(local)", since a free hosted
  model now exists.

### Fixed

- **A reasoning-only reply on the Groq lane was recorded as empty (R-022).** gpt-oss returns its
  reasoning in `message.reasoning`, and a reply that spent the cap on it came back as an empty
  string. Every lane that can reason (Ollama, Groq, Z.AI, DeepSeek) now returns one sentence for
  this, from one function, because a report classifies truncations by it. The Ollama lane gains the
  finish reason it lacked.
- The model recorded is the one the server reports running (R-023). The Z.AI coding endpoint
  answered a request for GLM-5.2 with GLM-5.3.
- The README said the design document had eighteen requirements. It had twenty-one, and now has
  twenty-five.

## [0.02.003] - 2026-09-23

### Fixed

- **A candidate that never ran could be `faithful` (R-021).** `CandidateVerdict.faithful` checked
  that no strong layer failed and one passed, and never that the executable layer passed. The sweep
  never records a structural or property verdict without a run, so no measured rate changes, but the
  property is public API, and the report's own comment says a candidate that never ran cannot be
  faithful. Found by a consistency test in Enunciado that compares the three places the rule is
  stated, over every combination of layer outcomes rather than over the ledger.

## [0.02.002] - 2026-09-23

A documentation release. No behaviour changed.

### Fixed

- **The README showed a superseded run as the current one.** Its example, Haiku 4.5 at ran 0.350
  and gap +0.100, was a real pass from before an instrument fix. It now shows the published
  measurement, both models at gap +0.050, as `copela report` prints it from the committed ledger,
  and says what the earlier pass was.
- **The sweep guide showed invented output**: two rows at n=50, one for a local model that was
  never run, intervals elided. Replaced by real output.
- The four-layers page states `faithful` exactly as `Verdicts.faithful` computes it: it ran, no
  strong layer failed, and at least one passed.
- `__display_version__` read 0.01.000 through 0.02.000 and 0.02.001. The publish gate checks the
  tag, `VERSION` and the manifest, and not this string.

## [0.02.001] - 2026-09-23

### Fixed

- **A sense-flipped rewrite is no longer refuted (R-020).** The structural layer compared the two
  optimal values raw, so a candidate maximising the negative of the cost, where the reference
  minimises the cost, solved to -z against z and was reported as a different optimum: a style
  rewrite refuted as a wrong model. Both optima are now read in the minimising sense before they
  are compared. A candidate optimising the same expression the wrong way is still refuted, unless
  its optimum is exactly the negative of the reference's, which reads as UNDECIDED and never as
  PASS. Neither refutation in the published Enunciado ledger changes: both compare values of the
  same sign. The calls that did not fail keep no document, so whether any of them would now be
  refuted cannot be re-checked; it would take a candidate optimising in the opposite sense that
  still lands exactly on the reference's value.

### Changed

- The four-layers page states the published measurement as it is: two refutations, one per model,
  a gap of +0.050 for each, and PASS on none of the sixteen candidates that ran. It had described
  the two refutations as one model's and its gap as +0.100.

## [0.02.000] - 2026-09-22

The release that makes the published measurement reproducible. 0.01.000 carried a structural layer
that could not fail, so a faithfulness rate computed with it was carried by a check that never
refuted anything. Anything measured with 0.01.000 should be re-measured with this.

### Fixed

- **The structural layer can now REFUTE.** It compared canonical forms, and when they differed it
  returned UNDECIDED and stopped. Measured over twenty authored optimization cases it returned
  UNDECIDED on every single candidate that ran, so the whole faithfulness rate rested on internal
  invariants that had never failed anything. The missing direction is conclusive and cheap: two
  formalizations of the same case that solve to different optima are not the same model. The
  asymmetry is kept deliberately, and a matching optimum never promotes a verdict to PASS, because
  compensating errors reach the right number.
- **A limit of the instrument is no longer charged to the subject.** A model the configured solver
  cannot express raises `ModelNotSupported`, which is recorded as NOT_APPLICABLE and excluded from
  both rates rather than counted as a failed formalization.
- **The gap is UNDEFINED, not zero, when nothing ran.** Reporting `gap +0.000` for a model that
  failed every call reads as "no gap" and means "no measurement".
- **The ledger takes an exclusive lock.** Two sweeps sharing one file interleaved records from two
  versions of the code, which is not a visible error but a dataset that mixes two instruments.
- **A failing response keeps a bounded excerpt.** A digest says a response existed and nothing about
  what was wrong with it, and re-running to reproduce does not work because hosted inference is not
  deterministic.
- **The Anthropic provider matches the current API**: the model ids carry no date suffix, the
  pricing is current, `temperature` is not sent because the API no longer accepts it, and reasoning
  effort is sent only to the models that take it. The fingerprint records which controls were
  actually exercised, including when the answer is none.

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
