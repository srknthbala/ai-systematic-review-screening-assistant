"""Settings: API key (local, masked), model selection, connection test."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config, db
from ..services import anthropic_client

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def get_settings() -> dict:
    key = config.get_api_key()
    return {
        "model": db.get_setting("model", config.DEFAULT_MODEL),
        "models": config.MODELS,
        "api_key_set": bool(key),
        "api_key_masked": config.mask_key(key),
    }


class ModelIn(BaseModel):
    model: str


@router.put("/settings")
def set_model(body: ModelIn) -> dict:
    if body.model not in config.VALID_MODEL_IDS:
        raise HTTPException(400, "Unknown model id.")
    db.set_setting("model", body.model)
    return {"ok": True, "model": body.model}


class KeyIn(BaseModel):
    api_key: str


@router.post("/settings/key")
def save_key(body: KeyIn) -> dict:
    if not body.api_key.strip():
        raise HTTPException(400, "Empty key.")
    config.set_api_key(body.api_key)
    return {"ok": True, "api_key_masked": config.mask_key(config.get_api_key())}


@router.delete("/settings/key")
def remove_key() -> dict:
    config.clear_api_key()
    return {"ok": True}


class TestIn(BaseModel):
    model: Optional[str] = None


@router.post("/settings/test")
def test(body: TestIn) -> dict:
    ok, message = anthropic_client.test_connection(body.model)
    return {"ok": ok, "message": message, "model": body.model or db.get_setting("model", config.DEFAULT_MODEL)}
