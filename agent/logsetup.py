"""One place that decides where log output goes.

run.py previously called logging.basicConfig() with a console handler only, so
config.LOG_DIR was created and never written to. Everything the agent did lived
in terminal scrollback and was gone once it scrolled — including the reason for a
halt, which is the one line you want after an unattended session.

The console stays terse (time + level + message). The file gets the full record:
date, logger name and line number, so a warning can be traced without guessing
which module emitted it.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

from . import config

CONSOLE_FMT = "%(asctime)s %(levelname)-7s %(message)s"
CONSOLE_DATE = "%H:%M:%S"
FILE_FMT = "%(asctime)s %(levelname)-7s %(name)s:%(lineno)d  %(message)s"
FILE_DATE = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup(*, console: bool = True, level: str = None, path: str = None) -> str:
    """Attach a console and a rotating file handler to the root logger.

    Idempotent: calling it twice does not double every line, which matters
    because scripts import each other.

    Returns the log file path, or "" if the file handler could not be attached —
    a read-only or full disk must not stop the agent trading, so failure here is
    reported and swallowed.
    """
    global _configured
    if _configured:
        return config.LOG_FILE

    lvl = getattr(logging, (level or config.LOG_LEVEL), logging.INFO)
    root = logging.getLogger()
    root.setLevel(lvl)
    for h in list(root.handlers):          # drop anything basicConfig() installed
        root.removeHandler(h)

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(lvl)
        ch.setFormatter(logging.Formatter(CONSOLE_FMT, CONSOLE_DATE))
        root.addHandler(ch)

    target = path or config.LOG_FILE
    written = ""
    try:
        fh = logging.handlers.RotatingFileHandler(
            target, maxBytes=config.LOG_FILE_MAX_MB * 1024 * 1024,
            backupCount=config.LOG_FILE_KEEP, encoding="utf-8")
        fh.setLevel(lvl)
        fh.setFormatter(logging.Formatter(FILE_FMT, FILE_DATE))
        root.addHandler(fh)
        written = target
    except OSError as e:
        logging.getLogger(__name__).warning(
            "file logging disabled (%s): %s", target, e)

    # urllib/http chatter at DEBUG would bury the trading decisions
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _configured = True
    return written


def banner(command: str, *, dry_run: bool) -> None:
    """A line at the top of every run, so a log file says what produced it."""
    log = logging.getLogger("agent")
    log.info("─" * 78)
    log.info("run: %s | account=%s (%s) | dry_run=%s | universe=%s",
             command, config.ACCOUNT, config.ACCOUNT_NUMBER or "?", dry_run,
             ",".join(config.UNIVERSE))
