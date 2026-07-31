"""Layered deduplication, scoped to one project.

Order:
  1. exact DOI match
  2. PMID match (for records not already merged by DOI)
  3. fuzzy title match for records missing BOTH identifiers, requiring the same
     publication year AND the same first-author surname.

Thresholds (editable):
  - FUZZY_MATCH = 0.92  : nominal "this is a duplicate" similarity.
  - REVIEW_BAND = [0.88, 0.93] : borderline. These are NEVER merged silently;
    they go to the merge-review queue so the user confirms or splits them.
  Net effect: pairs with similarity > 0.93 (and matching year + first author)
  auto-merge; pairs in [0.88, 0.93] go to review; below 0.88 stay distinct.

Every merge is logged. Surviving record provenance (which databases it came
from) is reconstructed from its merged children at read time.
"""
from difflib import SequenceMatcher
from typing import Dict, List

from .normalize import author_key, normalize_doi, title_key

FUZZY_MATCH = 0.92
REVIEW_LOW = 0.88
REVIEW_HIGH = 0.93


def _root(conn, rid: int) -> int:
    seen = set()
    while True:
        row = conn.execute(
            "SELECT id, active, merged_into FROM records WHERE id = ?", (rid,)
        ).fetchone()
        if row is None:
            return rid
        if row["active"] == 1 or row["merged_into"] is None:
            return row["id"]
        if rid in seen:
            return rid
        seen.add(rid)
        rid = row["merged_into"]


def _prefer(conn, a: int, b: int):
    """Return (keep, drop). Prefer record with abstract, then DOI, then PMID,
    then the earlier (lower id) record."""
    ra = conn.execute("SELECT * FROM records WHERE id = ?", (a,)).fetchone()
    rb = conn.execute("SELECT * FROM records WHERE id = ?", (b,)).fetchone()

    def score(r):
        return (r["has_abstract"], 1 if r["doi"] else 0, 1 if r["pmid"] else 0, -r["id"])

    return (a, b) if score(ra) >= score(rb) else (b, a)


def _merge(conn, keep: int, drop: int, method: str, sim: float, pid: int) -> None:
    keep, drop = _root(conn, keep), _root(conn, drop)
    if keep == drop:
        return
    keep, drop = _prefer(conn, keep, drop)
    conn.execute(
        "UPDATE records SET active = 0, merged_into = ?, dedup_method = ? WHERE id = ?",
        (keep, method, drop),
    )
    conn.execute(
        "INSERT INTO merge_log (project_id, kept_id, dropped_id, method, similarity, status) "
        "VALUES (?, ?, ?, ?, ?, 'merged')",
        (pid, keep, drop, method, sim),
    )


def _active(conn, pid: int):
    return conn.execute(
        "SELECT * FROM records WHERE project_id = ? AND active = 1", (pid,)
    ).fetchall()


def _existing_pairs(conn, pid: int) -> set:
    """Pairs already decided (pending review or split) so we don't re-add them."""
    rows = conn.execute(
        "SELECT kept_id, dropped_id FROM merge_log "
        "WHERE project_id = ? AND status IN ('pending_review', 'split')",
        (pid,),
    ).fetchall()
    return {frozenset((r["kept_id"], r["dropped_id"])) for r in rows}


def deduplicate(conn, pid: int) -> Dict:
    """Run all layers for a project. Returns a counts summary."""
    # ---- Layer 1: exact DOI ----
    by_doi: Dict[str, List[int]] = {}
    for r in _active(conn, pid):
        d = normalize_doi(r["doi"])
        if d:
            by_doi.setdefault(d, []).append(r["id"])
    doi_merges = 0
    for ids in by_doi.values():
        if len(ids) > 1:
            base = ids[0]
            for other in ids[1:]:
                before = _root(conn, base)
                _merge(conn, base, other, "doi", 1.0, pid)
                base = _root(conn, base)
                if base != before or True:
                    doi_merges += 1

    # ---- Layer 2: PMID (records not already merged by DOI) ----
    by_pmid: Dict[str, List[int]] = {}
    for r in _active(conn, pid):
        p = (r["pmid"] or "").strip()
        if p:
            by_pmid.setdefault(p, []).append(r["id"])
    pmid_merges = 0
    for ids in by_pmid.values():
        if len(ids) > 1:
            base = ids[0]
            for other in ids[1:]:
                _merge(conn, base, other, "pmid", 1.0, pid)
                base = _root(conn, base)
                pmid_merges += 1

    # ---- Layer 3: fuzzy title (records missing BOTH identifiers) ----
    candidates = [
        r for r in _active(conn, pid)
        if not (r["doi"] or "").strip() and not (r["pmid"] or "").strip()
    ]
    # block by (year, first letter of author key) to keep comparisons cheap
    blocks: Dict[tuple, List] = {}
    for r in candidates:
        yr = (r["year"] or "").strip()
        ak = author_key(r["first_author"])
        if not yr or not ak:
            continue  # year + first-author required for a fuzzy match
        blocks.setdefault((yr, ak[0]), []).append(r)

    decided = _existing_pairs(conn, pid)
    fuzzy_merges = 0
    review_added = 0
    for block in blocks.values():
        n = len(block)
        for i in range(n):
            ri = block[i]
            ki = title_key(ri["title"])
            aki = author_key(ri["first_author"])
            if not ki:
                continue
            for j in range(i + 1, n):
                rj = block[j]
                if ri["year"] != rj["year"]:
                    continue
                akj = author_key(rj["first_author"])
                if not aki or aki != akj:
                    continue
                pair = frozenset((ri["id"], rj["id"]))
                if pair in decided:
                    continue
                kj = title_key(rj["title"])
                if not kj:
                    continue
                sim = SequenceMatcher(None, ki, kj).ratio()
                if sim > REVIEW_HIGH:
                    _merge(conn, ri["id"], rj["id"], "fuzzy", round(sim, 4), pid)
                    fuzzy_merges += 1
                    decided.add(pair)
                elif REVIEW_LOW <= sim <= REVIEW_HIGH:
                    keep, drop = _prefer(conn, ri["id"], rj["id"])
                    conn.execute(
                        "INSERT INTO merge_log (project_id, kept_id, dropped_id, method, similarity, status) "
                        "VALUES (?, ?, ?, ?, ?, 'pending_review')",
                        (pid, keep, drop, "fuzzy", round(sim, 4)),
                    )
                    review_added += 1
                    decided.add(pair)
    conn.commit()
    return counts(conn, pid) | {
        "doi_merges": doi_merges,
        "pmid_merges": pmid_merges,
        "fuzzy_merges": fuzzy_merges,
        "pending_review": review_added,
    }


def counts(conn, pid: int) -> Dict:
    total = conn.execute(
        "SELECT COUNT(*) c FROM records WHERE project_id = ?", (pid,)
    ).fetchone()["c"]
    unique = conn.execute(
        "SELECT COUNT(*) c FROM records WHERE project_id = ? AND active = 1", (pid,)
    ).fetchone()["c"]
    no_abstract = conn.execute(
        "SELECT COUNT(*) c FROM records WHERE project_id = ? AND active = 1 AND has_abstract = 0",
        (pid,),
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM merge_log WHERE project_id = ? AND status = 'pending_review'",
        (pid,),
    ).fetchone()["c"]
    return {
        "total_in": total,
        "duplicates_removed": total - unique,
        "unique_out": unique,
        "no_abstract": no_abstract,
        "pending_review_count": pending,
    }


def source_databases_for(conn, pid: int, record_id: int) -> List[str]:
    """All databases a surviving record came from (itself + merged children)."""
    rows = conn.execute(
        "SELECT source_database FROM records "
        "WHERE project_id = ? AND (id = ? OR merged_into = ?)",
        (pid, record_id, record_id),
    ).fetchall()
    seen = []
    for r in rows:
        s = (r["source_database"] or "").strip()
        if s and s not in seen:
            seen.append(s)
    return seen
