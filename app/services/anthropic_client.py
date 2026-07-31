"""Thin wrapper around the official `anthropic` SDK.

Centralizes client construction (key from local secrets), a tiny connection
test, and a helper that builds the cached criteria system block used by both
the synchronous and batch screeners.
"""
from typing import Dict, List, Tuple

from .. import config


class NoKeyError(Exception):
    pass


def get_client():
    key = config.get_api_key()
    if not key:
        raise NoKeyError("No Anthropic API key set. Add one in Settings.")
    import anthropic  # imported lazily so the app boots without the package issue
    return anthropic.Anthropic(api_key=key)


def system_blocks(criteria_text: str) -> List[Dict]:
    """System prompt as content blocks. The (large, identical-every-call)
    criteria block is marked for prompt caching so it is billed at the cache
    rate after the first call in a run. Caching stacks with the batch discount.
    """
    from .screener import SCREENING_INSTRUCTIONS
    return [
        {"type": "text", "text": SCREENING_INSTRUCTIONS},
        {
            "type": "text",
            "text": criteria_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def test_connection(model: str | None = None) -> Tuple[bool, str]:
    """Make one tiny call to confirm the key + model work."""
    from .. import db
    model = model or db.get_setting("model", config.DEFAULT_MODEL)
    try:
        client = get_client()
    except NoKeyError as e:
        return False, str(e)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=8,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content).strip()
        return True, f"Model {model} responded: '{text or 'ok'}'."
    except Exception as e:  # noqa: BLE001 - surface a readable message to the UI
        return False, _readable_error(e)


def _readable_error(e: Exception) -> str:
    name = type(e).__name__
    msg = str(e)
    if "authentication" in name.lower() or "401" in msg:
        return "Authentication failed. Check the API key."
    if "not_found" in msg.lower() or "404" in msg or "model" in msg.lower() and "not" in msg.lower():
        return f"Model not available for this key: {msg}"
    if "rate" in name.lower() or "429" in msg:
        return "Rate limited. Try again shortly."
    return f"{name}: {msg}"
