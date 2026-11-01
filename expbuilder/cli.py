"""Command line interface.

    expbuilder lint     examples/pgg_punishment.yaml
    expbuilder build    examples/*.yaml --project otree_project --docs docs/generated
    expbuilder draft    "Four-person public goods game with peer punishment, 10 rounds" -o my_design.yaml
    expbuilder review   examples/pgg_punishment.yaml
    expbuilder translate examples/pgg_punishment.yaml --language "Simplified Chinese"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .lint import format_report, has_errors, lint
from .render import BuildRefused, build_docs, build_project
from .spec import SpecError, load_spec


def _load_all(paths):
    specs = []
    for p in paths:
        try:
            specs.append(load_spec(p))
        except SpecError as exc:
            print(f"{p}:\n{exc}", file=sys.stderr)
            raise SystemExit(2)
    return specs


def cmd_lint(a) -> int:
    worst = 0
    for spec in _load_all(a.specs):
        findings = lint(spec)
        print(f"== {spec.name}")
        print(format_report(findings))
        if has_errors(findings):
            worst = 1
    return worst


def cmd_build(a) -> int:
    specs = _load_all(a.specs)
    try:
        project = build_project(specs, a.project, force=a.force)
    except BuildRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"oTree project written to {project}")
    if a.docs:
        for s in specs:
            print(f"materials for {s.name}: {build_docs(s, a.docs)}")
    return 0


def _client(a):
    from .agent import AnthropicClient

    return AnthropicClient(model=a.model)


def cmd_draft(a) -> int:
    from .agent import DraftFailed, draft_spec

    try:
        result = draft_spec(a.description, _client(a), max_iterations=a.max_iterations)
    except DraftFailed as exc:
        print(str(exc), file=sys.stderr)
        return 1
    text = result.spec.to_yaml()
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"specification written to {a.output} after {result.iterations} iteration(s)")
    else:
        print(text)
    print(format_report(result.findings), file=sys.stderr)
    return 0


def cmd_review(a) -> int:
    from .agent import review_instructions

    print(review_instructions(load_spec(a.spec), _client(a)))
    return 0


def cmd_translate(a) -> int:
    from .agent import translate_instructions

    print(translate_instructions(load_spec(a.spec), _client(a), language=a.language))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="expbuilder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("lint", help="check specifications for design problems")
    p.add_argument("specs", nargs="+")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("build", help="generate an oTree project (and session materials)")
    p.add_argument("specs", nargs="+")
    p.add_argument("--project", default="otree_project")
    p.add_argument("--docs", default=None, help="directory for instructions, answer keys and checklists")
    p.add_argument("--force", action="store_true", help="build even if the linter reports errors")
    p.set_defaults(func=cmd_build)

    for name, func, helptext in (
        ("draft", cmd_draft, "draft a specification from a plain-language description (LLM)"),
        ("review", cmd_review, "LLM review of the generated participant instructions"),
        ("translate", cmd_translate, "translate the instructions with a number-preservation check (LLM)"),
    ):
        p = sub.add_parser(name, help=helptext)
        if name == "draft":
            p.add_argument("description")
            p.add_argument("-o", "--output")
            p.add_argument("--max-iterations", type=int, default=3)
        else:
            p.add_argument("spec")
        if name == "translate":
            p.add_argument("--language", default="Simplified Chinese")
        p.add_argument("--model", default=None)
        p.set_defaults(func=func)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
