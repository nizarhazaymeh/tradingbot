#!/usr/bin/env python3
"""Drive Alpaca's MCP server over stdio and record a real, reproducible session.

Why a script rather than a pasted chat log: this is verifiable. Anyone can re-run
it and get the same transcript, with real request/response pairs against the live
Alpaca API. It also doubles as proof the MCP integration actually works.

    python scripts/mcp_session.py            # run and print
    python scripts/mcp_session.py --save     # also write docs/mcp_session_transcript.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config


class MCPClient:
    """Minimal JSON-RPC 2.0 client speaking MCP over stdio."""

    def __init__(self, cmd, env_extra=None):
        env = {**os.environ, **(env_extra or {})}
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self._id = 0

    def _send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed the connection")
            try:
                res = json.loads(line)
            except json.JSONDecodeError:
                continue
            if res.get("id") == self._id:
                return res

    def initialize(self):
        r = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "options-alpha-agent", "version": "1.0"}})
        self._send("notifications/initialized", {}, notify=True)
        return r

    def list_tools(self):
        return self._send("tools/list", {})

    def call(self, name, args=None):
        return self._send("tools/call", {"name": name, "arguments": args or {}})

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def text_of(resp) -> str:
    """Pull the human-readable payload out of an MCP tool result."""
    r = resp.get("result") or {}
    if r.get("isError"):
        return "ERROR: " + json.dumps(r)[:400]
    parts = []
    for c in r.get("content") or []:
        if c.get("type") == "text":
            parts.append(c["text"])
    return "\n".join(parts) or json.dumps(r)[:400]


def shorten(s: str, n: int = 900) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + f"\n... [{len(s)-n} more chars]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()

    today = date.today()
    exp = today + timedelta(days=(4 - today.weekday()) % 7 or 7)   # next Friday

    log = []
    def rec(kind, title, body):
        log.append({"kind": kind, "title": title, "body": body})
        print(f"\n{'─'*74}\n{title}\n{'─'*74}\n{body}")

    print("starting Alpaca MCP server (uvx alpaca-mcp-server)...")
    c = MCPClient(["uvx", "alpaca-mcp-server"], {
        "ALPACA_API_KEY": config.API_KEY,
        "ALPACA_SECRET_KEY": config.SECRET_KEY,
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,assets,options-data,stock-data,news",
    })

    try:
        init = c.initialize()
        info = (init.get("result") or {}).get("serverInfo", {})
        rec("meta", "1. Handshake",
            f"server: {info.get('name')} v{info.get('version')}\n"
            f"protocol: {(init.get('result') or {}).get('protocolVersion')}")

        tools = (c.list_tools().get("result") or {}).get("tools", [])
        names = sorted(t["name"] for t in tools)
        opt = [n for n in names if "option" in n]
        rec("meta", "2. Tool discovery",
            f"{len(names)} tools exposed with ALPACA_TOOLSETS scoping.\n\n"
            f"options-related ({len(opt)}):\n  " + "\n  ".join(opt) +
            f"\n\nall tools:\n  " + "\n  ".join(names))

        # --- Q1: account state -------------------------------------------
        r = c.call("get_account_info", {})
        rec("q", "3. \"What is my account state and options approval level?\"",
            shorten(text_of(r), 700))

        # --- Q2: market status -------------------------------------------
        r = c.call("get_clock", {})
        rec("q", "4. \"Is the market open right now?\"", shorten(text_of(r), 400))

        # --- Q3: option chain with Greeks --------------------------------
        r = c.call("get_option_snapshot", {"symbol_or_symbols": "SPY"}) \
            if False else c.call("get_option_chain", {
                "underlying_symbol": "SPY",
                "expiration_date": exp.isoformat(),
                "feed": config.OPTIONS_FEED})
        rec("q", f"5. \"Show me the SPY option chain for {exp}, with Greeks.\"",
            shorten(text_of(r), 1100))

        # --- Q4: contracts ------------------------------------------------
        r = c.call("get_option_contracts", {
            "underlying_symbols": "SPY",
            "expiration_date": exp.isoformat(),
            "limit": 5})
        rec("q", f"6. \"Which SPY contracts exist for {exp}?\"",
            shorten(text_of(r), 700))

        # --- Q5: positions -------------------------------------------------
        r = c.call("get_all_positions", {})
        rec("q", "7. \"What positions am I holding?\"", shorten(text_of(r), 500))

        # --- Q6: the agent looking up its own API docs ---------------------
        r = c.call("search_alpaca_api_specs", {"query": "multi-leg option order mleg legs"}) \
            if any(t["name"] == "search_alpaca_api_specs" for t in tools) else None
        if r:
            rec("q", "8. \"How do I place a multi-leg option order?\" "
                     "(the agent reading its own API docs)",
                shorten(text_of(r), 900))

        # --- Q7: news -------------------------------------------------------
        r = c.call("get_news", {"symbols": "SPY", "limit": 3})
        rec("q", "9. \"Any recent news on SPY?\"", shorten(text_of(r), 700))

    finally:
        c.close()

    if a.save:
        out = Path(__file__).resolve().parent.parent / "docs" / "mcp_session_transcript.md"
        lines = [
            "# MCP session transcript",
            "",
            f"Recorded **{datetime.now(timezone.utc).isoformat(timespec='seconds')}** against the "
            f"DEV paper account `{config.ACCOUNT_NUMBER}`.",
            "",
            "Produced by `scripts/mcp_session.py`, which drives Alpaca's MCP server over stdio "
            "using JSON-RPC. Every request and response below is real and reproducible:",
            "",
            "```bash",
            "python scripts/mcp_session.py --save",
            "```",
            "",
            "The server is scoped with "
            "`ALPACA_TOOLSETS=account,trading,assets,options-data,stock-data,news` — a "
            "least-privilege control, since an MCP-connected model can place trades.",
            "",
        ]
        for e in log:
            lines += [f"## {e['title']}", "", "```", e["body"], "```", ""]
        lines += [
            "---",
            "",
            "## How the agent uses MCP",
            "",
            "MCP is the **research and oversight** surface, not the execution path:",
            "",
            "| Surface | Job |",
            "|---|---|",
            "| **Alpaca CLI** | the unattended cron loop that actually places orders |",
            "| **MCP server** | interactive inspection, human oversight, and the agent "
            "looking up its own API documentation when it hits an unfamiliar error |",
            "",
            "This split follows Alpaca's own guidance: the CLI is *\"built for long-running "
            "agent sessions, cron jobs and CI, where MCP is heavier than needed.\"*",
            "",
        ]
        out.write_text("\n".join(lines))
        print(f"\n\nwrote {out}")


if __name__ == "__main__":
    main()
