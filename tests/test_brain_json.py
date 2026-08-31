"""T6 — brain._extract_json must survive how reasoning models actually reply.

TODO.md: "brain.critic() occasionally fails to return JSON (GLM-5.2 is a
reasoning model and spends tokens thinking). It falls back to 'approve', which
is safe because the deterministic gates still run — but it means the critic is
not always doing its job."

Two distinct failure modes were confirmed by probing the old implementation:

  * output cut off by max_tokens mid-object returned None
  * the FIRST top-level object was returned, but reasoning models emit scratch
    work first and the answer last

The second is the dangerous one. A critic replying {"approve": false, ...} that
fails to parse becomes approve=True in the fallback, so a rejection is silently
discarded. Truncation inside "concerns":[...] hit exactly that path.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import _extract_json

VIEW_KEYS = ("direction", "confidence", "magnitude")
CRITIC_KEYS = ("approve", "concerns")


# ------------------------------------------------------------------ plain cases
def test_bare_object():
    assert _extract_json('{"direction":"up"}', VIEW_KEYS) == {"direction": "up"}


def test_strips_closed_think_block():
    assert _extract_json('<think>reasoning</think>{"direction":"up"}',
                         VIEW_KEYS) == {"direction": "up"}


def test_prose_before_json():
    assert _extract_json('Sure! Here is my view:\n{"direction":"down"}',
                         VIEW_KEYS) == {"direction": "down"}


def test_nested_object_inside_fence():
    """The fence regex is non-greedy, so nesting must fall through to brace matching."""
    out = _extract_json('```json\n{"a":{"b":1},"direction":"up"}\n```', VIEW_KEYS)
    assert out == {"a": {"b": 1}, "direction": "up"}


def test_no_json_returns_none():
    assert _extract_json("I cannot help with that.", VIEW_KEYS) is None
    assert _extract_json("", VIEW_KEYS) is None
    assert _extract_json(None, VIEW_KEYS) is None


# --------------------------------------------------- answer vs scratch work
def test_prefers_the_last_object_carrying_the_expected_keys():
    txt = '{"scratch":1}\nFinal answer:\n{"direction":"up"}'
    assert _extract_json(txt, VIEW_KEYS) == {"direction": "up"}


def test_scratch_object_does_not_shadow_the_critic_verdict():
    txt = '{"thinking":"weighing it up"}\n{"approve":false,"concerns":["too close"]}'
    out = _extract_json(txt, CRITIC_KEYS)
    assert out["approve"] is False
    assert out["concerns"] == ["too close"]


def test_falls_back_to_last_object_when_no_key_matches():
    assert _extract_json('{"a":1}\n{"b":2}', CRITIC_KEYS) == {"b": 2}


# ------------------------------------------------------------ truncation repair
def test_truncated_mid_object():
    out = _extract_json('{"direction":"up","magnitude":"small","confidence":0.6',
                        VIEW_KEYS)
    assert out == {"direction": "up", "magnitude": "small", "confidence": 0.6}


def test_truncated_mid_string():
    out = _extract_json('{"direction":"up","thesis":"the market looks', VIEW_KEYS)
    assert out["direction"] == "up"
    assert out["thesis"] == "the market looks"


def test_truncated_on_a_dangling_key():
    assert _extract_json('{"direction":"up","thes', VIEW_KEYS) == {"direction": "up"}


def test_truncated_inside_a_concerns_array_keeps_the_rejection():
    """The case that silently turned a rejection into an approval."""
    out = _extract_json('{"approve":false,"concerns":["short strike too close"',
                        CRITIC_KEYS)
    assert out["approve"] is False, "a rejection must not be lost to truncation"
    assert out["concerns"] == ["short strike too close"]


def test_truncated_mid_second_array_element():
    out = _extract_json('{"approve":false,"concerns":["too close","delta too',
                        CRITIC_KEYS)
    assert out["approve"] is False
    assert out["concerns"] == ["too close"]


def test_truncated_nested_object():
    out = _extract_json('{"approve":false,"detail":{"leg":"778C","sigma":0.83',
                        CRITIC_KEYS)
    assert out["approve"] is False
    assert out["detail"] == {"leg": "778C", "sigma": 0.83}


# ------------------------------------------------------------- string escaping
def test_braces_inside_a_string_are_not_structure():
    out = _extract_json('{"approve":true,"note":"looks {fine} to me"}', CRITIC_KEYS)
    assert out["note"] == "looks {fine} to me"


def test_unclosed_brace_inside_a_truncated_string():
    out = _extract_json('{"approve":false,"note":"bad {structure', CRITIC_KEYS)
    assert out["approve"] is False
    assert out["note"] == "bad {structure"


def test_escaped_quotes_survive():
    payload = json.dumps({"approve": True, "note": 'he said "no" firmly'})
    assert _extract_json(payload, CRITIC_KEYS)["note"] == 'he said "no" firmly'


def test_truncation_just_after_an_escaped_quote():
    payload = json.dumps({"approve": True, "note": 'he said "no" firmly'})
    out = _extract_json(payload[:payload.index("firmly")], CRITIC_KEYS)
    assert out["approve"] is True
    assert out["note"] == 'he said "no"'


def test_trailing_lone_backslash():
    out = _extract_json('{"approve":true,"note":"path C:\\\\', CRITIC_KEYS)
    assert out["approve"] is True


# ---------------------------------------------------------------- non-repairs
def test_unclosed_think_block_with_no_answer():
    """No JSON was emitted; inventing one would be worse than returning None."""
    assert _extract_json("<think>let me reason about this and then", VIEW_KEYS) is None


def test_garbage_is_not_repaired_into_an_object():
    assert _extract_json('{not json at all', VIEW_KEYS) is None
