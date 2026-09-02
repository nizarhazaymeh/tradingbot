"""Spot crypto: the signal, and the two bounds that replace a spread's long wing.

The options agent is safe because arithmetic makes it safe — a vertical spread
cannot lose more than its width, whatever happens overnight, because the long leg
is there. Spot has no long leg. A stop is a PLAN, and crypto gaps through plans.

So sizing is bounded twice, and the second bound is the one carrying the README's
claim that the account cannot blow up:

    by the stop      qty = risk_dollars / (entry - stop)     if the stop fills
    by the notional  qty <= MAX_NOTIONAL_PCT * equity / entry  if it does not

These tests exist mostly to pin the notional bound. It is the only thing standing
between a gap and the account.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, crypto as CR, levels as L, risk as RK

EQUITY = 100_000.0


def sig(entry=100.0, stop=90.0, target=120.0, symbol="BTC/USD"):
    return CR.Signal(symbol=symbol, side=CR.LONG, entry=entry, stop=stop,
                     target=target, level=95.0, atr=5.0, reason="test")


# ------------------------------------------------------------------- sizing
def test_size_is_bounded_by_the_stop_when_the_stop_is_wide():
    """A wide stop is the risk-limited case: $10 of risk per unit."""
    qty, risk, notional = CR.size(sig(entry=100, stop=90), EQUITY)
    assert abs(risk - EQUITY * config.CRYPTO_RISK_PER_TRADE_PCT) < 1.0
    assert notional <= EQUITY * config.CRYPTO_MAX_NOTIONAL_PCT + 1


def test_size_is_bounded_by_notional_when_the_stop_is_tight():
    """A very tight stop would otherwise buy an enormous position.

    This is the case that matters: risk-based sizing alone says "the stop is only
    1% away, so buy 40% of the account". A gap through that stop is catastrophic,
    and the notional cap is what refuses it.
    """
    qty, risk, notional = CR.size(sig(entry=100, stop=99), EQUITY)
    assert notional <= EQUITY * config.CRYPTO_MAX_NOTIONAL_PCT + 1e-6
    assert risk < EQUITY * config.CRYPTO_RISK_PER_TRADE_PCT, (
        "the notional bound must have bound first, leaving risk UNDER the budget")


def test_the_notional_cap_bounds_a_total_loss():
    """The honest worst case for spot: the position goes to zero."""
    qty, risk, notional = CR.size(sig(entry=100, stop=99), EQUITY)
    assert qty * 100.0 <= EQUITY * config.CRYPTO_MAX_NOTIONAL_PCT + 1e-6


def test_a_nonsensical_signal_sizes_to_zero():
    for bad in (sig(entry=100, stop=100), sig(entry=100, stop=110), sig(entry=0, stop=0)):
        assert CR.size(bad, EQUITY)[0] == 0.0
    assert CR.size(sig(), 0)[0] == 0.0


# ------------------------------------------------------------------ signals
def mk(rows):
    return [L.Bar(i, c, h, l, 1000.0) for i, (h, l, c) in enumerate(rows)]


def flat_then_break():
    """Range with one swing high at 110, a break above it, then a held retest."""
    r = [(105, 100, 102)] * 40 + [(110, 104, 108)] + [(105, 100, 102)] * 20
    r += [(112, 106, 111), (113, 110.5, 112), (112, 109, 110.5)]
    return r + [(113, 110, 112)] * 3


def test_a_confirmed_bullish_break_produces_a_long_signal():
    s = CR.signal("BTC/USD", mk(flat_then_break()))
    assert s is not None and s.side == CR.LONG
    assert s.stop < s.level, "the stop must sit UNDER the level, which is the thesis"
    assert s.target > s.entry


def test_no_break_means_no_signal():
    assert CR.signal("BTC/USD", mk([(105, 100, 102)] * 80)) is None


def test_too_little_history_is_not_an_error():
    assert CR.signal("BTC/USD", mk([(105, 100, 102)] * 20)) is None
    assert CR.signal("BTC/USD", []) is None


def test_a_stale_break_is_ignored():
    """Structure confirmed forty bars ago has been overtaken by what came after."""
    rows = flat_then_break() + [(113, 110, 112)] * (config.CRYPTO_MAX_SIGNAL_AGE + 10)
    assert CR.signal("BTC/USD", mk(rows)) is None


def test_short_signals_are_never_produced():
    """Alpaca does not support shorting spot, so a bearish break is an exit only."""
    rows = [(105, 100, 102)] * 40 + [(104, 95, 96)] + [(105, 100, 102)] * 20
    rows += [(99, 88, 89), (95, 88, 90), (94, 90, 92)]
    s = CR.signal("BTC/USD", mk(rows))
    assert s is None or s.side == CR.LONG


# -------------------------------------------------------------------- exits
def pos(entry=100.0, stop=90.0, target=120.0, qty=1.0, opened=None):
    return {"entry": entry, "stop": stop, "target": target, "qty": qty,
            "opened_at": opened or datetime.now(timezone.utc).isoformat()}


def test_the_stop_closes_the_position():
    assert CR.evaluate_exit(pos(), 89.0)[0] == CR.CLOSE
    assert CR.evaluate_exit(pos(), 90.0)[0] == CR.CLOSE


def test_the_target_closes_the_position():
    assert CR.evaluate_exit(pos(), 121.0)[0] == CR.CLOSE


def test_the_stop_is_checked_before_the_target():
    """A price satisfying both is resolved as the LOSS.

    On daily bars a candle through both is genuinely ambiguous, and resolving it
    as the target would flatter every backtest built on this function.
    """
    action, reason = CR.evaluate_exit(pos(stop=120.0, target=120.0), 120.0)
    assert action == CR.CLOSE and "stop" in reason


def test_between_the_levels_it_holds():
    assert CR.evaluate_exit(pos(), 105.0)[0] == CR.HOLD


def test_the_time_stop_fires():
    old = (datetime.now(timezone.utc)
           - timedelta(hours=config.CRYPTO_TIME_STOP_HOURS + 1)).isoformat()
    action, reason = CR.evaluate_exit(pos(opened=old), 105.0)
    assert action == CR.CLOSE and "time stop" in reason


def test_a_malformed_open_timestamp_does_not_crash_the_exit():
    assert CR.evaluate_exit(pos(opened="not-a-date"), 105.0)[0] == CR.HOLD


# ------------------------------------------------------------------- gates
def gate(**kw):
    base = dict(equity=EQUITY, qty=1.0, risk=100.0, notional=1000.0,
                open_positions=0, open_risk=0.0, symbol="BTC/USD",
                held_symbols=set())
    base.update(kw)
    return RK.crypto_gates(**base)


def test_a_reasonable_position_passes():
    assert gate()


def test_notional_over_the_cap_is_refused():
    g = gate(notional=EQUITY * config.CRYPTO_MAX_NOTIONAL_PCT * 2)
    assert not g and g.gate == "g_crypto_notional"


def test_risk_over_the_per_trade_budget_is_refused():
    g = gate(risk=EQUITY * config.CRYPTO_RISK_PER_TRADE_PCT * 2)
    assert not g and g.gate == "g_crypto_risk_per_trade"


def test_summed_heat_is_capped():
    g = gate(open_risk=EQUITY * config.CRYPTO_MAX_HEAT_PCT)
    assert not g and g.gate == "g_crypto_heat"


def test_a_duplicate_symbol_is_refused():
    g = gate(held_symbols={"BTC/USD"})
    assert not g and g.gate == "g_crypto_duplicate"


def test_the_position_count_is_capped():
    g = gate(open_positions=config.CRYPTO_MAX_POSITIONS)
    assert not g and g.gate == "g_crypto_max_positions"


def test_a_zero_size_is_refused():
    g = gate(qty=0.0)
    assert not g and g.gate == "g_crypto_size"


# ------------------------------------------------- the 24/7 day boundary
def test_the_crypto_day_starts_at_utc_midnight():
    d = CR.crypto_day_start(datetime(2026, 9, 1, 17, 43, tzinfo=timezone.utc))
    assert (d.hour, d.minute, d.second) == (0, 0, 0)
    assert d.date() == datetime(2026, 9, 1, tzinfo=timezone.utc).date()


def test_the_daily_breaker_fires_against_the_utc_midnight_mark():
    limit = config.DAILY_DRAWDOWN_LIMIT
    assert RK.crypto_day_drawdown(100_000 * (1 - limit - 0.001), 100_000).gate == (
        "g_crypto_day_drawdown")
    assert RK.crypto_day_drawdown(100_000 * (1 - limit + 0.005), 100_000)


def test_no_baseline_means_no_opinion():
    """A fresh install has no equity curve yet; that must not halt it."""
    assert RK.crypto_day_drawdown(100_000, None)
    assert RK.crypto_day_drawdown(100_000, 0)


def test_crypto_is_off_in_the_shipped_default():
    """The guardrail is that nobody enables spot crypto by ACCIDENT.

    docs/BACKTEST.md Part 8 measured PF 1.14 and mean R -0.123 over 69
    walk-forward trades, and it lost to buy-and-hold on BTC — that is not an
    edge, so the shipped default must stay off.

    This asserts the DEFAULT rather than the runtime value. An operator who
    edits .env has made a deliberate choice and the test should not fail on it;
    a contributor who ships a new default that is on should. Enabled locally on
    2 Sep 2026 by operator decision on the paper account, which is why the
    distinction now matters.
    """
    import re
    from pathlib import Path as _P

    root = _P(__file__).resolve().parent.parent

    # the code fallback when .env says nothing
    src = (root / "agent" / "config.py").read_text()
    m = re.search(r'CRYPTO_ENABLED\s*=\s*_b\(\s*"CRYPTO_ENABLED"\s*,\s*(\w+)', src)
    assert m, "CRYPTO_ENABLED default not found in config.py"
    assert m.group(1) == "False", (
        f"the code default is {m.group(1)}; spot crypto must not be on unless "
        "someone turns it on")

    # and the example env a new clone copies
    ex = root / ".env.example"
    if ex.exists():
        for line in ex.read_text().splitlines():
            if line.startswith("CRYPTO_ENABLED="):
                assert line.split("=", 1)[1].strip().lower() in ("", "false", "0", "no"), (
                    f".env.example ships crypto enabled: {line}")
