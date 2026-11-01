"""Runs the generated oTree apps with their bots (all cases). Skipped if oTree is not installed."""
import shutil
import subprocess

import pytest

from conftest import EXAMPLES, ROOT

pytestmark = pytest.mark.skipif(shutil.which("otree") is None, reason="oTree not installed")


@pytest.mark.parametrize("app", [p.stem for p in EXAMPLES])
def test_bots(app):
    res = subprocess.run(["otree", "test", app], cwd=ROOT / "otree_project", capture_output=True, text=True, timeout=900)
    out = res.stdout + res.stderr
    assert res.returncode == 0, out[-3000:]
    assert out.count("Bots completed session") == 3, out[-3000:]
