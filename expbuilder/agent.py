"""LLM agent layer: drafting specifications, reviewing instructions, and translating them.

The agent never writes oTree code and never computes payoffs. It works only on the
two places where language models help and deterministic code cannot:

1. ``draft_spec``  turns a plain-language design description into a YAML
   specification. Every draft is parsed and linted; parse or lint errors are sent
   back to the model, which repairs the draft (up to ``max_iterations`` turns).
   The result is a specification a researcher reads and approves; the app is then
   generated deterministically from it.
2. ``review_instructions`` asks the model for a critical reading of the generated
   participant instructions (ambiguity, loaded wording, demand effects).
3. ``translate_instructions`` translates the instructions and rejects any
   translation in which a number changed, was dropped or was added.

The client is injected, so the logic is fully testable without network access.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

import yaml

from .lint import Finding, format_report, has_errors, lint
from .render import instructions_markdown
from .games import public_goods as pg
from .spec import ExperimentSpec, SpecError, loads_spec

DEFAULT_MODEL = os.environ.get("EXPBUILDER_MODEL", "claude-sonnet-5-5")


class LLMClient(Protocol):
    def complete(self, system: str, messages: list[dict]) -> str:
        """Return the assistant's reply to a list of {'role', 'content'} messages."""


class AnthropicClient:
    """Thin wrapper around the Anthropic Messages API (requires ``pip install anthropic`` and ANTHROPIC_API_KEY)."""

    def __init__(self, model: str | None = None, max_tokens: int = 4000, temperature: float = 0.0):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on optional dependency
            raise RuntimeError("Install the optional dependency: pip install 'lab-experiment-toolkit[agent]'") from exc
        self._client = anthropic.Anthropic()
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens
        self.temperature = temperature

    def complete(self, system: str, messages: list[dict]) -> str:  # pragma: no cover - network
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=messages,
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")


# ------------------------------------------------------------------ drafting
SCHEMA_EXAMPLE = """\
name: pgg_example            # lower_snake_case, used as the oTree app name
title: Public Goods Game     # shown to experimenters
game: public_goods
players_per_group: 4
num_rounds: 10
endowment: 20                # integer points per round
mpcr: 0.4                    # marginal per-capita return; social dilemma requires 1/N < mpcr < 1
matching: partner            # partner | stranger
show_history: true
decision_timeout_seconds: 90 # or null
session_size: 16             # participants per session, a multiple of players_per_group
punishment:
  enabled: false
  max_points: 10
  cost_per_point: 1
  impact_per_point: 3
  floor_at_zero: true
threshold:
  enabled: false
  amount: 0
  refund: true
  bonus: 0
payment:
  rule: random_round         # random_round | all_rounds
  points_per_currency_unit: 2
  currency_code: CNY
  participation_fee: 15
comprehension:
  num_questions: 4
  max_attempts: 3
  seed: 2026
"""

DRAFT_SYSTEM = f"""You translate descriptions of laboratory experiments into a YAML specification for a public goods game generator.

Rules:
- Output exactly one YAML document inside a ```yaml code block and nothing else.
- Use only the fields in this schema; omit fields to keep their defaults:

{SCHEMA_EXAMPLE}
- Do not invent design features that the description does not mention. Where the description is silent, keep the default.
- If the description asks for something the schema cannot express, keep the closest valid design and add a short `notes:` field explaining the gap.
"""


class DraftFailed(RuntimeError):
    def __init__(self, transcript: list[dict]):
        self.transcript = transcript
        super().__init__(f"No valid specification after {len([m for m in transcript if m['role'] == 'assistant'])} attempt(s).")


@dataclass
class DraftResult:
    spec: ExperimentSpec
    findings: list[Finding]
    iterations: int
    transcript: list[dict] = field(default_factory=list)


def extract_yaml(text: str) -> str:
    m = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, flags=re.S)
    return (m.group(1) if m else text).strip()


def draft_spec(description: str, client: LLMClient, max_iterations: int = 3) -> DraftResult:
    """Draft a specification from a description; validate, lint and repair until it builds."""
    messages: list[dict] = [{"role": "user", "content": description.strip()}]
    for i in range(1, max_iterations + 1):
        reply = client.complete(DRAFT_SYSTEM, messages)
        messages.append({"role": "assistant", "content": reply})
        problem = None
        try:
            spec = loads_spec(extract_yaml(reply))
        except yaml.YAMLError as exc:
            problem = f"The YAML could not be parsed: {exc}"
        except SpecError as exc:
            problem = str(exc)
        else:
            findings = lint(spec)
            if not has_errors(findings):
                return DraftResult(spec, findings, i, messages)
            problem = "The design violates these rules:\n" + format_report([f for f in findings if f.level == "error"])
        messages.append(
            {
                "role": "user",
                "content": f"{problem}\n\nReturn a corrected YAML document that still matches the original description.",
            }
        )
    raise DraftFailed(messages)


# ------------------------------------------------------------------ review
REVIEW_SYSTEM = """You are an experienced experimental economist reviewing participant instructions before a laboratory session.
Report concrete problems only, as a numbered list, each with the exact sentence and a suggested rewrite:
1. statements a participant could misunderstand or that are ambiguous;
2. loaded or suggestive wording that could create demand effects (e.g., 'cooperate', 'fair', 'team');
3. inconsistencies between the instructions, the quiz and the design parameters.
Never change numbers or payoff rules. If there is nothing to report in a category, write 'none'."""


def review_instructions(spec: ExperimentSpec, client: LLMClient) -> str:
    quiz = "\n".join(f"- {q.text} (answer: {q.answer})" for q in pg.quiz(spec))
    user = (
        f"Design parameters (YAML):\n```yaml\n{spec.to_yaml()}```\n\n"
        f"Participant instructions:\n\n{instructions_markdown(spec)}\n\n"
        f"Comprehension questions:\n{quiz}\n\n"
        f"Automated design checks:\n{format_report(lint(spec))}"
    )
    return client.complete(REVIEW_SYSTEM, [{"role": "user", "content": user}])


# ------------------------------------------------------------------ translation
_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")


def numbers(text: str) -> Counter:
    """Multiset of numbers in a text (used to verify translations)."""
    return Counter(float(x) for x in _NUM.findall(text))


class TranslationRejected(RuntimeError):
    pass


def translate_instructions(spec: ExperimentSpec, client: LLMClient, language: str = "Simplified Chinese", max_iterations: int = 2) -> str:
    source = instructions_markdown(spec)
    system = (
        f"Translate the participant instructions into {language}. Keep the Markdown structure and every number exactly as in the source; "
        "write numbers with Arabic digits. Use neutral wording: 'group account', 'private account', 'points'. Output only the translation."
    )
    messages = [{"role": "user", "content": source}]
    want = numbers(source)
    for _ in range(max_iterations):
        out = client.complete(system, messages)
        got = numbers(out)
        if got == want:
            return out
        missing, extra = want - got, got - want
        messages += [
            {"role": "assistant", "content": out},
            {
                "role": "user",
                "content": f"The numbers do not match the source. Missing: {dict(missing)}; unexpected: {dict(extra)}. Return a corrected translation.",
            },
        ]
    raise TranslationRejected("translation changed the numbers in the instructions; review manually")
