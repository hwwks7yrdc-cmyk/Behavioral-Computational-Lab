"""Experiment specification: a typed, validated description of one experimental design.

A specification is written in YAML by the researcher (or drafted by the agent in
``expbuilder.agent``) and is the single source of truth for everything the
pipeline produces: the oTree app, the participant instructions, the
comprehension quiz and its answer key, and the session checklist.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_GAMES = ("public_goods",)
MATCHING = ("partner", "stranger")
PAYMENT = ("all_rounds", "random_round")


class SpecError(ValueError):
    """Raised when a specification cannot be parsed into a valid design."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Invalid experiment specification:\n  - " + "\n  - ".join(problems))


@dataclass(frozen=True)
class Punishment:
    enabled: bool = False
    max_points: int = 10          # maximum deduction points one player may assign to one other player
    cost_per_point: int = 1       # cost to the punisher per point assigned
    impact_per_point: int = 3     # reduction in the target's earnings per point received
    floor_at_zero: bool = True    # round earnings cannot fall below zero (Fehr & Gächter, 2000)


@dataclass(frozen=True)
class Threshold:
    enabled: bool = False
    amount: int = 0               # total contribution required for the public good to be provided
    refund: bool = True           # contributions are returned if the threshold is missed
    bonus: int = 0                # additional per-member payoff if the threshold is met


@dataclass(frozen=True)
class Payment:
    rule: str = "random_round"    # "all_rounds" or "random_round"
    points_per_currency_unit: float = 10.0
    currency_code: str = "CNY"
    participation_fee: float = 15.0


@dataclass(frozen=True)
class Comprehension:
    num_questions: int = 4
    max_attempts: int = 3
    seed: int = 2026


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    title: str
    game: str = "public_goods"
    players_per_group: int = 4
    num_rounds: int = 10
    endowment: int = 20
    mpcr: float = 0.4
    matching: str = "partner"
    show_history: bool = True
    decision_timeout_seconds: int | None = 90
    punishment: Punishment = field(default_factory=Punishment)
    threshold: Threshold = field(default_factory=Threshold)
    payment: Payment = field(default_factory=Payment)
    comprehension: Comprehension = field(default_factory=Comprehension)
    session_size: int | None = None    # planned participants per session (used by the linter and checklist)
    notes: str = ""

    # ------------------------------------------------------------------ helpers
    @property
    def multiplier(self) -> float:
        """Efficiency factor of the public good (MPCR x group size)."""
        return round(self.mpcr * self.players_per_group, 10)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------- parsing
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def _sub(cls, data: Any, path: str, problems: list[str]):
    if data is None:
        return cls()
    if not isinstance(data, dict):
        problems.append(f"{path}: expected a mapping, got {type(data).__name__}")
        return cls()
    allowed = set(cls.__dataclass_fields__)
    unknown = set(data) - allowed
    for key in sorted(unknown):
        problems.append(f"{path}.{key}: unknown field (allowed: {', '.join(sorted(allowed))})")
    kwargs = {k: v for k, v in data.items() if k in allowed}
    try:
        return cls(**kwargs)
    except TypeError as exc:  # pragma: no cover - defensive
        problems.append(f"{path}: {exc}")
        return cls()


def _check_type(value, types, path, problems, *, positive=False, minimum=None):
    if isinstance(value, bool) and bool not in (types if isinstance(types, tuple) else (types,)):
        problems.append(f"{path}: expected {types}, got bool")
        return
    if not isinstance(value, types):
        problems.append(f"{path}: expected {getattr(types, '__name__', types)}, got {type(value).__name__}")
        return
    if positive and value <= 0:
        problems.append(f"{path}: must be > 0 (got {value})")
    if minimum is not None and value < minimum:
        problems.append(f"{path}: must be >= {minimum} (got {value})")


def parse_spec(data: dict[str, Any]) -> ExperimentSpec:
    """Parse and type-check a raw mapping. Raises SpecError listing every problem found."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise SpecError(["top level: expected a mapping"])

    nested = {
        "punishment": Punishment,
        "threshold": Threshold,
        "payment": Payment,
        "comprehension": Comprehension,
    }
    allowed = set(ExperimentSpec.__dataclass_fields__)
    for key in sorted(set(data) - allowed):
        problems.append(f"{key}: unknown field")
    for key in ("name", "title"):
        if key not in data:
            problems.append(f"{key}: required")

    kwargs = {k: v for k, v in data.items() if k in allowed and k not in nested}
    for key, cls in nested.items():
        kwargs[key] = _sub(cls, data.get(key), key, problems)

    if problems:
        raise SpecError(problems)

    spec = ExperimentSpec(**kwargs)

    # --- field-level type and range checks (hard errors) ---
    if not isinstance(spec.name, str) or not _NAME_RE.match(spec.name):
        problems.append("name: must be lower_snake_case, 2-41 characters, starting with a letter (used as oTree app name)")
    _check_type(spec.title, str, "title", problems)
    if spec.game not in SUPPORTED_GAMES:
        problems.append(f"game: must be one of {SUPPORTED_GAMES}")
    _check_type(spec.players_per_group, int, "players_per_group", problems, minimum=2)
    _check_type(spec.num_rounds, int, "num_rounds", problems, minimum=1)
    _check_type(spec.endowment, int, "endowment", problems, positive=True)
    _check_type(spec.mpcr, (int, float), "mpcr", problems, positive=True)
    if spec.matching not in MATCHING:
        problems.append(f"matching: must be one of {MATCHING}")
    _check_type(spec.show_history, bool, "show_history", problems)
    if spec.decision_timeout_seconds is not None:
        _check_type(spec.decision_timeout_seconds, int, "decision_timeout_seconds", problems, positive=True)
    if spec.session_size is not None:
        _check_type(spec.session_size, int, "session_size", problems, positive=True)

    p = spec.punishment
    _check_type(p.enabled, bool, "punishment.enabled", problems)
    _check_type(p.max_points, int, "punishment.max_points", problems, minimum=1)
    _check_type(p.cost_per_point, int, "punishment.cost_per_point", problems, positive=True)
    _check_type(p.impact_per_point, int, "punishment.impact_per_point", problems, positive=True)
    _check_type(p.floor_at_zero, bool, "punishment.floor_at_zero", problems)

    t = spec.threshold
    _check_type(t.enabled, bool, "threshold.enabled", problems)
    _check_type(t.amount, int, "threshold.amount", problems, minimum=0)
    _check_type(t.refund, bool, "threshold.refund", problems)
    _check_type(t.bonus, int, "threshold.bonus", problems, minimum=0)
    if t.enabled and isinstance(t.amount, int) and t.amount <= 0:
        problems.append("threshold.amount: must be > 0 when the threshold is enabled")

    pay = spec.payment
    if pay.rule not in PAYMENT:
        problems.append(f"payment.rule: must be one of {PAYMENT}")
    _check_type(pay.points_per_currency_unit, (int, float), "payment.points_per_currency_unit", problems, positive=True)
    _check_type(pay.currency_code, str, "payment.currency_code", problems)
    _check_type(pay.participation_fee, (int, float), "payment.participation_fee", problems, minimum=0)

    c = spec.comprehension
    _check_type(c.num_questions, int, "comprehension.num_questions", problems, minimum=1)
    _check_type(c.max_attempts, int, "comprehension.max_attempts", problems, minimum=1)
    _check_type(c.seed, int, "comprehension.seed", problems)

    if problems:
        raise SpecError(problems)
    return spec


def load_spec(path: str | Path) -> ExperimentSpec:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return parse_spec(data)


def loads_spec(text: str) -> ExperimentSpec:
    return parse_spec(yaml.safe_load(text))
