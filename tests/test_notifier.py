"""A notification must never be able to break a trading cycle.

notifier.py was inherited and unwired: agent/config.py did not define the
variables it read, so importing it would have raised AttributeError. Now that it
is wired into cycle.py (halts and real submissions), two properties matter more
than delivery:

  1. It is off unless explicitly enabled. The SMTP block in .env was inherited
     from an earlier project, so wiring the notifier in must not start mailing on
     its own.
  2. A channel failing must not propagate. An unreachable SMTP host during a live
     session must cost a log line, not the cycle.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import config, notifier


def test_config_defines_everything_notifier_reads():
    """The original bug: notifier read config attributes that did not exist."""
    for name in ("NOTIFY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST",
                 "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM", "EMAIL_TO"):
        assert hasattr(config, name), f"config.{name} is missing"


def test_smtp_port_is_an_int():
    """smtplib.SMTP() requires an int; a string fails at connect time."""
    assert isinstance(config.SMTP_PORT, int)


def test_notify_is_off_by_default(monkeypatch):
    sent = []
    monkeypatch.setattr(notifier, "_send_telegram", lambda t: sent.append("tg"))
    monkeypatch.setattr(notifier, "_send_email", lambda s, t: sent.append("mail"))
    monkeypatch.setattr(config, "NOTIFY", False)
    notifier.notify("hello")
    assert sent == [], "notify() sent while NOTIFY was off"


def test_notify_sends_when_enabled(monkeypatch):
    sent = []
    monkeypatch.setattr(notifier, "_send_telegram", lambda t: sent.append("tg"))
    monkeypatch.setattr(notifier, "_send_email", lambda s, t: sent.append("mail"))
    monkeypatch.setattr(config, "NOTIFY", True)
    notifier.notify("hello")
    assert sorted(sent) == ["mail", "tg"]


def test_a_failing_channel_does_not_propagate(monkeypatch):
    """The property that protects the cycle."""
    def boom(*a, **kw):
        raise RuntimeError("smtp exploded")
    monkeypatch.setattr(notifier, "_send_telegram", boom)
    monkeypatch.setattr(notifier, "_send_email", boom)
    monkeypatch.setattr(config, "NOTIFY", True)
    notifier.notify("hello")          # must not raise


def test_telegram_failure_does_not_stop_email(monkeypatch):
    sent = []
    def boom(*a, **kw):
        raise RuntimeError("telegram down")
    monkeypatch.setattr(notifier, "_send_telegram", boom)
    monkeypatch.setattr(notifier, "_send_email", lambda s, t: sent.append("mail"))
    monkeypatch.setattr(config, "NOTIFY", True)
    notifier.notify("hello")
    assert sent == ["mail"], "email skipped because telegram failed"
