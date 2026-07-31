"""Criteria: the 12 PICOS boxes + optional full-text exclusion reason list."""
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api", tags=["criteria"])

FIELDS = [
    "pop_include", "pop_exclude", "int_include", "int_exclude",
    "comp_include", "comp_exclude", "out_include", "out_exclude",
    "study_include", "study_exclude", "other_include", "other_exclude",
]


class CriteriaIn(BaseModel):
    project_id: int
    pop_include: str = ""
    pop_exclude: str = ""
    int_include: str = ""
    int_exclude: str = ""
    comp_include: str = ""
    comp_exclude: str = ""
    out_include: str = ""
    out_exclude: str = ""
    study_include: str = ""
    study_exclude: str = ""
    other_include: str = ""
    other_exclude: str = ""
    exclusion_reasons: List[str] = []


def _row_to_dict(row) -> dict:
    d = {f: (row[f] or "") for f in FIELDS}
    try:
        d["exclusion_reasons"] = json.loads(row["exclusion_reasons"] or "[]")
    except Exception:
        d["exclusion_reasons"] = []
    return d


@router.get("/criteria")
def get_criteria(project_id: int) -> dict:
    with db.get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found.")
        row = conn.execute("SELECT * FROM criteria WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO criteria (project_id) VALUES (?)", (project_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM criteria WHERE project_id=?", (project_id,)).fetchone()
    return {"criteria": _row_to_dict(row)}


@router.put("/criteria")
def save_criteria(body: CriteriaIn) -> dict:
    reasons = [r.strip() for r in body.exclusion_reasons if r and r.strip()]
    with db.get_conn() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (body.project_id,)).fetchone():
            raise HTTPException(404, "Project not found.")
        sets = ", ".join(f"{f}=?" for f in FIELDS)
        values = [getattr(body, f) for f in FIELDS]
        conn.execute(
            f"INSERT INTO criteria (project_id) VALUES (?) ON CONFLICT(project_id) DO NOTHING",
            (body.project_id,),
        )
        conn.execute(
            f"UPDATE criteria SET {sets}, exclusion_reasons=?, updated_at=datetime('now') "
            f"WHERE project_id=?",
            (*values, json.dumps(reasons), body.project_id),
        )
        conn.commit()
    return {"ok": True, "saved_reasons": reasons}
