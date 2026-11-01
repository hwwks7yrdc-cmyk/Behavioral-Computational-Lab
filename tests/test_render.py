import dataclasses
import filecmp
import py_compile
import re

import pytest

from expbuilder.render import BuildRefused, build_app, build_docs, build_project, instructions_markdown, markdown_to_html
from conftest import EXAMPLES, ROOT
from expbuilder import load_spec


def test_app_files_and_syntax(example_spec, tmp_path):
    app = build_app(example_spec, tmp_path)
    expected = {"__init__.py", "tests.py", "instructions.html", "Introduction.html", "Comprehension.html",
                "ComprehensionFeedback.html", "Contribute.html", "Results.html", "FinalResults.html"}
    if example_spec.punishment.enabled:
        expected.add("Punish.html")
    assert expected == {p.name for p in app.iterdir()}
    py_compile.compile(str(app / "__init__.py"), doraise=True)
    py_compile.compile(str(app / "tests.py"), doraise=True)
    assert "[[" not in (app / "__init__.py").read_text() and "[%" not in (app / "Results.html").read_text()


def test_refuses_to_build_invalid_design(base, tmp_path):
    with pytest.raises(BuildRefused, match="PG001"):
        build_app(dataclasses.replace(base, mpcr=1.5), tmp_path)


def test_instructions_state_the_parameters(example_spec):
    md = instructions_markdown(example_spec)
    for value in (example_spec.endowment, example_spec.players_per_group, example_spec.num_rounds):
        assert re.search(rf"\b{value}\b", md)
    assert str(example_spec.mpcr) in md
    if example_spec.threshold.enabled:
        assert str(example_spec.threshold.amount) in md
    if example_spec.punishment.enabled:
        assert "deduction points" in md
    for loaded in ("cooperate", "fair", "team", "selfish"):
        assert loaded not in md.lower(), f"loaded wording '{loaded}' in instructions"


def test_markdown_to_html():
    html = markdown_to_html("## T\n\nA **b** c\n\n- x\n- y\n")
    assert html == "<h4>T</h4>\n<p>A <strong>b</strong> c</p>\n<ul><li>x</li><li>y</li></ul>\n"


def test_committed_project_is_up_to_date(tmp_path):
    """The oTree project in the repository must equal a fresh build from examples/*.yaml."""
    specs = [load_spec(p) for p in EXAMPLES]
    build_project(specs, tmp_path)
    committed = ROOT / "otree_project"
    for spec in specs:
        cmp = filecmp.dircmp(committed / spec.name, tmp_path / spec.name, ignore=["__pycache__"])
        assert not cmp.diff_files and not cmp.left_only and not cmp.right_only, spec.name
    assert (committed / "settings.py").read_text() == (tmp_path / "settings.py").read_text()


def test_docs(example_spec, tmp_path):
    out = build_docs(example_spec, tmp_path)
    names = {p.name for p in out.iterdir()}
    assert names == {"instructions.md", "quiz_answer_key.md", "session_checklist.md", "payoff_table.csv", "lint_report.txt", "spec.resolved.yaml"}
    assert "otree test " + example_spec.name in (out / "session_checklist.md").read_text()
