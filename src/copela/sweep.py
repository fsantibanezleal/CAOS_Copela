"""The sweep: cases times models times repeats, scored, ledgered, resumable.

The loop is deliberately boring. Everything interesting is in the pieces it calls, and the value of
this module is what it refuses to do:

- it never drops a run, including one whose response did not parse, because a discarded failure is a
  silently inflated success rate
- it never repeats a completed call, because a long sweep that lost its work is a cost already paid
- it never spends past the budget, because the guard runs before the call
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from planteo import Problem, validate

from .budget import Budget, BudgetExceeded, estimate
from .ledger import CallKey, Ledger, Record, digest
from .oracles import properties
from .providers import Provider, ProviderError
from .verdicts import Layer, LayerResult, Outcome


@dataclass(frozen=True, slots=True)
class Case:
    """One narrative, with its reference formalization.

    The reference is what the structural layer compares against. A case without one can still be
    run: it gets an executable and a property verdict, and the structural layer reports
    NOT_APPLICABLE rather than inventing an opinion.
    """

    case_id: str
    family: str
    narrative: str
    reference: Problem | None = None
    tier: int = 1
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Target:
    provider_name: str
    model_id: str


@dataclass
class Sweep:
    ledger: Ledger
    budget: Budget
    providers: dict[str, Provider]
    #: Turns a narrative into a prompt. Injected so the prompt strategy is a variable under study
    #: rather than a constant baked into the harness.
    build_prompt: Callable[[Case], str]
    #: Parses a model response into a Problem, given the case it came from. Raises on anything it
    #: cannot read; a raise becomes a recorded executable-layer failure, never a dropped run.
    #: The case is passed because a parser often needs it, for instance to check a response against
    #: the narrative the model was actually given.
    parse_response: Callable[[str, Case], Problem]
    #: Solves a Problem, for the executable and property layers.
    solve: Callable[[Problem], properties.Solution] | None = None
    repeats: int = 3
    temperature: float = 0.0
    seed: int | None = 20260922
    expected_output_tokens: int = 1200

    def run(self, cases: Sequence[Case], targets: Sequence[Target]) -> int:
        """Run the sweep. Returns the number of calls made in this invocation."""
        done = self.ledger.completed()
        made = 0

        for case in cases:
            prompt = self.build_prompt(case)
            for target in targets:
                provider = self.providers[target.provider_name]
                pricing = provider.models().get(target.model_id)
                for repeat in range(self.repeats):
                    key = CallKey(
                        case_id=case.case_id,
                        provider=target.provider_name,
                        model_id=target.model_id,
                        repeat=repeat,
                    )
                    if key.as_tuple() in done:
                        continue

                    projected = (
                        estimate(
                            prompt,
                            self.expected_output_tokens,
                            pricing.input_per_mtok,
                            pricing.output_per_mtok,
                        )
                        if pricing
                        else 0.0
                    )
                    try:
                        self.budget.check(projected)
                    except BudgetExceeded:
                        return made

                    self._run_one(case, target, provider, prompt, key)
                    made += 1
        return made

    def _run_one(
        self,
        case: Case,
        target: Target,
        provider: Provider,
        prompt: str,
        key: CallKey,
    ) -> None:
        verdicts: list[LayerResult] = []
        error = ""
        completion = None

        try:
            completion = provider.complete(
                prompt,
                model_id=target.model_id,
                temperature=self.temperature,
                seed=self.seed,
            )
        except ProviderError as failure:
            error = str(failure)

        if completion is None:
            # The call itself failed. This is an executable-layer failure and it is recorded, not
            # dropped: a sweep that discards its failures reports a success rate over the runs that
            # happened to work.
            verdicts.append(
                LayerResult(Layer.EXECUTABLE, Outcome.FAIL, f"the call failed: {error}")
            )
            self._record(key, case, target, None, verdicts, error)
            self.budget.charge(0.0, failed=True)
            return

        candidate: Problem | None = None
        try:
            candidate = self.parse_response(completion.text, case)
        except Exception as failure:  # noqa: BLE001, any parse failure is the same verdict
            verdicts.append(
                LayerResult(
                    Layer.EXECUTABLE,
                    Outcome.FAIL,
                    f"the response did not parse into a problem: {failure}",
                )
            )
            error = str(failure)

        if candidate is not None:
            verdicts.extend(self._score(candidate, case))

        self._record(key, case, target, completion, verdicts, error)
        self.budget.charge(
            completion.cost_usd,
            failed=any(
                v.layer is Layer.EXECUTABLE and v.outcome is Outcome.FAIL for v in verdicts
            ),
        )

    def _score(self, candidate: Problem, case: Case) -> list[LayerResult]:
        results: list[LayerResult] = []

        report = validate(candidate)
        if not report.ok:
            results.append(
                LayerResult(
                    Layer.EXECUTABLE,
                    Outcome.FAIL,
                    "; ".join(str(f) for f in report.errors[:3]),
                )
            )
            return results

        if self.solve is None:
            results.append(
                LayerResult(
                    Layer.EXECUTABLE,
                    Outcome.PASS,
                    "validated; no solver configured, so solving was not attempted",
                )
            )
        else:
            try:
                solution = self.solve(candidate)
                results.append(
                    LayerResult(
                        Layer.EXECUTABLE,
                        Outcome.PASS if solution.feasible else Outcome.FAIL,
                        solution.detail,
                    )
                )
            except Exception as failure:  # noqa: BLE001
                results.append(
                    LayerResult(Layer.EXECUTABLE, Outcome.FAIL, f"solving failed: {failure}")
                )
                return results

        results.append(self._structural(candidate, case))

        if self.solve is not None:
            layer, _ = properties.evaluate(candidate, self.solve)
            results.append(layer)

        return results

    def _structural(self, candidate: Problem, case: Case) -> LayerResult:
        if case.reference is None:
            return LayerResult(
                Layer.STRUCTURAL,
                Outcome.NOT_APPLICABLE,
                "the case carries no reference formalization to compare against",
            )
        from planteo import compare

        result = compare(case.reference, candidate)
        if result.equivalent:
            return LayerResult(
                Layer.STRUCTURAL, Outcome.PASS, "canonical forms are equal"
            )
        # Canonical inequality proves nothing, so this is UNDECIDED rather than FAIL and the
        # property layer carries the decision. Reporting it as a failure would manufacture false
        # negatives out of a normalisation artifact.
        return LayerResult(
            Layer.STRUCTURAL,
            Outcome.UNDECIDED,
            "canonical forms differ, which does not establish that the models differ",
        )

    def _record(
        self,
        key: CallKey,
        case: Case,
        target: Target,
        completion,
        verdicts: list[LayerResult],
        error: str,
    ) -> None:
        self.ledger.append(
            Record(
                key=key,
                family=case.family,
                model_version=completion.model_version if completion else "unknown",
                temperature=self.temperature,
                seed=self.seed,
                provider_fingerprint=completion.fingerprint if completion else "none",
                prompt_digest=digest(self.build_prompt(case)),
                response_digest=digest(completion.text) if completion else "",
                latency_ms=completion.latency_ms if completion else 0.0,
                input_tokens=completion.input_tokens if completion else 0,
                output_tokens=completion.output_tokens if completion else 0,
                cost_usd=completion.cost_usd if completion else 0.0,
                verdicts=[v.to_json() for v in verdicts],
                error=error,
            )
        )
