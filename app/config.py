"""Paths, model list, and local secret handling.

The Anthropic API key is stored in `secrets.local.json`, chmod 0600, alongside
the database. It is never committed and never returned to the browser in full
(see settings router masking). This key is separate from any Claude Code /
Claude.ai login.

Running from a source checkout, data lives in ./data. Running from an
installed .app or .exe, it lives in the per-user application data directory,
because an installed bundle sits in a read-only location and is replaced
wholesale on upgrade.
"""
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
FROZEN = getattr(sys, "frozen", False)
APP_NAME = "AI Systematic Review Screening Assistant"


def _user_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


# SCREENING_DATA_DIR wins, then the frozen-app location, then the checkout.
_dir_env = os.environ.get("SCREENING_DATA_DIR")
if _dir_env:
    DATA_DIR = Path(_dir_env)
elif FROZEN:
    DATA_DIR = _user_data_dir()
else:
    DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# DB location. Override with SCREENING_DB_PATH (used for tests / unusual
# filesystems that don't support SQLite locking).
_db_env = os.environ.get("SCREENING_DB_PATH")
DB_PATH = Path(_db_env) if _db_env else DATA_DIR / "screening.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SECRETS_PATH = DATA_DIR / "secrets.local.json"

# A source checkout previously kept secrets at the repo root; keep reading that
# so an existing dev setup does not silently lose its key.
_legacy_secrets = ROOT_DIR / "secrets.local.json"
if not FROZEN and _legacy_secrets.exists() and not SECRETS_PATH.exists():
    SECRETS_PATH = _legacy_secrets

# Model dropdown. The API value is what gets sent to Anthropic; the label is
# what the user sees. If Anthropic ever rejects an id, edit it here.
MODELS = [
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (recommended)"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (cheapest)"},
    {"id": "claude-opus-4-8", "label": "Claude Opus 4.8 (most capable)"},
]
DEFAULT_MODEL = "claude-sonnet-4-6"
VALID_MODEL_IDS = {m["id"] for m in MODELS}


def _read_secrets() -> dict:
    if SECRETS_PATH.exists():
        try:
            return json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_secrets(data: dict) -> None:
    SECRETS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except Exception:
        pass  # Windows may not support chmod; file is still gitignored


def get_api_key() -> str | None:
    key = _read_secrets().get("anthropic_api_key")
    if key:
        return key
    return os.environ.get("ANTHROPIC_API_KEY")  # optional fallback


def set_api_key(key: str) -> None:
    data = _read_secrets()
    data["anthropic_api_key"] = (key or "").strip()
    _write_secrets(data)


def clear_api_key() -> None:
    data = _read_secrets()
    data.pop("anthropic_api_key", None)
    _write_secrets(data)


def mask_key(key: str | None) -> str:
    if not key:
        return ""
    k = key.strip()
    if len(k) <= 10:
        return "•" * len(k)
    return f"{k[:7]}…{k[-4:]}"
