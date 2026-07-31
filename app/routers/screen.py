"""Screening: Mode A (synchronous test run) and Mode B (Message Batches)."""
import json
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import config, db
from ..services import anthropic_client, batches, screener
from ..services.anthropic_client import NoKeyError, get_client, system_blocks
from .criteria import FIELDS as CRIT_FIELDS

router = APIRouter(prefix="/api", tags=["screen"])

# in-memory progress for synchronous test runs (single-process app)
TEST_RUNS: dict = {}


def _pid(project_id: Optional[int]) -> int:
    if project_id:
        return project_id
    cur = db.get_setting("current_project_id")
    if not cur:
        raise HTTPException(400, "No project selected.")
    return int(cur)


def _load_criteria(conn, pid):
    row = conn.execute("SELECT * FROM criteria WHERE project_id=?", (pid,)).fetchone()
    crit = {f: (row[f] if row else "") for f in CRIT_FIELDS}
    try:
        reasons = json.loads(row["exclusion_reasons"]) if row and row["exclusion_reasons"] else []
    except Exception:
        reasons = []
    return crit, reasons


def _unscreened(conn, pid, limit=None, randomize=False):
    sql = ("SELECT * FROM records r WHERE r.project_id=? AND r.active=1 "
           "AND NOT EXISTS (SELECT 1 FROM screening_results s "
           "WHERE s.project_id=r.project_id AND s.record_id=r.id)")
    if randomize:
        sql += " ORDER BY RANDOM()"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (pid,)).fetchall()


def _active_batch(conn, pid):
    return conn.execute(
        "SELECT * FROM batch_jobs WHERE project_id=? AND status='in_progress' "
        "ORDER BY id DESC LIMIT 1", (pid,)).fetchone()


# ----------------------------- status -----------------------------
@router.get("/screen/status")
def status(project_id: Optional[int] = Query(None)) -> dict:
    pid = _pid(project_id)
    with db.get_conn() as conn:
        crit, reasons = _load_criteria(conn, pid)
        total_unique = conn.execute(
            "SELECT COUNT(*) c FROM records WHERE project_id=? AND active=1", (pid,)).fetchone()["c"]
        unscreened = conn.execute(
            "SELECT COUNT(*) c FROM records r WHERE r.project_id=? AND r.active=1 "
            "AND NOT EXISTS (SELECT 1 FROM screening_results s WHERE s.project_id=r.project_id AND s.record_id=r.id)",
            (pid,)).fetchone()["c"]
        ab = _active_batch(conn, pid)
    has_criteria = any((crit.get(f) or "").strip() for f in CRIT_FIELDS)
    run = TEST_RUNS.get(pid)
    return {
        "model": db.get_setting("model", config.DEFAULT_MODEL),
        "api_key_set": bool(config.get_api_key()),
        "has_criteria": has_criteria,
        "reason_list": reasons,
        "total_unique": total_unique,
        "unscreened": unscreened,
        "active_batch": dict(ab) if ab else None,
        "test_running": bool(run and run.get("running")),
    }


# ----------------------------- Mode A: test -----------------------------
class TestIn(BaseModel):
    project_id: int
    sample_size: int = 25


def _run_test(pid: int, model: str, system, records, reason_list):
    state = TEST_RUNS[pid]
    conn = db.get_conn()
    try:
        client = get_client()
        for rec in records:
            if state["cancel"]:
                break
            try:
                res = screener.screen_one(client, model, system, dict(rec), reason_list)
            except Exception as e:  # noqa: BLE001 - API/network error: stop & report
                state["error"] = anthropic_client._readable_error(e)
                break
            screener.save_result(conn, pid, rec["id"], res, model, "test")
            conn.commit()
            state["done"] += 1
    except NoKeyError as e:
        state["error"] = str(e)
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)
    finally:
        conn.close()
        state["running"] = False


@router.post("/screen/test")
def start_test(body: TestIn) -> dict:
    pid = body.project_id
    if not config.get_api_key():
        raise HTTPException(400, "No API key set (Settings).")
    existing = TEST_RUNS.get(pid)
    if existing and existing.get("running"):
        raise HTTPException(400, "A test run is already in progress.")
    with db.get_conn() as conn:
        crit, reasons = _load_criteria(conn, pid)
        if not any((crit.get(f) or "").strip() for f in CRIT_FIELDS):
            raise HTTPException(400, "Criteria are empty. Fill them in first.")
        records = _unscreened(conn, pid, limit=max(1, body.sample_size), randomize=True)
    if not records:
        raise HTTPException(400, "No unscreened records to test.")
    model = db.get_setting("model", config.DEFAULT_MODEL)
    criteria_text = screener.build_criteria_text(crit, reasons)
    system = system_blocks(criteria_text)
    TEST_RUNS[pid] = {
        "running": True, "total": len(records), "done": 0,
        "error": None, "cancel": False,
        "record_ids": [r["id"] for r in records],
    }
    threading.Thread(target=_run_test, args=(pid, model, system, records, reasons), daemon=True).start()
    return {"ok": True, "total": len(records)}


@router.get("/screen/test/progress")
def test_progress(project_id: Optional[int] = Query(None)) -> dict:
    pid = _pid(project_id)
    state = TEST_RUNS.get(pid)
    if not state:
        return {"running": False, "done": 0, "total": 0, "error": None, "results": []}
    ids = state["record_ids"]
    results = []
    if ids:
        placeholders = ",".join("?" * len(ids))
        with db.get_conn() as conn:
            rows = conn.execute(
                f"SELECT r.title, s.decision, s.confidence, s.reason, s.exclusion_reason_category, s.tags "
                f"FROM screening_results s JOIN records r ON r.id=s.record_id "
                f"WHERE s.project_id=? AND s.record_id IN ({placeholders}) ORDER BY s.id",
                (pid, *ids)).fetchall()
        for r in rows:
            results.append({
                "title": r["title"], "decision": r["decision"], "confidence": r["confidence"],
                "reason": r["reason"], "exclusion_reason_category": r["exclusion_reason_category"],
                "tags": json.loads(r["tags"] or "[]"),
            })
    return {"running": state["running"], "done": state["done"], "total": state["total"],
            "error": state["error"], "results": results}


@router.post("/screen/test/cancel")
def cancel_test(project_id: Optional[int] = Query(None)) -> dict:
    pid = _pid(project_id)
    if pid in TEST_RUNS:
        TEST_RUNS[pid]["cancel"] = True
    return {"ok": True}


# ----------------------------- Mode B: batch -----------------------------
class BatchIn(BaseModel):
    project_id: int


@router.post("/screen/batch")
def submit_batch(body: BatchIn) -> dict:
    pid = body.project_id
    if not config.get_api_key():
        raise HTTPException(400, "No API key set (Settings).")
    with db.get_conn() as conn:
        if _active_batch(conn, pid):
            raise HTTPException(400, "A batch is already running for this project.")
        crit, reasons = _load_criteria(conn, pid)
        if not any((crit.get(f) or "").strip() for f in CRIT_FIELDS):
            raise HTTPException(400, "Criteria are empty. Fill them in first.")
        records = _unscreened(conn, pid)
    if not records:
        raise HTTPException(400, "No unscreened records to submit.")
    model = db.get_setting("model", config.DEFAULT_MODEL)
    criteria_text = screener.build_criteria_text(crit, reasons)
    try:
        batch_id = batches.submit_batch(pid, model, criteria_text, records)
    except NoKeyError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, anthropic_client._readable_error(e))
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO batch_jobs (project_id, batch_id, status, model, record_count) "
            "VALUES (?,?,?,?,?)", (pid, batch_id, "in_progress", model, len(records)))
        conn.commit()
    return {"ok": True, "batch_id": batch_id, "count": len(records)}


@router.get("/screen/batch/status")
def batch_status(project_id: Optional[int] = Query(None)) -> dict:
    pid = _pid(project_id)
    with db.get_conn() as conn:
        job = _active_batch(conn, pid)
    if not job:
        return {"active_batch": None}
    try:
        b = batches.retrieve(job["batch_id"])
    except Exception as e:  # noqa: BLE001 - keep job; surface message
        return {"active_batch": dict(job), "poll_error": anthropic_client._readable_error(e)}
    processed = batches._counts(b)
    ps = getattr(b, "processing_status", "in_progress")
    new_status = "ended" if ps == "ended" else "in_progress"
    if ps == "ended" and job["status"] != "ended":
        _, reasons = _load_criteria(db.get_conn(), pid)
        batches.process_results(pid, job["batch_id"], job["model"], reasons)
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE batch_jobs SET status=?, result_count=?, updated_at=datetime('now') WHERE id=?",
            (new_status, processed, job["id"]))
        conn.commit()
        job = conn.execute("SELECT * FROM batch_jobs WHERE id=?", (job["id"],)).fetchone()
    return {"active_batch": dict(job)}


@router.post("/screen/batch/cancel")
def cancel_batch(project_id: Optional[int] = Query(None)) -> dict:
    pid = _pid(project_id)
    with db.get_conn() as conn:
        job = _active_batch(conn, pid)
    if not job:
        raise HTTPException(404, "No running batch.")
    try:
        batches.cancel(job["batch_id"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, anthropic_client._readable_error(e))
    return {"ok": True}
