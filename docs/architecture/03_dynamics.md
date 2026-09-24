# The dynamics layers

A dynamics candidate is a system of ordinary differential equations with questions attached:
planteo's dynamics family, from planteo 0.2.0. The layers are the optimization family's, with the
answer being a trajectory rather than an optimum. They live in
[`src/copela/oracles/dynamics.py`](../../src/copela/oracles/dynamics.py) and need SciPy
(`pip install "copela[solvers]"`). The requirements are R-037 to R-041 in the
[SDD](../design/SDD.md).

## What a candidate states

A statement such as "a tank holds 100 L of brine containing 2 kg of salt; brine with 0.4 kg of salt
per litre flows in at 5 L/min and the mixture drains at the same rate; how much salt is there after
20 minutes?" becomes

$$
\frac{dx}{dt} = f(x, t; p), \qquad x(t_0) = x_0, \qquad t \in [t_0, t_1],
$$

with the states $x$ (role `state`, the value being the initial value), one independent variable $t$
(role `independent`, the bounds being the range), the stated parameters $p$, one `rate` relation per
state, and queries $Q_k = g_k\big(x(\tau_k), \tau_k\big)$, each asked at a time $\tau_k$. For the tank,
$f = c_{in} q - x q / V$, so $x(t) = 40 - 38\,e^{-t/20}$ and the question's answer is
$Q = x(20) = 40 - 38/e \approx 26.021$ kg.

Every quantity a stated number produced cites the words it came from, which is what the property
layer uses.

## Executable

The system integrates to every query time with finite values. The integrator is SciPy's LSODA,
which switches between a non-stiff Adams method and a stiff BDF method as the problem requires
(Petzold 1983), at $\text{rtol} = 10^{-9}$ and $\text{atol} = 10^{-12}$, far below the structural
tolerance, so an integration error cannot pass for a modelling one.

Two outcomes are not a pass, and they are kept apart because they mean different things:

- **The model diverges.** When the rate of change stops being a finite number before the last query,
  the state has run off to infinity, and the question has no answer: FAIL. This guard exists because
  LSODA does not stop by itself. On $\dot{x} = x^2$ from 2 kg, which blows up at half a minute, it
  reached $x \approx 1.3 \times 10^{154}$, where the square overflows, and retried that step for
  more than 2.8 million evaluations of the right-hand side in 45 seconds without returning. A sweep
  that met such a candidate would have hung.
- **The instrument gives up.** An integration that spends 100,000 evaluations of the right-hand side
  without reaching the last query is stopped and reported as **not measured**. So is a construct the
  evaluator cannot compute, such as an indexed sum, whose members are not scalar values. Neither
  shows the model is wrong. The corpus's references need a few hundred evaluations.

## Units

planteo compares dimensions as exponent vectors, which is right for a dimensional check: minutes
and hours are both time. It is not enough for comparing values. A candidate that integrates in hours
where the reference integrates in minutes asks "after 20 minutes" at $t = 1/3$ where the reference
asks at $t = 20$, and one that counts salt in grams reports 26021 where the reference reports
26.021. Both are the system described.

Each unit symbol is therefore read into a factor to SI ([`copela.units`](../../src/copela/units.py)):
a closed vocabulary of time, length, volume, mass, amount, electrical and mechanical units with the
SI prefixes, their long and plural forms, products, quotients, powers and parentheses, and count
nouns ("people", "thousand rabbits"). A reading is trusted only when the exponents it implies equal
the exponents the document declared, so "min" declared as a length is not read at all. Celsius is
affine: a value in degrees Celsius converts with an offset, $T_K = T_{C} + 273.15$, and only when
the symbol is exactly one Celsius token.

With $\kappa^{c}, \kappa^{r}$ the seconds per unit of each document's independent variable and
$s^{c}, s^{r}$ the SI scales of a question's value, two questions are paired when
$|\tau^{c}\kappa^{c} - \tau^{r}\kappa^{r}| \le 10^{-9} \max(1, |\tau^{r}\kappa^{r}|)$ and their
dimensions agree, and every comparison below is made on $t\,\kappa$ and $s(Q)$. When either
document's symbol cannot be read, the raw times and values are compared, which is what the layers did
before 0.8.0: a symbol outside the vocabulary can cost a candidate a comparison, but never produces a
conversion that is wrong.

## Structural

Equal canonical forms prove equivalence: PASS. Otherwise the refutation compares the questions both
documents ask (the same time $\tau$ in seconds, the same dimension) along the **whole shared
range**, not only at the asked time. With times in seconds and values in SI, on the grid

$$
T = \Big\{\, t_0 + (t_1 - t_0)\,\tfrac{i}{60} \;:\; i = 0, \dots, 60 \,\Big\} \cup \{\tau\},
\qquad S = \max_{t \in T} \big|Q^{r}(t)\big|,
$$

the candidate is refuted if for some $t \in T$

$$
\big|Q^{c}(t) - Q^{r}(t)\big| \;>\; \varepsilon \,\max\!\big(S,\ |Q^{c}(t)|,\ |Q^{r}(t)|\big),
\qquad \varepsilon = 10^{-5}.
$$

Two formalizations of one case cannot follow two trajectories, so a difference anywhere is
conclusive. Agreement everywhere still decides nothing (UNDECIDED), for the same reason as an equal
optimum: compensating errors can reach the same curve.

![Salt against time: the reference rises from 2 kg toward 40 kg; a candidate held at 26.021 kg agrees only at 20 minutes and is refuted at t = 0](../assets/dynamics-trajectory.svg)

The figure is the case the grid exists for. A candidate that holds 26.021 kg from the start answers
the question exactly. Execution accuracy, one number at one time, is how MAMO scores its 346 ODE
problems (Huang et al. 2024), and it would count this candidate as correct. The structural layer
refutes it at the first grid point: "'salt_after_20_min' is 26.0206 at 0 where the reference's is 2".

## Property, through provenance

The optimization relations are authored per class: scale the objective, add a redundant constraint.
The obvious dynamics analogue, rescaling time, holds for any model by construction, so it tests
nothing. The dynamics relation instead uses what planteo has and other representations do not: the
citation from a parameter to the words of the statement.

A stated number is the words it was written in, and it can produce more than one quantity: "1 mol/L
of A" is A's initial value and, in a formalization by conservation, the total as well. So the
relation works on stated numbers, not on quantities:

- reference quantities whose spans overlap are one stated number $j$, with the set $P^{r}_j$ of
  quantities it produced;
- a candidate quantity belongs to the stated number whose words it covers the largest fraction of,
  $\max_j |s \cap w_j| / |w_j|$; one that covers two numbers equally, such as a span running over a
  whole sentence, belongs to neither and is left out, because raising it with the wrong number
  would compare a change the statement never made. $P^{c}_j$ is the set that belongs to $j$.

Every quantity in $P^{r}_j$ and in $P^{c}_j$ is raised by the same factor,
$p \mapsto 1.05\,p$, both systems are integrated again, and the responses of every shared question
at its asked time are compared:

$$
\Delta^{r}_{j} = Q^{r}(\tau;\, 1.05\,P^{r}_j) - Q^{r}(\tau), \qquad
\Delta^{c}_{j} = Q^{c}(\tau;\, 1.05\,P^{c}_j) - Q^{c}(\tau).
$$

Where the reference responds ($|\Delta^{r}_j| > 10^{-7}\,|Q^{r}|$), the candidate is refuted if it
does not respond, or responds the other way: $\operatorname{sign}\Delta^{c}_j \neq
\operatorname{sign}\Delta^{r}_j$. A candidate whose salt falls when the stated inflow concentration
rises is not the system described, whatever its value at the asked time. The test that gates this
(R-039) is built to have exactly the right value at 20 minutes: its inflow is
$0.16\,\text{kg}^2/\text{L}^2 \cdot q / c_{in}$, which equals $c_{in} q$ at the stated
$c_{in} = 0.4$ and moves the opposite way when it changes.

Raising one quantity per number, as 0.08.000 did, refuted correct formalizations. On a reaction
$A \to B \to C$ written with $C = a_0 - a - b$, raising only A's initial value lowers $C$ while
the reference's $C$ rises. Enunciado's hand-written alternatives of its twenty dynamics cases found
it before any model did.

This is metamorphic testing (Segura et al. 2016) with the relation derived from the reference
rather than authored per case. With no number cited by both, or no question asked by both, the
relation does not apply and says so (NOT_APPLICABLE), which is not a pass.

## Judge

Recorded for comparability, never counted, as for optimization.

## Limits, stated rather than hidden

- **Units the vocabulary does not know.** A symbol outside it is compared raw, so a candidate
  that counts time in fortnights is paired only if its numbers happen to match. The vocabulary is
  closed on purpose: a wrong conversion would refute a correct candidate, and a missing one only
  leaves it uncompared.
- **Rounded conversions are different numbers.** A candidate that converts 4 L/min into 0.0667 L/s
  states a flow 0.05% off, which the structural tolerance refutes. That is correct about the
  document and harsh about the model, so Enunciado's statements invite only conversions that are
  exact in decimal (6 L/min is 360 L/h and 0.1 L/s).
- **The sign is one-sided evidence.** A candidate that responds the right way can still respond by
  the wrong amount; the structural layer, not this one, compares amounts.
- **A finite perturbation.** A 5% change is not a derivative; a response that changes sign within 5%
  of the stated value would be misread. The corpus has none, and a case that did would have to say so.
- **Conservation and limits** declared per case (a closed compartment system conserves its total;
  cooling approaches ambient) are not checked separately. With a reference, a candidate that breaks
  either on a shared question leaves the reference's trajectory and is refuted structurally; one that
  breaks it on a quantity no question asks about is not seen. Naming such a quantity in the
  candidate's own vocabulary is the open part.

## References

- Huang, X., Shen, Q., Hu, Y., Gao, A., Wang, B. "LLMs for Mathematical Modeling: Towards Bridging
  the Gap between Natural and Mathematical Languages." arXiv:2405.13144, 2024.
- Petzold, L. "Automatic Selection of Methods for Solving Stiff and Nonstiff Systems of Ordinary
  Differential Equations." SIAM Journal on Scientific and Statistical Computing 4(1):136-148, 1983.
  [doi:10.1137/0904010](https://doi.org/10.1137/0904010)
- Segura, S., Fraser, G., Sanchez, A. B., Ruiz-Cortes, A. "A Survey on Metamorphic Testing." IEEE
  Transactions on Software Engineering 42(9):805-824, 2016.
  [doi:10.1109/TSE.2016.2532875](https://doi.org/10.1109/TSE.2016.2532875)
