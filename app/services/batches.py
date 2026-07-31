"""Message Batches API: submit, poll, retrieve, cancel.

Batch requests are independent of one another (each carries only the criteria +
one record). Prompt caching on the criteria block stacks with the 50% batch
discount. Results are written to SQLite incrementally so a crash or app close
never loses progress; re-polling an already-finished batch is a no-op.
"""
import json
from typing import Dict, List

from .. import db
from . import screener
from .anthropic_client import get_client, system_blocks


def submit_batch(pid: int, model: str, criteria_text: str, records: List) -> str:
    client = get_client()
    system = system_blocks(criteria_text)
    requests = [
        {"custom_id": f"rec-{r['id']}", "params": screener.request_params(model, system, dict(r))}
        for r in records
    ]
    batch = client.messages.batches.create(requests=requests)
    return batch.id


def retrieve(batch_id: str):
    return get_client().messages.batches.retrieve(batch_id)


def cancel(batch_id: str):
    return get_client().messages.batches.cancel(batch_id)


def _counts(batch) -> int:
    rc = batch.request_counts
    return (getattr(rc, "succeeded", 0) + getattr(rc, "errored", 0)
            + getattr(rc, "canceled", 0) + getattr(rc, "expired", 0))


def process_results(pid: int, batch_id: str, model: str, reason_list: List[str]) -> int:
    """Stream results, parse, and write each to SQLite. Returns rows written."""
    client = get_client()
    written = 0
    conn = db.get_conn()
    try:
        for entry in client.messages.batches.results(batch_id):
            cid = getattr(entry, "custom_id", "") or ""
            if not cid.startswith("rec-"):
                continue
            try:
                rec_id = int(cid.split("-", 1)[1])
            except ValueError:
                continue
            result = entry.result
            rtype = getattr(result, "type", "errored")
            if rtype == "succeeded":
                raw = "".join(getattr(b, "text", "") for b in result.message.content)
                try:
                    res = screener.normalize_result(screener.parse_response(raw), reason_list, raw)
                except Exception:  # noqa: BLE001
                    res = screener._failed_result(raw, "json_parse_failed")
            else:
                res = {
                    "decision": "MAYBE", "confidence": 0.0,
                    "reason": f"Batch request {rtype}; needs manual check.",
                    "exclusion_reason_category": None, "tags": [],
                    "raw_response": "", "error": rtype,
                }
            screener.save_result(conn, pid, rec_id, res, model, "batch")
            written += 1
            if written % 50 == 0:
                conn.commit()
        conn.commit()
    finally:
        conn.close()
    return written
