"""The sweep: cases times models times repeats, scored, ledgered, resumable.

The loop is deliberately boring. Everything interesting is in the pieces it calls, and the value of
this module is what it refuses to do:

- it never drops a run, including one whose response did not parse, because a discarded failure is a
  silently inflated success rate
- it never repeats a completed call, because a long sweep that lost its work is a cost already paid
- it never spends past the budget, because the guard runs before the call and projects the most the
  call can bill
- it never calls a model it has no price for, because the guard would count that call as free
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from planteo import Problem, Sense, validate

from .budget import Budget, BudgetExceeded, UnpricedModel, estimate
from .ledger import CallKey, Ledger, Record, digest
from .oracles import properties
from .providers import Pricing, Provider, ProviderError
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
    #: How much of a failing response to keep in the ledger, in characters.
    excerpt_chars: int = 2000
    #: Hard cap per call. A formalization document runs to a few thousand tokens, and a cap set
    #: for chat-sized replies truncates it into a failure that looks like the model could not do
    #: the task. It is also what the guard projects each call at, since no call can bill more.
    max_tokens: int = 8192

    def run(self, cases: Sequence[Case], targets: Sequence[Target]) -> int:
        """Run the sweep. Returns the number of calls made in this invocation.

        Raises ``UnpricedModel`` before the first call if any target has no price.
        """
        prices = self._price(targets)
        done = self.ledger.completed()
        made = 0

        for case in cases:
            prompt = self.build_prompt(case)
            for target in targets:
                provider = self.providers[target.provider_name]
                pricing = prices[target]
                for repeat in range(self.repeats):
                    key = CallKey(
                        case_id=case.case_id,
                        provider=target.provider_name,
                        model_id=target.model_id,
                        repeat=repeat,
                    )
                    if key.as_tuple() in done:
                        continue

                    projected = estimate(
                        prompt,
                        self.max_tokens,
                        pricing.input_per_mtok,
                        pricing.output_per_mtok,
                    )
                    try:
                        self.budget.check(projected)
                    except BudgetExceeded:
                        return made

                    self._run_one(case, target, provider, prompt, key)
                    made += 1
        return made

    def _price(self, targets: Sequence[Target]) -> dict[Target, Pricing]:
        """Every target's price, or a refusal before anything is spent.

        An earlier version projected an unpriced model at zero, and the provider then charged it at
        zero, so a sweep of a model missing from a price table spent real money against a budget
        that never moved. A local model is priced too, at nothing, which is a price; a model the
        local server has not pulled is refused here rather than failing every call.
        """
        prices: dict[Target, Pricing] = {}
        for target in targets:
            models = self.providers[target.provider_name].models()
            pricing = models.get(target.model_id)
            if pricing is None:
                listed = ", ".join(sorted(models)) or "nothing"
                raise UnpricedModel(
                    f"{target.provider_name!r} has no price for {target.model_id!r}, so the budget "
                    "guard would count its calls as free and could not stop the sweep. "
                    f"Priced by this provider: {listed}. For a hosted model, add its published "
                    "price to the provider's table; for a local one, pull it first"
                )
            prices[target] = pricing
        return prices

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
                max_tokens=self.max_tokens,
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
            self._record(key, case, target, None, verdicts, error, None)
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

        self._record(key, case, target, completion, verdicts, error, candidate)
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
                # Running means reaching an optimum, or, for a model with no objective, a feasible
                # point. An unbounded model reaches neither, and it used to pass: the solver reports
                # a feasible point, so it read as a run, and the layers after it then compared an
                # optimum against nothing (R-030).
                reached = solution.feasible and not _unbounded(candidate, solution)
                results.append(
                    LayerResult(
                        Layer.EXECUTABLE,
                        Outcome.PASS if reached else Outcome.FAIL,
                        solution.detail,
                    )
                )
            except Exception as failure:  # noqa: BLE001
                # A solver that cannot EXPRESS the model is a limit of this harness, not a defect
                # in the formalization. Counting it as a model failure would blame the subject for
                # the instrument, so it is recorded as unmeasured and left out of both rates.
                if type(failure).__name__ == "ModelNotSupported":
                    results.append(
                        LayerResult(
                            Layer.EXECUTABLE,
                            Outcome.NOT_APPLICABLE,
                            f"not measured: {failure}",
                        )
                    )
                else:
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
        """Compare the candidate against the reference, by form and then by answer.

        Canonical equality proves equivalence. Canonical inequality proves nothing on its own, but
        it is not the end of the comparison: **two formalizations of the same case that solve to
        different optima are not the same model.** That direction IS conclusive, and without it this
        layer can only ever say PASS or shrug.

        It matters more than it sounds. Measured on this corpus, the layer returned UNDECIDED on
        every single candidate that ran, so the whole faithfulness rate rested on internal
        invariants that never failed anything. A rate carried by a check that cannot fail is not a
        measurement.

        Note the asymmetry, which is the honest part: a matching optimum does NOT promote a verdict
        to PASS. Compensating errors reach the right number, which is the very failure the anchor
        survey documents. Answer agreement can only ever REFUTE.
        """
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

        disagreement, agreement = self._answers_disagree(candidate, case)
        if disagreement is not None:
            return LayerResult(Layer.STRUCTURAL, Outcome.FAIL, disagreement)

        # Agreeing on an answer proves nothing, whatever the answer. The message says which answer
        # was agreed on, because "both solve to the same optimum" was once written into records of
        # pairs that had no optimum at all (R-029).
        if agreement in {"infeasible", "unbounded"}:
            return LayerResult(
                Layer.STRUCTURAL,
                Outcome.UNDECIDED,
                f"canonical forms differ and both are {agreement}, which does not establish "
                f"equivalence: a wrong model can be {agreement} too",
            )
        if agreement == "feasible":
            return LayerResult(
                Layer.STRUCTURAL,
                Outcome.UNDECIDED,
                "canonical forms differ and both are feasible with no objective to compare, which "
                "does not establish equivalence",
            )
        return LayerResult(
            Layer.STRUCTURAL,
            Outcome.UNDECIDED,
            "canonical forms differ and both solve to the same optimum, which does not establish "
            "equivalence: compensating errors reach the right number",
        )

    def _answers_disagree(
        self, candidate: Problem, case: Case
    ) -> tuple[str | None, str | None]:
        """A reason when candidate and reference solve to different answers, else None; and, when
        they agree on something other than an optimum, what it is ("infeasible", "unbounded",
        "feasible"), so an agreement is described as the one it is.

        The reason is None whenever the comparison cannot be made, because an unmade comparison
        must never read as a failure any more than it may read as a pass.
        """
        if self.solve is None or case.reference is None:
            return None, None
        try:
            mine = self.solve(candidate)
            theirs = self.solve(case.reference)
        except Exception:  # noqa: BLE001, an unsolvable pair simply cannot be compared
            return None, None

        if mine.feasible != theirs.feasible:
            return (
                f"the reference is {'feasible' if theirs.feasible else 'infeasible'} and this "
                f"candidate is {'feasible' if mine.feasible else 'infeasible'}, so they are not "
                "the same model"
            ), None
        if not mine.feasible:
            return None, "infeasible"

        # An unbounded model has no optimum, so against a reference that has one the comparison is
        # conclusive: the same case cannot have an optimum and none. It used to fall through to
        # "both solve to the same optimum", written about a candidate with no optimum (R-031).
        mine_unbounded = _unbounded(candidate, mine)
        theirs_unbounded = _unbounded(case.reference, theirs)
        if mine_unbounded != theirs_unbounded:
            mine_says = "is unbounded" if mine_unbounded else f"solves to {mine.objective:.6g}"
            theirs_says = "is unbounded" if theirs_unbounded else f"solves to {theirs.objective:.6g}"
            return (
                f"the reference {theirs_says} and this candidate {mine_says}, so they are not the "
                "same model"
            ), None
        if mine_unbounded:
            return None, "unbounded"
        if mine.objective is None or theirs.objective is None:
            return None, "feasible"

        # Both optima are read in the minimising sense before they are compared. Maximising f and
        # minimising -f are the same model with optimal values of opposite sign, and comparing the
        # raw values would refute that style rewrite as "a different optimum", which is exactly the
        # false FAIL this layer exists not to produce (R-020). A candidate that optimises the same
        # expression the wrong way still differs after the flip and is still refuted, unless its
        # optimum is exactly the negative of the reference's; that coincidence reads as UNDECIDED,
        # never as PASS, which is the safe direction to be wrong in.
        mine_min = _minimising(candidate, mine.objective)
        theirs_min = _minimising(case.reference, theirs.objective)
        tolerance = 1e-6 * max(1.0, abs(theirs_min))
        if abs(mine_min - theirs_min) > tolerance:
            return (
                f"solves to {mine.objective:.6g} where the reference solves to "
                f"{theirs.objective:.6g}; the same case cannot have two optima, so these are "
                "different models"
            ), None
        return None, None

    def _excerpt(self, completion, verdicts: list[LayerResult]) -> str:
        """Keep a bounded excerpt of the response, but only when something failed.

        A successful run is described by its verdicts. A failed one is not: a digest says a
        response existed and nothing about what was wrong with it, and re-running to reproduce does
        not work because hosted inference is not deterministic.
        """
        failed = any(v.outcome is Outcome.FAIL for v in verdicts)
        if not failed or completion is None:
            return ""
        text = completion.text
        if len(text) <= self.excerpt_chars:
            return text
        half = self.excerpt_chars // 2
        omitted = len(text) - self.excerpt_chars
        middle = f"[... {omitted} characters omitted ...]"
        return "\n".join((text[:half], middle, text[-half:]))

    def _record(
        self,
        key: CallKey,
        case: Case,
        target: Target,
        completion,
        verdicts: list[LayerResult],
        error: str,
        candidate: Problem | None,
    ) -> None:
        # Imported here, not at module level: the package imports this module while initialising.
        from . import __version__

        # The document the verdicts were reached on (R-034). A parser may hand back something that
        # is not a Problem, as a test double does; that is recorded as no document, never guessed.
        document = candidate.to_json() if isinstance(candidate, Problem) else None

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
                response_excerpt=self._excerpt(completion, verdicts),
                harness=f"copela {__version__}",
                max_tokens=self.max_tokens,
                candidate=document,
            )
        )


def _unbounded(problem: Problem, solution: properties.Solution) -> bool:
    """The solver found a feasible point and no optimum, for a model that has an objective.

    The solver wrapper reports an unbounded model as feasible with no objective value. A model with
    no objective at all is also reported without one, and is not unbounded: it asked only for a
    feasible point.
    """
    return solution.feasible and solution.objective is None and bool(problem.objectives)


def _minimising(problem: Problem, value: float) -> float:
    """An optimal value restated as the value of the equivalent minimisation.

    A problem with no objective has no sense to restate, and its value is returned unchanged.
    """
    if problem.objectives and problem.objectives[0].sense is Sense.MAXIMISE:
        return -value
    return value
