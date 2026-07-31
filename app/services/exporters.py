"""Export formats: RIS for downstream tools, PRISMA counts for the flow diagram.

RIS is what Covidence / Rayyan / EndNote actually ingest, so exporting the
included records as RIS is the normal handoff from title/abstract screening
to full-text screening.
"""
import csv
import io
import json
from typing import Dict, Iterable, List, Optional

from . import dedup

# RIS is line-oriented: a two-letter tag, two spaces, a hyphen, a space, then
# the value. "ER  - " terminates a record. Readers are strict about the spacing.
_RIS_LINE = "{tag}  - {value}"


def _ris_line(tag: str, value: str) -> str:
    # Newlines inside a value would be read as a new (untagged) line and
    # silently truncate the field, so flatten them.
    clean = " ".join(str(value or "").split())
    return _RIS_LINE.format(tag=tag, value=clean)


def record_to_ris(rec: Dict, result: Optional[Dict] = None,
                  sources: Optional[List[str]] = None) -> str:
    """One record as an RIS entry. `result` adds the screening decision as a note."""
    lines = [_ris_line("TY", "JOUR")]
    if rec.get("title"):
        lines.append(_ris_line("TI", rec["title"]))
    for author in [a for a in (rec.get("authors") or "").split(";") if a.strip()]:
        lines.append(_ris_line("AU", author.strip()))
    if rec.get("year"):
        lines.append(_ris_line("PY", rec["year"]))
    if rec.get("abstract"):
        lines.append(_ris_line("AB", rec["abstract"]))
    if rec.get("doi"):
        lines.append(_ris_line("DO", rec["doi"]))
        lines.append(_ris_line("UR", f"https://doi.org/{rec['doi']}"))
    if rec.get("pmid"):
        lines.append(_ris_line("AN", rec["pmid"]))
    for src in (sources or []):
        lines.append(_ris_line("DB", src))

    if result:
        conf = result.get("confidence")
        conf_txt = f", confidence {conf:.2f}" if isinstance(conf, (int, float)) else ""
        note = f"AI screening: {result.get('decision') or 'n/a'}{conf_txt}"
        if result.get("reason"):
            note += f". {result['reason']}"
        if result.get("exclusion_reason_category"):
            note += f" [{result['exclusion_reason_category']}]"
        lines.append(_ris_line("N1", note))
        for tag in (result.get("tags") or []):
            lines.append(_ris_line("KW", tag))

    lines.append("ER  - ")
    return "\r\n".join(lines)


def build_ris(rows: Iterable[Dict]) -> str:
    """Join record dicts into a full RIS file (CRLF, as the format expects)."""
    entries = [
        record_to_ris(r["record"], r.get("result"), r.get("sources"))
        for r in rows
    ]
    return "\r\n\r\n".join(entries) + "\r\n"


def ris_rows(conn, pid: int, decisions: Optional[List[str]] = None) -> List[Dict]:
    """Screened records for a project, optionally limited to given decisions."""
    sql = (
        "SELECT r.id, r.title, r.abstract, r.authors, r.year, r.doi, r.pmid, "
        "s.decision, s.confidence, s.reason, s.exclusion_reason_category, s.tags "
        "FROM screening_results s JOIN records r ON r.id = s.record_id "
        "WHERE s.project_id = ? AND r.active = 1"
    )
    params: List = [pid]
    if decisions:
        sql += " AND s.decision IN (%s)" % ",".join("?" * len(decisions))
        params.extend(decisions)
    sql += " ORDER BY r.year DESC, r.title"

    out = []
    for r in conn.execute(sql, params).fetchall():
        out.append({
            "record": {
                "title": r["title"], "abstract": r["abstract"], "authors": r["authors"],
                "year": r["year"], "doi": r["doi"], "pmid": r["pmid"],
            },
            "result": {
                "decision": r["decision"], "confidence": r["confidence"],
                "reason": r["reason"],
                "exclusion_reason_category": r["exclusion_reason_category"],
                "tags": json.loads(r["tags"] or "[]"),
            },
            "sources": dedup.source_databases_for(conn, pid, r["id"]),
        })
    return out


def prisma_rows(conn, pid: int) -> List[List[str]]:
    """Flat stage/count rows for a PRISMA 2020 identification+screening flow."""
    counts = dedup.counts(conn, pid)

    per_source = conn.execute(
        "SELECT source_database AS source, COUNT(*) AS identified "
        "FROM records WHERE project_id=? GROUP BY source_database "
        "ORDER BY identified DESC", (pid,),
    ).fetchall()
    by_method = {
        r["method"]: r["c"] for r in conn.execute(
            "SELECT method, COUNT(*) c FROM merge_log "
            "WHERE project_id=? AND status='merged' GROUP BY method", (pid,),
        ).fetchall()
    }
    decisions = {
        r["decision"]: r["c"] for r in conn.execute(
            "SELECT s.decision, COUNT(*) c FROM screening_results s "
            "JOIN records r ON r.id=s.record_id "
            "WHERE s.project_id=? AND r.active=1 GROUP BY s.decision", (pid,),
        ).fetchall()
    }
    # Reason categories are attached to MAYBE rows as well as EXCLUDE rows, but
    # a PRISMA "excluded with reasons" breakdown has to sum to the excluded
    # count, so split the two rather than lumping them together.
    def _cats(decision: str):
        return conn.execute(
            "SELECT s.exclusion_reason_category cat, COUNT(*) c FROM screening_results s "
            "JOIN records r ON r.id=s.record_id "
            "WHERE s.project_id=? AND r.active=1 AND s.decision=? "
            "AND s.exclusion_reason_category IS NOT NULL "
            "GROUP BY cat ORDER BY c DESC", (pid, decision),
        ).fetchall()

    excluded_cats = _cats("EXCLUDE")
    maybe_cats = _cats("MAYBE")

    rows: List[List[str]] = [["stage", "count"]]
    for r in per_source:
        rows.append([f"Records identified from {r['source'] or 'unlabelled source'}",
                     str(r["identified"])])
    rows.append(["Records identified (total)", str(counts["total_in"])])
    for method in ("doi", "pmid", "fuzzy"):
        rows.append([f"Duplicates removed by {method.upper()}", str(by_method.get(method, 0))])
    rows.append(["Duplicates removed (total)", str(counts["duplicates_removed"])])
    rows.append(["Records after duplicates removed", str(counts["unique_out"])])

    screened = sum(decisions.values())
    rows.append(["Records screened (title/abstract)", str(screened)])
    rows.append(["Records excluded", str(decisions.get("EXCLUDE", 0))])
    for c in excluded_cats:
        rows.append([f"  Excluded, reason: {c['cat']}", str(c["c"])])
    rows.append(["Records marked maybe (needs review)", str(decisions.get("MAYBE", 0))])
    for c in maybe_cats:
        rows.append([f"  Maybe, reason: {c['cat']}", str(c["c"])])
    rows.append(["Records sought for retrieval (included)", str(decisions.get("INCLUDE", 0))])
    rows.append(["Records not yet screened", str(counts["unique_out"] - screened)])
    rows.append(["Records without an abstract", str(counts["no_abstract"])])
    return rows


def rows_to_csv(rows: Iterable[Iterable]) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()
