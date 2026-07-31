"""Projects: multi-project support. All other data is scoped to a project."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api", tags=["projects"])

REVIEW_TYPES = [
    "Systematic review", "Scoping review", "Rapid review",
    "Umbrella review", "Literature review", "Other",
]
QUESTION_TYPES = [
    "Therapy/intervention", "Prevention", "Etiology", "Diagnosis",
    "Prognosis", "Qualitative", "Other",
]
AREAS_OF_RESEARCH = [
    "Medical and health sciences", "Biological sciences",
    "Psychology and cognitive sciences", "Agricultural and veterinary sciences",
    "Engineering and technology", "Social sciences", "Education",
    "Economics and business", "Environmental sciences",
    "Information and computing sciences", "Other",
]


class ProjectIn(BaseModel):
    name: str
    review_type: str = ""
    question_type: str = ""
    area_of_research: str = ""
    notes: str = ""


def _project_dict(row) -> dict:
    return dict(row) if row else None


@router.get("/options")
def options() -> dict:
    return {
        "review_types": REVIEW_TYPES,
        "question_types": QUESTION_TYPES,
        "areas_of_research": AREAS_OF_RESEARCH,
    }


@router.get("/projects")
def list_projects() -> dict:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM records r WHERE r.project_id = p.id AND r.active = 1) AS unique_records, "
            "(SELECT COUNT(*) FROM screening_results s WHERE s.project_id = p.id) AS screened "
            "FROM projects p ORDER BY p.created_at DESC"
        ).fetchall()
    current = db.get_setting("current_project_id")
    return {
        "projects": [dict(r) for r in rows],
        "current_project_id": int(current) if current else None,
    }


@router.post("/projects")
def create_project(body: ProjectIn) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Project name is required.")
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, review_type, question_type, area_of_research, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (body.name.strip(), body.review_type, body.question_type,
             body.area_of_research, body.notes),
        )
        pid = cur.lastrowid
        # every project gets exactly one criteria row
        conn.execute("INSERT OR IGNORE INTO criteria (project_id) VALUES (?)", (pid,))
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    db.set_setting("current_project_id", str(pid))  # auto-select new project
    return {"project": dict(row)}


@router.get("/projects/{pid}")
def get_project(pid: int) -> dict:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found.")
    return {"project": dict(row)}


@router.put("/projects/{pid}")
def update_project(pid: int, body: ProjectIn) -> dict:
    with db.get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM projects WHERE id = ?", (pid,)).fetchone()
        if not exists:
            raise HTTPException(404, "Project not found.")
        conn.execute(
            "UPDATE projects SET name=?, review_type=?, question_type=?, "
            "area_of_research=?, notes=? WHERE id=?",
            (body.name.strip(), body.review_type, body.question_type,
             body.area_of_research, body.notes, pid),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    return {"project": dict(row)}


@router.delete("/projects/{pid}")
def delete_project(pid: int) -> dict:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
        conn.commit()
    current = db.get_setting("current_project_id")
    if current and int(current) == pid:
        db.set_setting("current_project_id", "")
    return {"ok": True}


class SelectIn(BaseModel):
    project_id: int


@router.post("/projects/current")
def select_project(body: SelectIn) -> dict:
    with db.get_conn() as conn:
        row = conn.execute("SELECT 1 FROM projects WHERE id = ?", (body.project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found.")
    db.set_setting("current_project_id", str(body.project_id))
    return {"ok": True, "current_project_id": body.project_id}
