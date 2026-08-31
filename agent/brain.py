"""LLM layer (Featherless AI, OpenAI-compatible).

Deliberately narrow. The model does exactly two things:

  1. view()   — read the market context and return a *directional view*
  2. critic() — sanity-check a proposal for structural coherence

It never picks strikes, never sizes a position, never builds an order payload.
Everything that touches money is deterministic code in strategy.py / risk.py.

Every call is JSON-only, schema-validated, and falls back to a safe default on
any error — the agent must keep trading if the LLM is unavailable.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from . import config
from .regime import Regime
from .strategy import View, NEUTRAL

log = logging.getLogger(__name__)

_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=config.FEATHERLESS_BASE_URL,
                         api_key=config.FEATHERLESS_API_KEY,
                         timeout=config.LLM_TIMEOUT)
    return _client


def _scan(frag: str):
    """Walk the fragment tracking string state and the bracket stack.

    Returns (stack, in_string). Brackets inside string literals must not count,
    or a thesis containing "{" corrupts the repair.
    """
    stack, in_str, esc = [], False, False
    for ch in frag:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack and stack[-1] == ("{" if ch == "}" else "["):
                stack.pop()
    return stack, in_str


def _repair_truncated(frag: str) -> Optional[dict]:
    """Close an object the model ran out of tokens mid-way through.

    This is T6's actual failure mode: GLM-5.2 is a reasoning model, it spends
    output tokens thinking, and the JSON is cut off by max_tokens. The fragment
    is usually valid right up to the cut, so closing the open string, arrays and
    objects recovers the fields it did manage to emit. Fields never reached are
    absent, and both callers already treat absent keys as defaults.

    Closing arrays matters as much as objects: a critic cut off inside
    "concerns":[...] used to yield nothing, and critic() then falls back to
    approve — silently discarding a rejection.
    """
    frag = frag.rstrip()
    if not frag.startswith("{"):
        return None

    stack, in_str = _scan(frag)
    if in_str:
        frag += '"'
        stack, _ = _scan(frag)
    if not stack:
        return None

    # drop a dangling key with no value, then any trailing comma or colon
    frag = re.sub(r',\s*"[^"]*"\s*:?\s*$', "", frag)
    frag = frag.rstrip().rstrip(",:")
    stack, in_str = _scan(frag)
    if in_str:
        frag += '"'
        stack, _ = _scan(frag)

    closing = "".join("}" if ch == "{" else "]" for ch in reversed(stack))
    try:
        return json.loads(frag + closing)
    except json.JSONDecodeError:
        return None


def _objects(text: str) -> list:
    """Every balanced top-level {...} in order, plus a repaired trailing fragment."""
    found, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    found.append(json.loads(text[start:i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    # unbalanced tail: the model was cut off mid-object
    if depth > 0 and start is not None:
        repaired = _repair_truncated(text[start:])
        if repaired is not None:
            found.append(repaired)
    return found


def _extract_json(text: str, require_keys=None) -> Optional[dict]:
    """Pull the model's answer out of prose, fences and thinking blocks.

    Prefers the LAST object carrying any of require_keys. Reasoning models emit
    scratch work first and the answer last, so taking the first object returned
    the scratch pad — for critic() that meant a garbage verdict silently becoming
    "approve".
    """
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)

    candidates = []
    # a fenced block is the strongest signal, so try it first
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        candidates.extend(_objects(m.group(1)))
    candidates.extend(_objects(text))
    if not candidates:
        return None

    if require_keys:
        keyed = [c for c in candidates if any(k in c for k in require_keys)]
        if keyed:
            return keyed[-1]
    return candidates[-1]


def _ask(system: str, user: str, *, max_tokens: int = None,
         temperature: float = 0.2, require_keys=None) -> Optional[dict]:
    if not config.FEATHERLESS_API_KEY:
        log.warning("no FEATHERLESS_API_KEY — skipping LLM")
        return None
    try:
        r = client().chat.completions.create(
            model=config.FEATHERLESS_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
            temperature=temperature,
        )
        out = _extract_json(r.choices[0].message.content or "",
                            require_keys=require_keys)
        if out is None:
            log.warning("LLM returned no parsable JSON")
        return out
    except Exception as e:                       # network, rate limit, cold model
        log.warning("LLM call failed: %s: %s", type(e).__name__, e)
        return None


# ---------------------------------------------------------------------- view
VIEW_SYSTEM = """You are a disciplined options strategist. You output ONLY a JSON object.

Your job is narrow: given market context, state a short-horizon directional view.
You do NOT choose strikes, expirations, position sizes, or order types — deterministic
code does that. You only judge direction, magnitude and conviction.

Return EXACTLY this shape and nothing else:
{"direction":"up|down|neutral","magnitude":"small|medium|large",
 "horizon_days":<1-10 integer>,"confidence":<0.0-1.0>,"thesis":"<=200 chars"}

Rules:
- "neutral" is a legitimate and often correct answer. Prefer it when signals conflict.
- confidence below 0.55 means "no strong opinion" and will be treated as neutral.
- Base the view on the supplied data only. Do not invent news or price levels.
- "structure" is swing structure (higher highs/lows). If it disagrees with
  trend_z, that is a genuine conflict — prefer neutral.
- "resistance_sigma"/"support_sigma" are distances to the nearest supply/demand
  zone in units of the 1-sigma expected move. Under ~1.0 means price could
  reach it inside the option's life. "touches" above ~3 means a worked, weak zone.
- Be conservative: capital preservation outranks being interesting."""


def view(reg: Regime, *, news: List[dict] = None, extra: Dict[str, Any] = None) -> View:
    """Ask the model for a directional view. Falls back to NEUTRAL on any failure."""
    headlines = [n.get("headline", "")[:140] for n in (news or [])[:8]]
    ctx = {
        "underlying": reg.underlying,
        "spot": round(reg.spot, 2),
        "regime": reg.name,
        "implied_vol": round(reg.iv, 4),
        "iv_rank": reg.iv_rank,
        "realized_vol": round(reg.detail.get("realized_vol") or 0, 4),
        "trend_z": round(reg.trend_z, 2),
        "trend_direction": reg.trend_dir,
        "days_to_expiry": reg.dte,
        "expected_move_1sigma": round(reg.expected_move, 2),
        "expected_move_pct": round(reg.expected_move / reg.spot, 4) if reg.spot else None,
        "recent_headlines": headlines,
    }
    # Swing structure and the nearest levels. Supplied as data only — the model
    # still returns a view, and deterministic code still picks every strike.
    if extra:
        ctx.update(extra)

    data = _ask(VIEW_SYSTEM, json.dumps(ctx, separators=(",", ":")),
                require_keys=("direction", "confidence", "magnitude"))
    if not data:
        return View(source="fallback-neutral", thesis="LLM unavailable; defaulting to neutral")

    direction = str(data.get("direction", "neutral")).lower()
    if direction not in ("up", "down", "neutral"):
        direction = "neutral"
    magnitude = str(data.get("magnitude", "small")).lower()
    if magnitude not in ("small", "medium", "large"):
        magnitude = "small"
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    try:
        horizon = max(1, min(10, int(data.get("horizon_days", reg.dte))))
    except (TypeError, ValueError):
        horizon = reg.dte

    # low conviction is treated as no opinion
    if confidence < 0.55:
        direction = "neutral"

    return View(direction=direction, magnitude=magnitude, horizon_days=horizon,
                confidence=confidence, thesis=str(data.get("thesis", ""))[:200],
                source=config.FEATHERLESS_MODEL)


# -------------------------------------------------------------------- critic
CRITIC_SYSTEM = """You are a risk critic reviewing a proposed options trade.

You check STRUCTURAL COHERENCE ONLY. You do NOT predict whether the trade will make
money, and you do NOT re-do the risk maths — deterministic gates already did that.

Check only:
- does the structure match the stated market view? (neutral view -> neutral structure)
- is the thesis internally consistent with the data given?
- is anything obviously contradictory or nonsensical?

Return EXACTLY:
{"approve":true|false,"concerns":["..."],"note":"<=160 chars"}

Approve unless something is clearly wrong. Do not manufacture objections."""


def critic(spread_summary: dict, reg: Regime, v: View) -> Dict[str, Any]:
    payload = {
        "proposal": spread_summary,
        "regime": {"name": reg.name, "reason": reg.reason,
                   "iv": round(reg.iv, 4), "trend_z": round(reg.trend_z, 2),
                   "expected_move": round(reg.expected_move, 2)},
        "view": {"direction": v.direction, "confidence": v.confidence, "thesis": v.thesis},
    }
    data = _ask(CRITIC_SYSTEM, json.dumps(payload, separators=(",", ":")),
                max_tokens=config.LLM_MAX_TOKENS,
                require_keys=("approve", "concerns"))
    if not data:
        # LLM unavailable -> do not block. Deterministic gates are the real guard.
        return {"approve": True, "concerns": [], "note": "critic unavailable — gates still applied",
                "source": "fallback"}
    return {"approve": bool(data.get("approve", True)),
            "concerns": [str(c)[:160] for c in (data.get("concerns") or [])][:5],
            "note": str(data.get("note", ""))[:160],
            "source": config.FEATHERLESS_MODEL}


def health() -> dict:
    """Cheap probe so the cycle can report LLM availability."""
    d = _ask("Return only JSON.", '{"ping":1} -> reply {"ok":true}', max_tokens=200)
    return {"ok": bool(d and d.get("ok") is not None), "model": config.FEATHERLESS_MODEL}
