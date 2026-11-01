import dataclasses

import pytest

from expbuilder.spec import SpecError, loads_spec, parse_spec


def test_examples_parse(example_spec):
    assert example_spec.players_per_group == 4
    assert example_spec.multiplier == pytest.approx(example_spec.mpcr * 4)


def test_roundtrip_yaml(example_spec):
    assert loads_spec(example_spec.to_yaml()) == example_spec


def test_all_problems_reported_at_once():
    with pytest.raises(SpecError) as exc:
        parse_spec({"name": "Bad Name", "title": "x", "players_per_group": 1, "mpcr": -1, "matching": "random"})
    text = str(exc.value)
    for fragment in ("name:", "players_per_group", "mpcr", "matching"):
        assert fragment in text


def test_unknown_fields_rejected():
    with pytest.raises(SpecError, match="unknown field"):
        parse_spec({"name": "abc", "title": "x", "punishmnet": {}})
    with pytest.raises(SpecError, match="punishment.cost"):
        parse_spec({"name": "abc", "title": "x", "punishment": {"cost": 1}})


def test_required_fields():
    with pytest.raises(SpecError, match="name: required"):
        parse_spec({"title": "x"})


def test_bool_is_not_int():
    with pytest.raises(SpecError, match="endowment"):
        parse_spec({"name": "abc", "title": "x", "endowment": True})


def test_threshold_requires_amount():
    with pytest.raises(SpecError, match="threshold.amount"):
        parse_spec({"name": "abc", "title": "x", "threshold": {"enabled": True, "amount": 0}})


def test_spec_is_immutable(base):
    with pytest.raises(dataclasses.FrozenInstanceError):
        base.endowment = 10
