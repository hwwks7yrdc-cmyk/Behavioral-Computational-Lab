import pytest

from expbuilder.agent import (
    DraftFailed,
    TranslationRejected,
    draft_spec,
    extract_yaml,
    numbers,
    review_instructions,
    translate_instructions,
)
from expbuilder.render import instructions_markdown

VALID = """```yaml
name: pgg_drafted
title: Drafted design
players_per_group: 4
num_rounds: 10
endowment: 20
mpcr: 0.4
punishment:
  enabled: true
```"""

NOT_A_DILEMMA = VALID.replace("mpcr: 0.4", "mpcr: 1.2")
BAD_FIELD = VALID.replace("num_rounds: 10", "rounds: 10")


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append((system, [dict(m) for m in messages]))
        return self.replies.pop(0)


def test_extract_yaml():
    assert extract_yaml(VALID).startswith("name: pgg_drafted")
    assert extract_yaml("name: x") == "name: x"


def test_draft_accepts_valid_first_try():
    r = draft_spec("4-person PGG with punishment", FakeClient([VALID]))
    assert r.iterations == 1 and r.spec.punishment.enabled


def test_draft_repairs_lint_and_schema_errors():
    client = FakeClient([NOT_A_DILEMMA, BAD_FIELD, VALID])
    r = draft_spec("4-person PGG", client)
    assert r.iterations == 3
    # the model was told exactly what was wrong
    second_prompt = client.calls[1][1][-1]["content"]
    third_prompt = client.calls[2][1][-1]["content"]
    assert "PG001" in second_prompt
    assert "rounds: unknown field" in third_prompt


def test_draft_gives_up():
    with pytest.raises(DraftFailed):
        draft_spec("x", FakeClient([NOT_A_DILEMMA] * 3), max_iterations=3)


def test_numbers_multiset():
    assert numbers("give 20 points, 0.4 each, 20 again") == {20.0: 2, 0.4: 1}


def test_translation_number_check(base):
    src = instructions_markdown(base)
    broken = src.replace("20 points", "2 points", 1)
    client = FakeClient([broken, src])          # first reply changes a number, second is faithful
    assert translate_instructions(base, client) == src
    assert "Missing" in client.calls[1][1][-1]["content"]
    with pytest.raises(TranslationRejected):
        translate_instructions(base, FakeClient([broken, broken]))


def test_review_prompt_contains_design(base):
    client = FakeClient(["1. none"])
    assert review_instructions(base, client) == "1. none"
    prompt = client.calls[0][1][0]["content"]
    assert "mpcr: 0.4" in prompt and "Comprehension questions" in prompt and "PG003" in prompt
