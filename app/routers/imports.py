"""Import: upload .ris/.txt files, parse, dedup, and manage the merge-review queue."""
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from .. import db
from ..services import dedup, importer

router = APIRouter(prefix="/api", tags=["imports"])


def _current_pid(project_id: Optional[int]) -> int:
    if project_id:
        return project_id
    cur = db.get_setting("current_project_id")
    if not cur:
        raise HTTPException(400, "No project selected.")
    return int(cur)


def _read(upload: UploadFile) -> str:
    raw = upload.file.read()
    if isinstance(raw, bytes):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "ignore")
    return raw


@router.post("/import/inspect")
async def inspect(files: List[UploadFile] = File(...)) -> dict:
    """Detect format, infer source, and count records per file (no DB writes)."""
    out = []
    for f in files:
        text = _read(f)
        out.append(importer.inspect_file(text, f.filename))
    return {"files": out}


@router.post("/import/commit")
async def commit(
    project_id: int = Form(...),
    files: List[UploadFile] = File(...),
    sources: List[str] = Form(default=[]),
    formats: List[str] = Form(default=[]),
) -> dict:
    """Parse + insert all files, then run layered dedup. Returns PRISMA counts."""
    with db.get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found.")
        imported = []
        for i, f in enumerate(files):
            text = _read(f)
            source = sources[i] if i < len(sources) else ""
            fmt = formats[i] if i < len(formats) and formats[i] in ("ris", "medline") else None
            imported.append(importer.import_one(conn, project_id, text, f.filename, source, fmt))
        summary = dedup.deduplicate(conn, project_id)
    return {"imported": imported, "summary": summary}


@router.get("/import/summary")
def summary(project_id: Optional[int] = Query(None)) -> dict:
    pid = _current_pid(project_id)
    with db.get_conn() as conn:
        s = dedup.counts(conn, pid)
        per_source = conn.execute(
            "SELECT source_database AS source, COUNT(*) AS identified, "
            "SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS kept "
            "FROM records WHERE project_id=? GROUP BY source_database ORDER BY identified DESC",
            (pid,),
        ).fetchall()
        merges = conn.execute(
            "SELECT method, COUNT(*) c FROM merge_log "
            "WHERE project_id=? AND status='merged' GROUP BY method", (pid,),
        ).fetchall()
    s["by_source"] = [dict(r) for r in per_source]
    s["merges_by_method"] = {r["method"]: r["c"] for r in merges}
    return s


@router.post("/import/dedup")
def rerun_dedup(project_id: Optional[int] = Query(None)) -> dict:
    """Re-run dedup (e.g. after adding more files)."""
    pid = _current_pid(project_id)
    with db.get_conn() as conn:
        return dedup.deduplicate(conn, pid)


@router.get("/import/review")
def review_queue(project_id: Optional[int] = Query(None)) -> dict:
    pid = _current_pid(project_id)
    with db.get_conn() as conn:
        logs = conn.execute(
            "SELECT * FROM merge_log WHERE project_id=? AND status='pending_review' "
            "ORDER BY similarity DESC", (pid,),
        ).fetchall()
        items = []
        for lg in logs:
            keep = conn.execute("SELECT * FROM records WHERE id=?", (lg["kept_id"],)).fetchone()
            drop = conn.execute("SELECT * FROM records WHERE id=?", (lg["dropped_id"],)).fetchone()
            items.append({
                "log_id": lg["id"],
                "similarity": lg["similarity"],
                "method": lg["method"],
                "keep": dict(keep) if keep else None,
                "drop": dict(drop) if drop else None,
            })
    return {"items": items}


@router.post("/import/review/{log_id}/confirm")
def confirm_merge(log_id: int) -> dict:
    with db.get_conn() as conn:
        lg = conn.execute("SELECT * FROM merge_log WHERE id=?", (log_id,)).fetchone()
        if not lg or lg["status"] != "pending_review":
            raise HTTPException(404, "No pending merge with that id.")
        conn.execute(
            "UPDATE records SET active=0, merged_into=?, dedup_method='fuzzy' WHERE id=?",
            (lg["kept_id"], lg["dropped_id"]),
        )
        conn.execute("UPDATE merge_log SET status='merged' WHERE id=?", (log_id,))
        conn.commit()
    return {"ok": True}


@router.post("/import/review/{log_id}/split")
def split_merge(log_id: int) -> dict:
    """Keep the two records separate; never auto-suggest this pair again."""
    with db.get_conn() as conn:
        lg = conn.execute("SELECT * FROM merge_log WHERE id=?", (log_id,)).fetchone()
        if not lg or lg["status"] != "pending_review":
            raise HTTPException(404, "No pending merge with that id.")
        conn.execute("UPDATE merge_log SET status='split' WHERE id=?", (log_id,))
        conn.commit()
    return {"ok": True}


@router.post("/import/reset")
def reset_import(project_id: Optional[int] = Query(None)) -> dict:
    """Delete all imported records (and their screening results) for a project."""
    pid = _current_pid(project_id)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM records WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM merge_log WHERE project_id=?", (pid,))
        conn.commit()
    return {"ok": True}
