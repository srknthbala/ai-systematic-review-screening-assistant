"""High-level import helpers shared by the router and tests."""
from datetime import datetime, timezone
from typing import Dict, List

from . import ris_parser
from .normalize import title_key


def inspect_file(text: str, filename: str) -> Dict:
    parsed = ris_parser.parse_file(text, filename)
    return {
        "filename": filename,
        "detected_format": parsed["format"],
        "inferred_source": ris_parser.infer_source_database(filename),
        "record_count": len(parsed["records"]),
        "no_abstract": sum(1 for r in parsed["records"] if not r["has_abstract"]),
    }


def insert_records(conn, pid: int, records: List[Dict], source_database: str,
                   import_batch: str) -> int:
    n = 0
    for r in records:
        conn.execute(
            "INSERT INTO records (project_id, title, abstract, authors, first_author, "
            "year, doi, pmid, source_database, raw_id, norm_title, has_abstract, import_batch) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid, r["title"], r["abstract"], "; ".join(r["authors"]),
                r["first_author"], r["year"], r["doi"], r["pmid"],
                source_database, r["raw_id"], title_key(r["title"]),
                r["has_abstract"], import_batch,
            ),
        )
        n += 1
    conn.commit()
    return n


def import_one(conn, pid: int, text: str, filename: str, source_database: str,
               fmt: str | None = None) -> Dict:
    parsed = ris_parser.parse_file(text, filename, fmt)
    batch = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = (source_database or ris_parser.infer_source_database(filename) or "Unknown").strip()
    n = insert_records(conn, pid, parsed["records"], source, batch)
    return {"filename": filename, "format": parsed["format"], "source": source, "inserted": n}
