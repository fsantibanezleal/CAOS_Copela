---
name: author-sdd
description: >-
  Author a software design document before development starts: a product SDD at
  docs/design/SDD.md, or a feature SDD at docs/design/features/<slug>/, with every
  requirement in EARS form and every requirement naming the gate (a test, a guard
  script, a measured check) that fails when the requirement is violated. Use when a
  repo is about to gain implementation code, when a non-trivial unit is about to be
  built, or when an existing SDD must be brought to convergence. Ships the stdlib
  guard that checks every named gate exists.
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
metadata:
  version: 0.1.0
---

# Author an SDD

A software design document says **how** a thing is built and **what proves each part works**. It is
written after the research and the plan, and before the code. Its binding clause is the one this
skill enforces: **every requirement names the gate that verifies it.** A requirement with no named
verification is a wish.

The practice comes from the account's ADR-0075 and its convention page; copela and Enunciado are
built on it. Two outside sources were read and partly taken: GitHub Spec Kit (the specify, plan,
tasks, implement, converge sequence) and AWS Kiro (requirements, design and tasks, with EARS
acceptance criteria). Their tooling was not taken; the artifacts are markdown.

## When to use it

- A repo is about to gain its first implementation file: write the **product SDD** first.
- A non-trivial unit is about to be built inside a repo that has one: write a **feature SDD**.
- Work is "done": write the **convergence** verdict before saying so.

## Procedure

### 1. Read before writing

Read the research dossiers and the plan for the product. The SDD transcribes decisions from them; it
does not invent them. If a decision the design needs is not in the research, stop and research it,
or record it as UNDECIDED with the measurement that will decide it.

### 2. Write the product SDD

Copy [`assets/SDD-template.md`](assets/SDD-template.md) to `docs/design/SDD.md` and fill every
section. All eight are required:

1. **Problem and non-goals.** The non-goals do more work than the problem: list what a reader would
   reasonably assume is in scope and is not.
2. **Contracts.** Ingestion (raw to pipeline) and artifact (pipeline to surface), typed, with the
   outlier policy.
3. **Lanes.** What runs offline, what runs live, what is replayed, and the measured basis for each.
4. **The method ladder**, one acceptance sentence per method, written before the method.
5. **Case taxonomy and coverage matrix**, with the reason each category exists.
6. **The evaluation oracle.** What decides an output is correct and why that is trustworthy. A model
   judging is a screening aggregate, not an oracle; say so if it is used.
7. **The deploy driver.** A measurement and a threshold. UNDECIDED until the measurement exists.
8. **Risks and kill criteria.**

### 3. Write the requirements in EARS

EARS is the Easy Approach to Requirements Syntax: Mavin, Wilkinson, Harwood and Novak, 17th IEEE
International Requirements Engineering Conference, 2009, pp. 317-322, doi:10.1109/RE.2009.9. Its
generic form, as its originator states it, is "While [optional pre-condition], when [optional
trigger], the [system name] shall [system response]": zero or more preconditions, zero or one trigger,
one system, one or more responses. The patterns, with the keywords capitalised as the guard reads
them:

```
THE  <system> SHALL <response>                                         ubiquitous
WHEN  <trigger>, THE <system> SHALL <response>                         event-driven
WHILE <precondition>, THE <system> SHALL <response>                    state-driven
WHERE <feature is included>, THE <system> SHALL <response>             optional feature
IF    <trigger>, THEN THE <system> SHALL <response>                    unwanted behaviour
WHILE <precondition>, WHEN <trigger>, THE <system> SHALL <response>    complex
```

The value is not the keywords. Each pattern forces the author to say **when** the requirement
applies, which is the part that otherwise stays implicit and gets argued about later.

Requirements live **inside fenced code blocks**, one identifier per requirement, each followed by its
gate:

```
R-004  WHEN the ingestion contract rejects a record,
       THE pipeline SHALL halt and report the failing field and its expected range.
       Gate: tests/test_contract.py::test_reject_out_of_range
```

### 4. Name a real gate for every requirement

A gate is the name of the thing that **fails** when the requirement is violated: a test file and
case, a guard script, a browser check, an artifact validation, a parity tolerance with its number.
Not "tested", not "verified manually", not "code review": the guard rejects `manual:` and `review:`
gates on purpose.

Then prove the gate can fail. Remove or break the rule the requirement protects, run the gate, and
watch it fail; restore the rule and watch it pass. A gate that has never failed has not been shown to
test anything. The failures this practice was written after were mostly not missing gates but green
gates measuring the wrong thing: a check that passed against a different product on the same port, a
CI watch piped to `tail` that reported success on failure, a count of elements that existed instead
of a comparison with what should exist.

### 5. Run the guard

```bash
python skills/author-sdd/scripts/check_sdd.py <repo_root>
```

Standard library only. It fails when a repo has implementation code and no `docs/design/SDD.md`,
when a requirement has no `Gate:` line or no `SHALL`, when an identifier repeats, and **when a named
gate does not exist**: the file must be on disk and, when the gate names a test, `def <test>` must
appear in it. Wire it into CI as a cheap check. A requirement whose gate does not exist yet makes the
guard fail, which is correct: write the test, then the requirement passes.

### 6. Feature SDDs

For a non-trivial unit, create `docs/design/features/<slug>/` with three files: `requirements.md`
(EARS, gated, in fenced blocks, from
[`assets/feature-requirements-template.md`](assets/feature-requirements-template.md)), `design.md`
(architecture, interfaces, data flow) and `tasks.md` (dependency-ordered tasks, each linked to the
requirement it satisfies). The guard checks every feature `requirements.md` as well.

### 7. Converge, as a verdict

Work ends with an explicit check against the SDD: every requirement, its gate, and the gate's result,
recorded in a convergence table in the SDD or in the PR that closes the unit. Anything unmet is
listed, not omitted. "It builds", "it is green" and "it is deployed" are not convergence.

Record why each requirement exists, beside the block: the incident, measurement or decision that
produced it. A requirement whose reason is lost gets deleted by the next person who finds it
inconvenient.

## What not to do

- Do not write the SDD after the code and present it as before. If that happened, say so at the top
  of the document; an SDD that opens with a false claim about its own timing is worth nothing.
- Do not restate a rule in two places and trust that they agree. Two restatements can agree on every
  record in the data and still differ as rules; compare them over every combination of inputs.
- Do not count elements where a comparison is needed. "Every model has a row" is checked by comparing
  the rows with the models, not by counting rows.
- Do not accept a gate that reads the wrong state: point browser gates at the built or deployed
  artifact, not a dev server.
