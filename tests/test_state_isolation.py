"""The ledger must be per-account.

Observed live 1 Sep 2026: a single shared state file meant the first COMP cycle
read DEV's seven open positions. The monitor tried to manage legs the competition
account did not hold, and COMP's risk budget was consumed by another account's
heat — every candidate was rejected with "per_expiry budget $2".
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _config_for(account, monkeypatch):
    monkeypatch.setenv("ACCOUNT", account)
    import agent.config as cfg
    importlib.reload(cfg)
    return cfg


def test_dev_and_comp_use_different_ledgers(monkeypatch):
    dev = _config_for("dev", monkeypatch).STATE_DB
    comp = _config_for("comp", monkeypatch).STATE_DB
    assert dev != comp, "a shared ledger leaks positions between accounts"


def test_ledger_path_names_the_account(monkeypatch):
    for account in ("dev", "comp"):
        cfg = _config_for(account, monkeypatch)
        assert account in os.path.basename(cfg.STATE_DB)


def test_comp_selects_comp_credentials(monkeypatch):
    monkeypatch.setenv("COMP_ALPACA_API_KEY", "COMPKEY")
    monkeypatch.setenv("COMP_ALPACA_SECRET_KEY", "COMPSECRET")
    monkeypatch.setenv("COMP_ACCOUNT_NUMBER", "PA_COMP")
    cfg = _config_for("comp", monkeypatch)
    assert cfg.API_KEY == "COMPKEY"
    assert cfg.ACCOUNT_NUMBER == "PA_COMP"


def test_dev_selects_dev_credentials(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "DEVKEY")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "DEVSECRET")
    monkeypatch.setenv("DEV_ACCOUNT_NUMBER", "PA_DEV")
    cfg = _config_for("dev", monkeypatch)
    assert cfg.API_KEY == "DEVKEY"
    assert cfg.ACCOUNT_NUMBER == "PA_DEV"


def test_reset_env_after_module(monkeypatch):
    """Leave config back on dev so later tests are unaffected."""
    cfg = _config_for("dev", monkeypatch)
    assert cfg.ACCOUNT == "dev"
