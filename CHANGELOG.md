# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are `X.XX.XXX` in this file, the
git tag and any interface string, and the semver form with zeros dropped in `pyproject.toml`.

## [0.08.001] - 2026-09-24

### Fixed

- **The property layer refuted correct dynamics formalizations (R-043).** It raised one quantity per
  stated number, and matched a candidate quantity to the first reference quantity whose span
  overlapped its own. A number that produces two quantities, such as an initial concentration that
  is also the total in a formalization by conservation, was half raised, and the candidate responded
  the other way; a candidate quantity was paired with a state that happened to share words with it.
  A stated number now raises every quantity whose words it is, in both documents, and a candidate
  quantity belongs to the number whose words it covers the largest fraction of, or to none when it
  covers two equally. Found by Enunciado's hand-written alternatives of its dynamics cases.

## [0.08.000] - 2026-09-24

### Added

- **Unit-aware comparison in the dynamics layers (R-042).** `copela.units` reads a unit symbol into a
  factor to SI: time, length, volume, mass, amount, electrical and mechanical units with the SI
  prefixes, long and plural forms, products, quotients, powers, parentheses and count nouns, trusted
  only when the exponents it implies equal the declared ones; Celsius converts with its offset.
  Questions are paired at the same time in seconds and compared in SI. A symbol that cannot be read
  is compared raw, as before.

### Fixed

- A correct dynamics candidate in other units could not be found faithful. One counting hours where
  the reference counts minutes asked its question at 1 where the reference asked at 60 and was never
  compared; one counting grams where the reference counts kilograms was refuted.

## [0.07.000] - 2026-09-24

### Added

- **The dynamics layers (R-037 to R-041).** A candidate of planteo's dynamics family, a system of
  ODEs with questions attached, is scored by `copela.oracles.dynamics` instead of the optimization
  layers, with no solver injected. Executable: SciPy's LSODA integrates to every question's time with
  finite values. Structural: equal canonical forms pass; otherwise every question both documents ask
  is compared on 61 points across the whole shared range plus the asked time, and a difference
  anywhere refutes, so a candidate right at the asked time and wrong elsewhere is caught. Property:
  each number the statement states and both documents cite is raised by 5% in both, and an answer
  that does not move, or moves the other way, refutes. Design and equations in
  `docs/architecture/03_dynamics.md`.
- A candidate of another family than its case's reference fails the executable layer (R-041).

### Changed

- Requires planteo 0.2.0, which adds the dynamics family; SciPy joins the `solvers`, `all` and `dev`
  extras.

### Fixed

- A diverging system no longer hangs the sweep. LSODA does not stop on its own when a state
  overflows: on x' = x^2 it retried one step for over 2.8 million evaluations. The rate of change is
  checked at every evaluation (a divergence fails), and an integration is bounded at 100,000
  evaluations (beyond that it is unmeasured, the instrument's limit).
- A test server in `test_unreachable.py` answered before reading the request, which on Windows reset
  the connection under the client about one run in three; it now reads the body and sends a length.

## [0.06.001] - 2026-09-24

### Added

- **Two agent skills in `skills/` (R-036).** `author-sdd` writes a software design document before
  development, with every requirement in EARS form and naming the gate that fails when it is
  violated; it ships a product SDD template, a feature template and the repository's own SDD guard.
  `run-sweep` runs a narrative-to-formal sweep with a runner that refuses before it spends or locks
  (no price, no budget, a failed probe), stops without recording on an unreachable provider, and
  resumes; it ships a working example study. A test runs both scripts. No change to the library.

## [0.06.000] - 2026-09-24

### Changed

- **A call that never reached the model stops the sweep and is not recorded (R-035).** A new
  `ProviderUnreachable`, a `ProviderError`, raised when the connection fails before any response
  (a refused connection, an unresolved name, a TLS failure, a connect timeout) or when the provider
  answers 401 or 403. The sweep stops on it, keeps every call it recorded before, and a resume picks
  up at the failed call. An HTTP 500, a malformed body and a read timeout are still answers about
  this call and are still recorded. Recording the first kind put rows about a key file into a ledger
  as rows about the model; a network that drops mid-sweep would have done the same until the kill
  criterion.
- The stub provider takes `unreachable_after`, to drop its connection after that many calls.

## [0.05.000] - 2026-09-24

### Added

- **Each record carries the candidate's document, whole (R-034).** A new field, `candidate`, and
  ledger schema `copela-ledger/1.2`: the planteo document the response parsed into, or `null` when it
  did not parse. The verdicts said what the layers concluded and nothing about what they concluded it
  of, so a stronger check written later could not be applied to a recorded candidate. In Enunciado's
  finished measurement 30 of the 34 faithful verdicts rested on the property layer alone for that
  reason, and two refutations that were a reading the statement allowed could be established only
  from failure excerpts that happened to keep the declarations. A record written before 1.2 loads
  with `candidate` empty.

## [0.04.001] - 2026-09-23

Documentation only; no code changes to the library. CI now also checks that `VERSION`, the manifest
and `__version__` agree, because the first cut of this release bumped the last two and not the first,
and only the publish workflow noticed.

### Changed

- The README and the sweep guide show the finished measurement, re-derived by this release with
  `copela report`: sixteen models from four providers, 320 calls, 2.53 USD at list price. They
  showed the first, two-model measurement.
- `docs/architecture/01_the_four_layers.md` states what the structural layer decided over the
  finished measurement (4 PASS, 10 refutations, 45 candidates that ran) and a limitation it cannot
  see: a refutation inherits every choice the reference made. Both Claude refutations land exactly
  on their references' optima with the decisions made integer, in statements that never say whether
  those decisions are whole numbers.

## [0.04.000] - 2026-09-23

### Added

- **Each ledger record says which copela scored it and the output cap it ran at (R-033).** Two new
  fields, `harness` (`"copela 0.4.0"`) and `max_tokens`, and schema `copela-ledger/1.1`. One ledger
  had held records scored by three copela versions, which judge an unbounded candidate differently,
  with nothing in a record to tell them apart; and a report had to assume the cap, because a record
  could not state its own. A record written before 1.1 still loads, with both fields empty, which
  reads as unknown rather than as a guess.

## [0.03.003] - 2026-09-23

### Fixed

- **An unbounded candidate passed the executable layer (R-030).** The solver wrapper reports an
  unbounded model as feasible with no objective value, and the executable layer passed anything
  feasible. Running now means reaching an optimum, or a feasible point for a model with no
  objective, so an unbounded model is a failure to run, recorded as `unbounded`.
- **An unbounded candidate was described as agreeing on an optimum (R-031).** With no objective
  value on one side the comparison fell through to "both solve to the same optimum". A candidate
  that is unbounded where the reference has an optimum, or the reverse, is now refuted: the same case
  cannot have an optimum and none. Two unbounded models read as UNDECIDED, "both are unbounded",
  and two feasibility-only models as "both are feasible with no objective to compare".
- **The property layer reported FAIL on an unbounded candidate (R-032).** The objective-scaling
  relation found no argmin to compare and called that a failure. The layer now reports
  not-applicable, as it does for an infeasible candidate.

Found by checking deepseek-r1:8b's opt-006 record, which read as the first metamorphic refutation
Enunciado's ledger had recorded, before publishing it as one.

## [0.03.002] - 2026-09-23

### Fixed

- **Two infeasible models were described as agreeing on an optimum (R-029).** When a candidate and
  its reference are both infeasible and differ in canonical form, the structural layer reported
  UNDECIDED, correctly, with the detail "both solve to the same optimum". Neither has one. The detail
  now says both are infeasible and that a wrong model can be infeasible too. The outcome is
  unchanged; only records written from this release carry the corrected text.

### Documented

- A contradictory case cannot be passed: the executable layer counts only a feasible optimum as a
  run. Recorded as an open risk in the design document, since changing it moves published rates.

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
