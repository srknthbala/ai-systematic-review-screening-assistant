"""Results: filterable table, PRISMA summary counts, and CSV export."""
import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import db
from ..services import dedup, exporters

router = APIRouter(prefix="/api", tags=["results"])

DECISION_ORDER = "CASE s.decision WHEN 'INCLUDE' THEN 0 WHEN 'MAYBE' THEN 1 ELSE 2 END"


def _pid(project_id: Optional[int]) -> int:
    if project_id:
        return project_id
    cur = db.get_setting("current_project_id")
    if not cur:
        raise HTTPException(400, "No project selected.")
    return int(cur)


def _where(pid, decision, category, tag, has_abstract):
    clauses = ["s.project_id=?", "r.active=1"]
    params = [pid]
    if decision:
        clauses.append("s.decision=?"); params.append(decision)
    if category:
        clauses.append("s.exclusion_reason_category=?"); params.append(category)
    if tag:
        clauses.append("s.tags LIKE ?"); params.append(f'%"{tag}"%')
    if has_abstract in ("0", "1"):
        clauses.append("r.has_abstract=?"); params.append(int(has_abstract))
    return " AND ".join(clauses), params


def _rows(conn, pid, decision, category, tag, has_abstract, with_abstract=False):
    """Screened rows for the table or an export.

    `with_abstract` is off for the table on purpose, since abstracts would add
    megabytes to a JSON payload that only renders titles.
    """
    where, params = _where(pid, decision, category, tag, has_abstract)
    sql = (
        "SELECT r.id, r.title, r.first_author, r.year, r.doi, r.pmid, r.has_abstract, "
        "r.abstract, s.decision, s.confidence, s.reason, s.exclusion_reason_category, s.tags "
        "FROM screening_results s JOIN records r ON r.id=s.record_id "
        f"WHERE {where} ORDER BY {DECISION_ORDER}, s.confidence DESC")
    out = []
    for r in conn.execute(sql, params).fetchall():
        row = {
            "id": r["id"], "title": r["title"], "first_author": r["first_author"],
            "year": r["year"], "doi": r["doi"], "pmid": r["pmid"],
            "has_abstract": r["has_abstract"], "decision": r["decision"],
            "confidence": r["confidence"], "reason": r["reason"],
            "exclusion_reason_category": r["exclusion_reason_category"],
            "tags": json.loads(r["tags"] or "[]"),
            "source_databases": dedup.source_databases_for(conn, pid, r["id"]),
        }
        if with_abstract:
            row["abstract"] = r["abstract"] or ""
        out.append(row)
    return out


@router.get("/results/meta")
def meta(project_id: Optional[int] = Query(None)) -> dict:
    pid = _pid(project_id)
    with db.get_conn() as conn:
        dec = conn.execute(
            "SELECT s.decision d, COUNT(*) c FROM screening_results s JOIN records r ON r.id=s.record_id "
            "WHERE s.project_id=? AND r.active=1 GROUP BY s.decision", (pid,)).fetchall()
        cats = conn.execute(
            "SELECT s.exclusion_reason_category cat, COUNT(*) c FROM screening_results s "
            "JOIN records r ON r.id=s.record_id WHERE s.project_id=? AND r.active=1 "
            "AND s.exclusion_reason_category IS NOT NULL GROUP BY cat ORDER BY c DESC", (pid,)).fetchall()
        tag_rows = conn.execute(
            "SELECT s.tags FROM screening_results s JOIN records r ON r.id=s.record_id "
            "WHERE s.project_id=? AND r.active=1", (pid,)).fetchall()
    summary = {"INCLUDE": 0, "EXCLUDE": 0, "MAYBE": 0, "total": 0, "by_category": {}}
    for r in dec:
        summary[r["d"]] = r["c"]; summary["total"] += r["c"]
    summary["by_category"] = {r["cat"]: r["c"] for r in cats}
    all_tags = set()
    for tr in tag_rows:
        for t in json.loads(tr["tags"] or "[]"):
            all_tags.add(t)
    return {"summary": summary, "categories": [r["cat"] for r in cats], "tags": sorted(all_tags)}


@router.get("/results")
def results(project_id: Optional[int] = Query(None), decision: Optional[str] = None,
            category: Optional[str] = None, tag: Optional[str] = None,
            has_abstract: Optional[str] = None) -> dict:
    pid = _pid(project_id)
    with db.get_conn() as conn:
        rows = _rows(conn, pid, decision, category, tag, has_abstract)
    return {"rows": rows, "count": len(rows)}


@router.get("/results/export.csv")
def export_csv(project_id: Optional[int] = Query(None), decision: Optional[str] = None,
               category: Optional[str] = None, tag: Optional[str] = None,
               has_abstract: Optional[str] = None,
               include_abstract: str = Query("0")):
    pid = _pid(project_id)
    want_abstract = include_abstract in ("1", "true", "yes")
    with db.get_conn() as conn:
        rows = _rows(conn, pid, decision, category, tag, has_abstract,
                     with_abstract=want_abstract)
    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["title", "year", "source_databases", "decision", "confidence", "reason",
              "exclusion_reason_category", "tags", "doi", "pmid", "has_abstract"]
    if want_abstract:
        header.append("abstract")
    w.writerow(header)
    for r in rows:
        line = [
            r["title"], r["year"], "; ".join(r["source_databases"]), r["decision"],
            f'{r["confidence"]:.2f}' if r["confidence"] is not None else "", r["reason"],
            r["exclusion_reason_category"] or "", "; ".join(r["tags"]),
            r["doi"], r["pmid"], "yes" if r["has_abstract"] else "no",
        ]
        if want_abstract:
            line.append(r.get("abstract", ""))
        w.writerow(line)
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="screening_results_project_{pid}.csv"'}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)


@router.get("/results/export.ris")
def export_ris(project_id: Optional[int] = Query(None),
               decisions: str = Query("INCLUDE")):
    """Screened records as RIS, for import into Covidence / Rayyan / EndNote.

    `decisions` is a comma-separated list; defaults to just INCLUDE, which is
    the set you carry forward to full-text screening.
    """
    pid = _pid(project_id)
    wanted = [d.strip().upper() for d in decisions.split(",") if d.strip()]
    allowed = {"INCLUDE", "EXCLUDE", "MAYBE"}
    bad = [d for d in wanted if d not in allowed]
    if bad:
        raise HTTPException(400, f"Unknown decision(s): {', '.join(bad)}")
    with db.get_conn() as conn:
        rows = exporters.ris_rows(conn, pid, wanted or None)
    body = exporters.build_ris(rows)
    slug = "_".join(d.lower() for d in wanted) or "all"
    headers = {"Content-Disposition":
               f'attachment; filename="screening_{slug}_project_{pid}.ris"'}
    return StreamingResponse(iter([body]), media_type="application/x-research-info-systems",
                             headers=headers)


@router.get("/results/prisma.csv")
def export_prisma(project_id: Optional[int] = Query(None)):
    """Stage-by-stage counts for a PRISMA 2020 flow diagram."""
    pid = _pid(project_id)
    with db.get_conn() as conn:
        rows = exporters.prisma_rows(conn, pid)
    headers = {"Content-Disposition": f'attachment; filename="prisma_flow_project_{pid}.csv"'}
    return StreamingResponse(iter([exporters.rows_to_csv(rows)]),
                             media_type="text/csv", headers=headers)
