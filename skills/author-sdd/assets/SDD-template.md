# <Product>, software design document

Status: draft for review. Date: <YYYY-MM-DD>.

<!-- Written after the research and the plan, before the code. If it was not, say so here. -->

## 1. Problem

<The question the product answers, in one paragraph, and the evidence that the question is open.>

## 2. Non-goals

- **Not <a thing a reader would assume>.** <Why it is out.>
- **Not <another>.** <Why.>

## 3. Contracts

**Ingestion.** <Raw source to pipeline: the typed record, units, ranges, and the outlier policy.>

**Artifact.** <Pipeline to surface: the files, their schema version, and what a reader of each
relies on.>

## 4. Lanes

| Lane | What runs there | Measured basis |
|---|---|---|
| Offline | <bake, training, sweeps> | <the measurement that put it there> |
| Live | <what a reader's browser or the server computes> | <payload, latency measured> |
| Replayed | <what is shown from committed artifacts> | <why it need not run live> |

## 5. The method ladder

| Method | Acceptance sentence, written before the method |
|---|---|
| <method 1> | <the sentence that will decide whether it is implemented> |

## 6. Case taxonomy and coverage

| Category | Why it exists | Cases |
|---|---|---|
| <tier or trap> | <what it catches> | <n> |

## 7. The evaluation oracle

<What decides an output is correct, and why that is trustworthy. If a model judges, say that it is a
screening aggregate and not an oracle, and state its limitation.>

## 8. Requirements

Every requirement is in EARS form and names the gate that fails when it is violated.

```
R-001  THE <system> SHALL <response>.
       Gate: tests/test_<unit>.py::test_<what_it_checks>

R-002  WHEN <trigger>, THE <system> SHALL <response>.
       Gate: tests/test_<unit>.py::test_<what_it_checks>

R-003  IF <unwanted condition>, THEN THE <system> SHALL <response>.
       Gate: scripts/check_<thing>.py
```

<For each requirement, below the block: the incident, measurement or decision that produced it.>

## 9. The deploy driver

<The measurement and the threshold that decide where it runs. UNDECIDED until measured.>

## 10. Convergence

Recorded <date>.

| Requirement | Result |
|---|---|
| R-001 to R-003 | <pass or fail, with the gate's output> |

Out of scope and not claimed: <what was not built, stated rather than left out>.

## 11. Risks and kill criteria

- **<Risk>.** <How it shows up, and the measured criterion that stops the work.>
