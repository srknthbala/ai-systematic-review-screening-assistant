"""Standalone test for parsing + layered dedup. Run: python tests/test_import_dedup.py"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SCREENING_DB_PATH"] = os.path.join(tempfile.gettempdir(), "screening_dedup_test.db")
for ext in ("", "-journal"):
    try:
        os.remove(os.environ["SCREENING_DB_PATH"] + ext)
    except OSError:
        pass

from app import db                                    # noqa: E402
from app.services import dedup, importer, ris_parser   # noqa: E402
from app.services.normalize import normalize_text      # noqa: E402

FIX = ROOT / "tests" / "fixtures"
PASS, FAIL = 0, 0


def check(label, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


db.init_db()
with db.get_conn() as conn:
    pid = conn.execute("INSERT INTO projects (name) VALUES ('Dedup Test')").lastrowid
    conn.commit()

files = [
    ("pubmed_results.txt", "PubMed"),
    ("embase.ris", "Embase"),
    ("scopus.ris", "Scopus"),
    ("cochrane.ris", "Cochrane CENTRAL"),
]

print("\n== Format detection & parsing ==")
parsed_counts = {}
with db.get_conn() as conn:
    for fname, source in files:
        text = (FIX / fname).read_text(encoding="utf-8")
        parsed = ris_parser.parse_file(text, fname)
        parsed_counts[fname] = len(parsed["records"])
        expected_fmt = "medline" if fname.endswith(".txt") else "ris"
        check(f"{fname}: detected {parsed['format']} (== {expected_fmt})",
              parsed["format"] == expected_fmt)
        importer.insert_records(conn, pid, parsed["records"], source, "batch1")

check("pubmed parsed 4 records", parsed_counts["pubmed_results.txt"] == 4)
check("embase parsed 2 records", parsed_counts["embase.ris"] == 2)
check("scopus parsed 4 records", parsed_counts["scopus.ris"] == 4)
check("cochrane parsed 3 records", parsed_counts["cochrane.ris"] == 3)

print("\n== Field extraction ==")
with db.get_conn() as conn:
    rows = {r["title"]: r for r in conn.execute(
        "SELECT * FROM records WHERE project_id=?", (pid,)).fetchall()}
    # DOI from MEDLINE AID [doi]
    rec1 = conn.execute(
        "SELECT * FROM records WHERE pmid='30000001'").fetchone()
    check("MEDLINE DOI parsed from AID", rec1["doi"] == "10.1000/jstroke.2019.01")
    check("MEDLINE PMID parsed", rec1["pmid"] == "30000001")
    # no-abstract flag
    brown = conn.execute("SELECT * FROM records WHERE pmid='30000004'").fetchone()
    check("no-abstract flagged (Brown TENS)", brown["has_abstract"] == 0)
    # unicode normalization in title + author
    uni = conn.execute("SELECT * FROM records WHERE pmid='30000003'").fetchone()
    check("unicode beta in title", "beta-alanine" in uni["title"])
    check("unicode degree/plusminus normalized",
          "deg" in uni["title"] and "+/-" in uni["title"])
    check("ascii-only title", all(ord(c) < 128 for c in uni["title"]))
    # RIS PMID from N1 'PMID: ...'
    wang_n1 = conn.execute(
        "SELECT * FROM records WHERE source_database='Embase' AND title LIKE 'Whole-body%'").fetchone()
    check("RIS PMID parsed from N1 note", wang_n1["pmid"] == "30000010")
    # RIS PMID from AN + DB PubMed
    wang_an = conn.execute(
        "SELECT * FROM records WHERE source_database='Scopus' AND title LIKE 'Whole body%'").fetchone()
    check("RIS PMID parsed from AN+DB", wang_an["pmid"] == "30000010")

print("\n== Dedup ==")
with db.get_conn() as conn:
    summary = dedup.deduplicate(conn, pid)
print("  summary:", summary)
check("total_in == 13", summary["total_in"] == 13)
check("duplicates_removed == 3", summary["duplicates_removed"] == 3)
check("unique_out == 10", summary["unique_out"] == 10)
check("pending_review == 1", summary["pending_review_count"] == 1)
check("no_abstract among unique == 1", summary["no_abstract"] == 1)
check("doi_merges == 1", summary["doi_merges"] == 1)
check("pmid_merges == 1", summary["pmid_merges"] == 1)
check("fuzzy_merges == 1", summary["fuzzy_merges"] == 1)

print("\n== Merge provenance & gating ==")
with db.get_conn() as conn:
    # DOI merge: Rec1 (PubMed) kept, Embase copy merged in -> sources both
    rec1 = conn.execute("SELECT * FROM records WHERE pmid='30000001'").fetchone()
    check("DOI-dup kept active", rec1["active"] == 1)
    srcs = dedup.source_databases_for(conn, pid, rec1["id"])
    check("merged record shows both source DBs", set(srcs) == {"PubMed", "Embase"})
    # PMID merge happened across Embase+Scopus
    active_wbv = conn.execute(
        "SELECT COUNT(*) c FROM records WHERE active=1 AND pmid='30000010'").fetchone()["c"]
    check("PMID dup collapsed to 1 active", active_wbv == 1)
    # fuzzy auto pair both inactive-collapsed to 1
    ham = conn.execute(
        "SELECT COUNT(*) c FROM records WHERE active=1 AND title LIKE 'Eccentric training%'").fetchone()["c"]
    check("fuzzy near-dup collapsed to 1 active", ham == 1)
    # borderline pair both still ACTIVE (not silently merged), 1 pending log
    bfr_active = conn.execute(
        "SELECT COUNT(*) c FROM records WHERE active=1 AND title LIKE 'Effects of blood flow%' AND year='2021'").fetchone()["c"]
    check("borderline pair NOT merged (both active)", bfr_active == 2)
    pend = conn.execute(
        "SELECT * FROM merge_log WHERE project_id=? AND status='pending_review'", (pid,)).fetchall()
    check("one pending_review log", len(pend) == 1)
    if pend:
        print(f"     borderline similarity = {pend[0]['similarity']} (want 0.88-0.93)")
        check("borderline similarity in band",
              0.88 <= pend[0]["similarity"] <= 0.93)
    # year gating: 2015 Patel must stay separate & untouched
    patel2015 = conn.execute(
        "SELECT * FROM records WHERE active=1 AND title LIKE 'Effects of blood flow%' AND year='2015'").fetchone()
    check("different-year same-author NOT merged", patel2015 is not None)
    # author gating: Pearson 2021 untouched
    pearson = conn.execute(
        "SELECT * FROM records WHERE active=1 AND title LIKE 'Resistance training%'").fetchone()
    check("low-sim same-block record untouched", pearson is not None)

print(f"\n==== {PASS} passed, {FAIL} failed ====")
sys.exit(1 if FAIL else 0)
