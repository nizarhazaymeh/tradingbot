"""Notification channels for trading signals.

Currently supports Telegram (via the Bot API) and always logs to console.
No external dependencies — uses the standard library only.
"""
import logging
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from . import config

log = logging.getLogger("notifier")


def _send_telegram(text: str) -> bool:
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    ).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            ok = resp.status == 200
            if not ok:
                log.warning("Telegram returned status %s", resp.status)
            return ok
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False


def _smtp_send_starttls(msg) -> None:
    """Standard submission: port 587 + STARTTLS."""
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
        server.ehlo()
        server.starttls()
        if config.SMTP_USER and config.SMTP_PASSWORD:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.EMAIL_FROM, [config.EMAIL_TO], msg.as_string())


def _smtp_send_ssl(msg) -> None:
    """Fallback: implicit TLS on port 465 (works when 587/STARTTLS is filtered)."""
    with smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=20) as server:
        if config.SMTP_USER and config.SMTP_PASSWORD:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.EMAIL_FROM, [config.EMAIL_TO], msg.as_string())


def _send_email(subject: str, body: str) -> bool:
    if not (config.SMTP_HOST and config.EMAIL_FROM and config.EMAIL_TO):
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO

    # Try STARTTLS (587), then SSL (465); retry each once for transient timeouts.
    methods = [("STARTTLS:587", _smtp_send_starttls), ("SSL:465", _smtp_send_ssl)]
    last_err = None
    for name, send in methods:
        for attempt in (1, 2):
            try:
                send(msg)
                return True
            except Exception as e:
                last_err = f"{name} attempt {attempt}: {e}"
                log.warning("Email %s", last_err)
    log.error("Email send failed on all methods. Last error: %s", last_err)
    return False


def notify(text: str, subject: str = "Options Alpha Agent") -> None:
    """Send a notification through every configured channel.

    Always logs. Sends only when config.NOTIFY is on, so an inherited SMTP
    block in .env cannot start mailing on its own. Each channel is
    independently optional and fails silently if unconfigured — a notification
    must never be able to break a trading cycle.
    """
    log.info("NOTIFY: %s", text.replace("\n", " | "))
    if not config.NOTIFY:
        return
    try:
        _send_telegram(text)
    except Exception as e:                      # never propagate into the cycle
        log.warning("telegram notify failed: %s", e)
    try:
        _send_email(subject, text)
    except Exception as e:
        log.warning("email notify failed: %s", e)
