"""Code and document generation from a validated specification."""
from __future__ import annotations

import csv
import html
import io
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import __version__
from .games import GAMES
from .games import public_goods as pg
from .lint import format_report, has_errors, lint
from .spec import ExperimentSpec

TEMPLATES = Path(__file__).parent / "templates"


class BuildRefused(RuntimeError):
    """Raised when the linter reports errors; the report is attached."""


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        comment_start_string="[#",
        comment_end_string="#]",
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.filters["pyrepr"] = repr
    return env


def _fmt(x: float) -> str:
    return pg._fmt(x)


def _context(spec: ExperimentSpec) -> dict:
    quiz = pg.quiz(spec)
    example_contribs = _example_contributions(spec)
    pay = pg.stage1_payoffs(spec, example_contribs)
    total = sum(example_contribs)
    ok = pg.provided(spec, total)
    others = ", ".join(_fmt(c) for c in example_contribs[1:])
    ex_text = (
        f"Suppose you contribute {_fmt(example_contribs[0])} points and the other members contribute "
        f"{others} points. The group account then contains {_fmt(total)} points."
    )
    if spec.threshold.enabled:
        ex_text += f" This {'reaches' if ok else 'does not reach'} the threshold of {spec.threshold.amount}."
    kept = spec.endowment if (spec.threshold.enabled and not ok and spec.threshold.refund) else spec.endowment - example_contribs[0]
    expl = f"Your earnings: {_fmt(kept)} points in your private account"
    if ok:
        expl += f" + {_fmt(spec.mpcr * total)} points from the group account ({spec.mpcr} × {_fmt(total)})"
    if spec.threshold.enabled and ok and spec.threshold.bonus:
        expl += f" + {spec.threshold.bonus} points bonus"
    expl += f" = **{_fmt(pay[0])} points**. A member who contributed {_fmt(example_contribs[1])} earns {_fmt(pay[1])} points."
    conv = spec.payment.points_per_currency_unit
    return dict(
        spec=spec,
        n=spec.players_per_group,
        e=spec.endowment,
        members=list(range(1, spec.players_per_group + 1)),
        quiz=quiz,
        example=dict(text=ex_text, explanation=expl),
        conv=_fmt(conv),
        fee=f"{spec.payment.participation_fee:.2f}",
        version=__version__,
        spec_json=json.dumps(spec.to_dict(), sort_keys=True),
    )


def _example_contributions(spec: ExperimentSpec) -> list[int]:
    """A readable, asymmetric example: you contribute half, others contribute spread values."""
    n, e = spec.players_per_group, spec.endowment
    you = e // 2
    others = [round(e * k / max(1, n - 1)) for k in range(n - 1, 0, -1)][: n - 1]
    others = [min(e, max(0, o)) for o in others]
    contribs = [you] + others
    if spec.threshold.enabled and sum(contribs) < spec.threshold.amount <= n * e:
        contribs = [e // 2] + [e] * (n - 1)
    return contribs


# ------------------------------------------------------------------ markdown -> html
def markdown_to_html(md: str) -> str:
    """Minimal Markdown for instructions: ##/### headings, paragraphs, '-' lists, **bold**."""
    def inline(s: str) -> str:
        s = html.escape(s, quote=False)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

    out, para, items = [], [], []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in md.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("### "):
            flush()
            out.append(f"<h5>{inline(s[4:])}</h5>")
        elif s.startswith("## "):
            flush()
            out.append(f"<h4>{inline(s[3:])}</h4>")
        elif s.startswith("- "):
            if para:
                flush()
            items.append(s[2:])
        else:
            if items:
                flush()
            para.append(s)
    flush()
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ builders
def instructions_markdown(spec: ExperimentSpec) -> str:
    text = _env().get_template(f"{spec.game}/instructions.md.j2").render(**_context(spec))
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def build_app(spec: ExperimentSpec, apps_dir: str | Path, *, force: bool = False) -> Path:
    """Write the oTree app for ``spec`` into ``apps_dir/<spec.name>``. Refuses to build on lint errors."""
    if spec.game not in GAMES:
        raise ValueError(f"unsupported game {spec.game}")
    findings = lint(spec)
    if has_errors(findings) and not force:
        raise BuildRefused(format_report(findings))
    env = _env()
    ctx = _context(spec)
    app = Path(apps_dir) / spec.name
    app.mkdir(parents=True, exist_ok=True)

    (app / "__init__.py").write_text(env.get_template(f"{spec.game}/__init__.py.j2").render(**ctx), encoding="utf-8")
    (app / "tests.py").write_text(env.get_template(f"{spec.game}/tests.py.j2").render(**ctx), encoding="utf-8")
    (app / "instructions.html").write_text(markdown_to_html(instructions_markdown(spec)), encoding="utf-8")

    pages = env.get_template(f"{spec.game}/pages.j2").render(**ctx)
    for chunk in re.split(r"^=== ", pages, flags=re.M)[1:]:
        name, _, body = chunk.partition("\n")
        (app / name.strip()).write_text(body.strip() + "\n", encoding="utf-8")
    return app


def payoff_table_csv(spec: ExperimentSpec) -> str:
    """Your stage-1 earnings for your contribution x the others' average contribution."""
    n, e = spec.players_per_group, spec.endowment
    step = max(1, e // 4)
    levels = sorted(set(list(range(0, e + 1, step)) + [e]))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["your_contribution \\ others_each"] + levels)
    for c in levels:
        w.writerow([c] + [pg.stage1_payoffs(spec, [c] + [o] * (n - 1))[0] for o in levels])
    return buf.getvalue()


def quiz_answer_key(spec: ExperimentSpec) -> str:
    lines = [f"# Comprehension quiz – answer key ({spec.name})", ""]
    for i, q in enumerate(pg.quiz(spec), 1):
        lines += [f"**{i}. {q.text}**", "", f"Answer: **{_fmt(q.answer)}**. {q.explanation}", ""]
    return "\n".join(lines)


def session_checklist(spec: ExperimentSpec) -> str:
    n = spec.players_per_group
    size = spec.session_size or (n * 4)
    b = pg.round_bounds(spec)
    budget = pg.session_budget(spec, size)
    cur = spec.payment.currency_code
    minutes = 10 + 4 + spec.num_rounds * (2.5 if spec.punishment.enabled else 1.5) + 8
    lines = [
        f"# Session checklist – {spec.title}",
        "",
        f"Session config: `{spec.name}` · participants per session: **{size}** ({size // n} groups of {n}) · "
        f"{spec.num_rounds} round(s), {spec.matching} matching.",
        "",
        "## Before the session",
        f"- [ ] Run `otree test {spec.name}` and confirm all bot cases pass.",
        f"- [ ] Create the session in the oTree admin with exactly a multiple of {n} participants (room links or session-wide link).",
        "- [ ] Print the instructions (instructions.md) and the payment receipts; keep the quiz answer key at the experimenter desk.",
        "- [ ] Check that the IRB-approved consent form is the one shown to participants.",
        f"- [ ] Prepare cash or transfer for up to {budget['session_upper_bound']:.2f} {cur} "
        f"(expected range {budget['session_selfish_benchmark']:.2f}–{budget['session_social_optimum']:.2f} {cur}).",
        "",
        "## During the session",
        "- [ ] Read the instructions aloud while participants follow on screen (common knowledge of the rules).",
        f"- [ ] Watch the monitor for participants stuck on the quiz (max {spec.comprehension.max_attempts} attempts; failures are recorded in `quiz_gave_up`).",
        "- [ ] Do not answer questions about strategy; repeat the relevant part of the instructions instead.",
        "- [ ] Note any irregularities (late arrivals, crashes, talking) in the session log with the participant code.",
        "",
        "## After the session",
        "- [ ] Download the data via *Data → Custom export* (tidy long format) and the standard *All apps* export.",
        "- [ ] Pay participants privately using the payment report; record payments against participant codes.",
        "- [ ] Store data according to the data management plan; remove direct identifiers.",
        "",
        "## Key numbers",
        f"- Estimated duration: about {round(minutes / 5) * 5} minutes.",
        f"- Earnings per round: {b.min_round:g} to {b.max_round:g} points (all contribute: {b.social_optimum_round:g}; nobody contributes: {b.nash_round:g}).",
        f"- Payment per person: {budget['per_person_min']:.2f} to {budget['per_person_max']:.2f} {cur} incl. participation fee "
        f"of {spec.payment.participation_fee:.2f} {cur}.",
        "",
    ]
    return "\n".join(lines)


def build_docs(spec: ExperimentSpec, docs_dir: str | Path) -> Path:
    out = Path(docs_dir) / spec.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "instructions.md").write_text(instructions_markdown(spec), encoding="utf-8")
    (out / "quiz_answer_key.md").write_text(quiz_answer_key(spec), encoding="utf-8")
    (out / "session_checklist.md").write_text(session_checklist(spec), encoding="utf-8")
    (out / "payoff_table.csv").write_text(payoff_table_csv(spec), encoding="utf-8")
    (out / "lint_report.txt").write_text(format_report(lint(spec)) + "\n", encoding="utf-8")
    (out / "spec.resolved.yaml").write_text(spec.to_yaml(), encoding="utf-8")
    return out


SETTINGS_TEMPLATE = '''"""oTree project settings (generated by expbuilder {version})."""
from os import environ

SESSION_CONFIGS = [
{configs}]

SESSION_CONFIG_DEFAULTS = dict(
    real_world_currency_per_point={rate},
    participation_fee={fee},
    doc="",
)

PARTICIPANT_FIELDS = []
SESSION_FIELDS = []

LANGUAGE_CODE = "en"
REAL_WORLD_CURRENCY_CODE = "{currency}"
USE_POINTS = True
POINTS_DECIMAL_PLACES = 2

ROOMS = [
    dict(name="lab", display_name="Experimental lab"),
]

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = environ.get("OTREE_ADMIN_PASSWORD")

DEMO_PAGE_INTRO_HTML = """Public goods game variants generated with expbuilder."""

SECRET_KEY = environ.get("OTREE_SECRET_KEY", "change-me-before-deployment")

INSTALLED_APPS = ["otree"]
'''


PAGE_HTML = """{% extends "otree/Page.html" %}
{% load otree static %}

{% block global_styles %}
{% endblock %}

{% block global_scripts %}
{% endblock %}
"""


def build_project(specs: list[ExperimentSpec], project_dir: str | Path, *, force: bool = False) -> Path:
    """Write a complete oTree project with one app and one session config per specification."""
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    if not specs:
        raise ValueError("no specifications given")
    currencies = {s.payment.currency_code for s in specs}
    if len(currencies) > 1:
        raise ValueError(f"all specifications in one project must use the same currency, got {currencies}")
    configs = ""
    for s in specs:
        build_app(s, project, force=force)
        size = s.session_size or s.players_per_group * 2
        configs += (
            "    dict(\n"
            f"        name={s.name!r},\n"
            f"        display_name={s.title!r},\n"
            f"        app_sequence=[{s.name!r}],\n"
            f"        num_demo_participants={size},\n"
            f"        real_world_currency_per_point={round(1 / s.payment.points_per_currency_unit, 6)},\n"
            f"        participation_fee={s.payment.participation_fee},\n"
            "    ),\n"
        )
    first = specs[0]
    (project / "settings.py").write_text(
        SETTINGS_TEMPLATE.format(
            version=__version__,
            configs=configs,
            rate=round(1 / first.payment.points_per_currency_unit, 6),
            fee=first.payment.participation_fee,
            currency=first.payment.currency_code,
        ),
        encoding="utf-8",
    )
    (project / "requirements.txt").write_text("otree>=5.10,<6\npsycopg2>=2.8.4\n", encoding="utf-8")
    (project / "Procfile").write_text("web: otree prodserver1of2\nworker: otree prodserver2of2\n", encoding="utf-8")
    (project / "_static" / "global").mkdir(parents=True, exist_ok=True)
    (project / "_static" / "global" / "empty.css").write_text("", encoding="utf-8")
    (project / "_templates" / "global").mkdir(parents=True, exist_ok=True)
    (project / "_templates" / "global" / "Page.html").write_text(PAGE_HTML, encoding="utf-8")
    (project / ".gitignore").write_text("__pycache__/\n*.sqlite3\ndb.sqlite3\n.env\n_bots_*\n", encoding="utf-8")
    return project
