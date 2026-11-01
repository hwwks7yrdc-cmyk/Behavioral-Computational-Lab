from pathlib import Path

import pytest

from expbuilder import load_spec

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.yaml"))


@pytest.fixture(params=EXAMPLES, ids=lambda p: p.stem)
def example_spec(request):
    return load_spec(request.param)


@pytest.fixture
def base():
    return load_spec(ROOT / "examples" / "pgg_partner.yaml")
