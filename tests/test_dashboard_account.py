"""The public dashboard must show the account judges will score.

It is the demo URL in the submission. Publishing DEV's numbers as if they were
the competition result would be a misrepresentation, and easy to do by accident
since the exporter is a routine script.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = Path(__file__).resolve().parent.parent / "scripts" / "export_dashboard.py"


def test_account_is_forced_to_comp_by_default():
    src = SRC.read_text()
    m = re.search(r'os\.environ\["ACCOUNT"\]\s*=\s*os\.environ\.get\(\s*"DASHBOARD_ACCOUNT",\s*"comp"\s*\)', src)
    assert m, "exporter must default ACCOUNT to comp"


def test_env_is_set_before_agent_config_is_imported():
    """config resolves ACCOUNT at import time, so ordering is the whole fix."""
    src = SRC.read_text()
    set_at = src.index('os.environ["ACCOUNT"]')
    import_at = src.index("from agent import config")
    assert set_at < import_at, (
        "ACCOUNT is set after agent.config is imported, so it has no effect — "
        "this exact ordering bug published DEV's numbers on 1 Sep")


def test_override_is_still_possible():
    src = SRC.read_text()
    assert "DASHBOARD_ACCOUNT" in src, "must remain overridable for local testing"
