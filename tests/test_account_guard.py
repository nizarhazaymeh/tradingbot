"""Keys are issued per paper account, and Alpaca's dashboard issues them for
whichever account is ACTIVE — so pasting DEV keys into a COMP slot is an easy
mistake that would either contaminate the judged account or leave it empty.
"""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest.mock import patch
from agent.client import AlpacaClient


def _client(number):
    with patch.object(AlpacaClient, "account", return_value={"account_number": number}):
        yield


def test_assert_account_passes_on_match():
    c = AlpacaClient(key="k", secret="s")
    with patch.object(c, "account", return_value={"account_number": "PA3BAT1OOEFE"}):
        assert c.assert_account("PA3BAT1OOEFE")["account_number"] == "PA3BAT1OOEFE"


def test_assert_account_raises_on_mismatch():
    c = AlpacaClient(key="k", secret="s")
    with patch.object(c, "account", return_value={"account_number": "PA349BYK6I13"}):
        with pytest.raises(RuntimeError, match="ACCOUNT MISMATCH"):
            c.assert_account("PA3BAT1OOEFE")


def test_mismatch_names_both_accounts():
    c = AlpacaClient(key="k", secret="s")
    with patch.object(c, "account", return_value={"account_number": "PA349BYK6I13"}):
        try:
            c.assert_account("PA3BAT1OOEFE")
            assert False
        except RuntimeError as e:
            assert "PA349BYK6I13" in str(e) and "PA3BAT1OOEFE" in str(e)


def test_verify_account_kwarg_runs_the_check():
    with patch.object(AlpacaClient, "account",
                      return_value={"account_number": "WRONG"}):
        with pytest.raises(RuntimeError, match="ACCOUNT MISMATCH"):
            AlpacaClient(key="k", secret="s", verify_account="PA3BAT1OOEFE")
