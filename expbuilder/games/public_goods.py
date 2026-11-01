"""Payoff model of the linear public goods game and its variants.

This module is the reference implementation of the payoff rules. The generated
oTree app re-implements the same rules (an oTree app must run without this
package installed); the test-suite plays the generated app with oTree bots and
checks every payoff against the functions below.

Round payoff of player i in a group of N with endowment E and contributions c:

    kept_i     = E - c_i                         (E if the threshold is missed and refund is on)
    provided   = (not threshold) or sum(c) >= T
    return_i   = MPCR * sum(c)       if provided else 0
    bonus_i    = B                   if threshold and provided else 0
    stage1_i   = kept_i + return_i + bonus_i

With peer punishment (Fehr & Gächter, 2000), after observing contributions each
player may assign deduction points p_ij to every other member j:

    final_i = stage1_i - cost * sum_j p_ij - impact * sum_j p_ji
    final_i = max(final_i, 0)        if floor_at_zero

Spending on punishment is limited by the punisher's stage-1 earnings.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from ..spec import ExperimentSpec

DECIMALS = 2


def _r(x: float) -> float:
    return round(float(x) + 0.0, DECIMALS)


# ------------------------------------------------------------------ stage 1
def provided(spec: ExperimentSpec, total: float) -> bool:
    return (not spec.threshold.enabled) or total >= spec.threshold.amount


def stage1_payoffs(spec: ExperimentSpec, contributions: Sequence[float]) -> list[float]:
    """Stage-1 (pre-punishment) earnings for every member of a group."""
    if len(contributions) != spec.players_per_group:
        raise ValueError(f"expected {spec.players_per_group} contributions, got {len(contributions)}")
    for c in contributions:
        if c < 0 or c > spec.endowment:
            raise ValueError(f"contribution {c} outside [0, {spec.endowment}]")
    total = sum(contributions)
    ok = provided(spec, total)
    ret = spec.mpcr * total if ok else 0.0
    bonus = spec.threshold.bonus if (spec.threshold.enabled and ok) else 0
    out = []
    for c in contributions:
        kept = spec.endowment if (spec.threshold.enabled and not ok and spec.threshold.refund) else spec.endowment - c
        out.append(_r(kept + ret + bonus))
    return out


# ------------------------------------------------------------------ stage 2
def final_payoffs(
    spec: ExperimentSpec,
    contributions: Sequence[float],
    punishment: Sequence[Sequence[int]] | None = None,
) -> list[float]:
    """Round earnings after punishment.

    ``punishment[i][j]`` is the number of points player i assigns to player j
    (diagonal entries must be zero). If punishment is disabled the matrix is ignored.
    """
    s1 = stage1_payoffs(spec, contributions)
    if not spec.punishment.enabled or punishment is None:
        return s1
    n = spec.players_per_group
    p = spec.punishment
    if len(punishment) != n or any(len(row) != n for row in punishment):
        raise ValueError("punishment matrix must be N x N")
    out = []
    for i in range(n):
        given = sum(punishment[i][j] for j in range(n) if j != i)
        received = sum(punishment[j][i] for j in range(n) if j != i)
        if punishment[i][i] != 0:
            raise ValueError("a player cannot punish themself")
        if any(punishment[i][j] < 0 or punishment[i][j] > p.max_points for j in range(n)):
            raise ValueError("punishment points outside [0, max_points]")
        if given * p.cost_per_point > s1[i] + 1e-9:
            raise ValueError(f"player {i + 1} spends more on punishment than stage-1 earnings")
        v = s1[i] - p.cost_per_point * given - p.impact_per_point * received
        if p.floor_at_zero:
            v = max(v, 0.0)
        out.append(_r(v))
    return out


# ------------------------------------------------------------------ bounds and budget
@dataclass(frozen=True)
class Bounds:
    min_round: float
    max_round: float
    social_optimum_round: float   # everyone contributes the full endowment
    nash_round: float             # everyone contributes nothing (selfish benchmark)


def round_bounds(spec: ExperimentSpec) -> Bounds:
    n, e = spec.players_per_group, spec.endowment
    all_in = stage1_payoffs(spec, [e] * n)[0]
    none = stage1_payoffs(spec, [0] * n)[0]
    # the best a single player can do: contribute 0 while all others contribute everything
    free_ride = stage1_payoffs(spec, [0] + [e] * (n - 1))[0]
    # the worst: contribute everything while nobody else does (threshold refund may soften this)
    sucker = stage1_payoffs(spec, [e] + [0] * (n - 1))[0]
    max_round = max(all_in, none, free_ride)
    min_round = min(all_in, none, sucker)
    if spec.punishment.enabled:
        p = spec.punishment
        received_max = (n - 1) * p.max_points * p.impact_per_point
        # a player can spend all stage-1 earnings on punishment and receive the maximum deduction
        min_round = 0.0 if p.floor_at_zero else -float(received_max)
    return Bounds(_r(min_round), _r(max_round), _r(all_in), _r(none))


def session_budget(spec: ExperimentSpec, participants: int) -> dict[str, float]:
    """Payment range for one session, in real currency (participation fee included)."""
    b = round_bounds(spec)
    rounds_paid = spec.num_rounds if spec.payment.rule == "all_rounds" else 1
    conv = spec.payment.points_per_currency_unit
    fee = spec.payment.participation_fee
    per_person = {
        "min": fee + b.min_round * rounds_paid / conv,
        "selfish_benchmark": fee + b.nash_round * rounds_paid / conv,
        "social_optimum": fee + b.social_optimum_round * rounds_paid / conv,
        "max": fee + b.max_round * rounds_paid / conv,
    }
    out = {f"per_person_{k}": round(v, 2) for k, v in per_person.items()}
    out.update({f"session_{k}": round(v * participants, 2) for k, v in per_person.items() if k != "max"})
    # the session maximum is bounded by the social optimum (transfers are zero-sum or destroy value)
    out["session_upper_bound"] = round(per_person["social_optimum"] * participants, 2)
    return out


# ------------------------------------------------------------------ comprehension quiz
@dataclass(frozen=True)
class QuizQuestion:
    key: str
    text: str
    answer: float
    explanation: str


def _fmt(x: float) -> str:
    x = _r(x)
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}".rstrip("0").rstrip(".")


def quiz(spec: ExperimentSpec) -> list[QuizQuestion]:
    """Deterministic comprehension questions with answers computed from the payoff model.

    The first two questions are always the canonical free-riding and cooperation
    scenarios; further questions are drawn with the spec's seed.
    """
    n, e = spec.players_per_group, spec.endowment
    rng = random.Random(spec.comprehension.seed)
    others = n - 1
    qs: list[QuizQuestion] = []

    def scenario_text(contribs):
        you, rest = contribs[0], contribs[1:]
        if len(set(rest)) == 1:
            r = f"each of the other {others} members contributes {_fmt(rest[0])} points"
        else:
            r = "the other members contribute " + ", ".join(_fmt(x) for x in rest) + " points"
        return f"You contribute {_fmt(you)} points and {r}."

    def add_stage1(key, contribs, who=0):
        pay = stage1_payoffs(spec, contribs)
        total = sum(contribs)
        whom = "your" if who == 0 else f"Member {who + 1}'s"
        txt = f"{scenario_text(contribs)} What are {whom} earnings in this round"
        txt += " before any deduction points?" if spec.punishment.enabled else "?"
        ok = provided(spec, total)
        parts = [f"Group total = {_fmt(total)}."]
        if spec.threshold.enabled:
            parts.append(
                f"The threshold of {spec.threshold.amount} is {'reached' if ok else 'not reached'}."
            )
        if ok:
            parts.append(f"Each member receives {spec.mpcr} × {_fmt(total)} = {_fmt(spec.mpcr * total)} from the group account.")
        kept = e if (spec.threshold.enabled and not ok and spec.threshold.refund) else e - contribs[who]
        parts.append(f"Kept in private account: {_fmt(kept)}.")
        if spec.threshold.enabled and ok and spec.threshold.bonus:
            parts.append(f"Bonus: {spec.threshold.bonus}.")
        parts.append(f"Earnings = {_fmt(pay[who])}.")
        qs.append(QuizQuestion(key, txt, pay[who], " ".join(parts)))

    # canonical scenarios
    add_stage1("q1", [0] + [e] * others)
    add_stage1("q2", [e] * n)

    if spec.threshold.enabled and len(qs) < spec.comprehension.num_questions:
        # a scenario just below the threshold, to make the refund rule salient
        target = max(0, spec.threshold.amount - 1)
        contribs = [0] * n
        remaining = min(target, n * e)
        for i in range(n):
            contribs[i] = min(e, remaining)
            remaining -= contribs[i]
        add_stage1(f"q{len(qs) + 1}", contribs)

    if spec.punishment.enabled and len(qs) < spec.comprehension.num_questions:
        p = spec.punishment
        pts = min(p.max_points, max(1, p.max_points // 3))
        qs.append(
            QuizQuestion(
                f"q{len(qs) + 1}",
                f"In the deduction stage you assign {pts} points to Member 2. By how many points are your own earnings reduced?",
                pts * p.cost_per_point,
                f"Each point you assign costs you {p.cost_per_point}: {pts} × {p.cost_per_point} = {pts * p.cost_per_point}.",
            )
        )
        if len(qs) < spec.comprehension.num_questions:
            qs.append(
                QuizQuestion(
                    f"q{len(qs) + 1}",
                    f"Member 2 receives {pts} deduction points in total. By how many points are Member 2's earnings reduced?",
                    pts * p.impact_per_point,
                    f"Each point received reduces earnings by {p.impact_per_point}: {pts} × {p.impact_per_point} = {pts * p.impact_per_point}.",
                )
            )

    while len(qs) < spec.comprehension.num_questions:
        contribs = [rng.randint(0, e) for _ in range(n)]
        who = 0 if rng.random() < 0.6 else rng.randint(1, n - 1)
        add_stage1(f"q{len(qs) + 1}", contribs, who)

    return qs[: spec.comprehension.num_questions]
