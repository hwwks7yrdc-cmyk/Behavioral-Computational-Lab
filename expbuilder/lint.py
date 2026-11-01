"""Design linter: checks a valid specification for design problems that a type check cannot catch.

Each check encodes a piece of methodological knowledge, for example that a
linear public goods game is only a social dilemma if 1/N < MPCR < 1, or that
stranger matching needs enough groups per session to be meaningful. Findings
have three levels:

* ``error``   - the design does not implement what its parameters suggest; the build is refused.
* ``warning`` - the design runs, but a reviewer is likely to object.
* ``info``    - facts worth stating in the paper or the session protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import gcd

from .games import public_goods as pg
from .spec import ExperimentSpec

LEVELS = ("error", "warning", "info")


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper():7}] {self.code}: {self.message}"


def lint(spec: ExperimentSpec) -> list[Finding]:
    f: list[Finding] = []
    add = lambda level, code, msg: f.append(Finding(level, code, msg))  # noqa: E731

    n, e, m = spec.players_per_group, spec.endowment, spec.mpcr

    # --- social dilemma condition --------------------------------------------------
    if not spec.threshold.enabled:
        if m >= 1:
            add("error", "PG001", f"MPCR = {m} >= 1: contributing is individually optimal, so the game is not a social dilemma.")
        elif m * n <= 1:
            add("error", "PG002", f"MPCR x N = {m * n:g} <= 1: full contribution is not socially efficient, so there is no dilemma to study.")
        else:
            add("info", "PG003", f"Social dilemma condition holds: 1/N = {1 / n:.3f} < MPCR = {m} < 1 (efficiency factor {m * n:g}).")
            if abs(m - 0.4) > 1e-9 and n == 4:
                add("info", "PG004", "Most four-person VCM studies use MPCR = 0.4 (e.g., Fehr & Gächter, 2000); a different value limits comparability.")
    else:
        t = spec.threshold
        if t.amount > n * e:
            add("error", "TH001", f"Threshold {t.amount} exceeds the maximum possible group contribution {n * e}.")
        if t.amount <= e:
            add("warning", "TH002", f"Threshold {t.amount} <= endowment {e}: a single member can provide the good alone, which changes the coordination problem.")
        if m >= 1:
            add("warning", "TH003", f"MPCR = {m} >= 1 above the threshold: once the good is provided, contributing more is individually profitable.")
        if not t.refund and t.bonus == 0 and m * n <= 1:
            add("error", "TH004", "Without refund, bonus or an efficient group account, contributing never pays; the threshold game has no cooperative equilibrium.")
        add("info", "TH005", f"Provision-point mechanism with {'money-back guarantee' if t.refund else 'no refund'}; threshold = {t.amount} of {n * e} ({t.amount / (n * e):.0%}).")

    # --- punishment ------------------------------------------------------------------
    p = spec.punishment
    if p.enabled:
        ratio = p.impact_per_point / p.cost_per_point
        if ratio < 1:
            add("warning", "PU001", f"Punishment impact/cost ratio = {ratio:g} < 1: punishment is weak; cooperation-sustaining effects are unlikely.")
        elif ratio != 3:
            add("info", "PU002", f"Impact/cost ratio = {ratio:g}; the canonical design uses 1:3 (Fehr & Gächter, 2000).")
        cost_cap = p.max_points * (n - 1) * p.cost_per_point
        s1_min = pg.stage1_payoffs(spec, [e] + [0] * (n - 1))[0]
        if cost_cap > s1_min:
            add("info", "PU003", f"Maximum punishment spending ({cost_cap}) can exceed stage-1 earnings ({s1_min:g}); the app enforces the budget constraint.")
        if not p.floor_at_zero:
            add("warning", "PU004", "Round earnings can become negative; check that your IRB protocol and payment rule allow losses.")
        if spec.matching == "stranger":
            add("info", "PU005", "Punishment with stranger matching removes reputational motives: deductions are costly signals without future benefit to the punisher.")

    # --- matching and session size -----------------------------------------------------
    if spec.session_size is not None:
        if spec.session_size % n != 0:
            add("error", "SE001", f"Session size {spec.session_size} is not a multiple of the group size {n}.")
        groups = spec.session_size // n
        if spec.matching == "stranger" and groups < 3:
            add("warning", "SE002", f"Stranger matching with only {groups} group(s) per session gives frequent re-matching; use >= 3 groups or a perfect-stranger protocol.")
        if groups < 2:
            add("warning", "SE003", "One group per session: session and group effects are confounded.")
        if spec.matching == "partner":
            add("info", "SE004", f"{groups} independent group(s) per session (partner matching: the group is the independent unit).")
        else:
            add("info", "SE004", f"{groups} groups per session; with stranger matching the session, not the group, is the independent unit.")
    else:
        lcm = n * 3 // gcd(n, 3)
        add("info", "SE005", f"No session_size given; with stranger matching plan at least {max(3 * n, lcm)} participants per session.")

    if spec.matching == "stranger":
        add("info", "MA001", "Observations are not independent across groups within a session; cluster standard errors at the session level (see powersim).")

    # --- rounds and timing ---------------------------------------------------------------
    if spec.num_rounds == 1:
        add("info", "RO001", "One-shot game: no learning or decay dynamics can be observed.")
    elif spec.num_rounds >= 5:
        add("info", "RO002", "Contributions typically decline over rounds with an end-game drop; announce the number of rounds in the instructions and pre-register a round-trend analysis.")
    if spec.decision_timeout_seconds is not None and spec.decision_timeout_seconds < 30:
        add("warning", "TI001", f"Decision timeout of {spec.decision_timeout_seconds}s is short; timeouts are recorded as contribution 0 and bias the outcome.")

    # --- payment -------------------------------------------------------------------------
    b = pg.round_bounds(spec)
    conv = spec.payment.points_per_currency_unit
    rounds_paid = spec.num_rounds if spec.payment.rule == "all_rounds" else 1
    stake = (b.social_optimum_round - b.nash_round) * rounds_paid / conv
    if stake < 2:
        add("warning", "PA001", f"The gain from full cooperation is only {stake:.2f} {spec.payment.currency_code} per person; stakes may be too low to be salient.")
    if spec.payment.rule == "all_rounds" and spec.num_rounds > 1:
        add("info", "PA002", "Paying all rounds allows wealth effects across rounds; random-round payment avoids them.")

    # --- comprehension -------------------------------------------------------------------
    if spec.comprehension.num_questions < 2:
        add("warning", "CQ001", "Fewer than two comprehension questions; include at least the free-riding and full-cooperation scenarios.")

    return f


def has_errors(findings: list[Finding]) -> bool:
    return any(x.level == "error" for x in findings)


def format_report(findings: list[Finding]) -> str:
    order = {lvl: i for i, lvl in enumerate(LEVELS)}
    lines = [str(x) for x in sorted(findings, key=lambda x: (order[x.level], x.code))]
    counts = {lvl: sum(1 for x in findings if x.level == lvl) for lvl in LEVELS}
    lines.append(f"\n{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} note(s)")
    return "\n".join(lines)
