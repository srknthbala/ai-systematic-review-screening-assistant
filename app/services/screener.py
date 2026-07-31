"""Screening prompt construction, strict-JSON parsing, and per-record screening.

INDEPENDENCE GUARANTEE
----------------------
Every record is screened in its OWN request. The `messages` array contains only
the criteria (as a cached system block) plus the single title/abstract being
judged, never any other study and never any prior decision. There is no
conversation history. In batch mode each request is independent by construction.
The system prompt also explicitly tells the model it has no memory of other
records, so each decision stands alone.
"""
import json
import re
from typing import Dict, List, Optional

from .normalize import normalize_text

# ---- The fixed rules (system block #1). Identical for every call. ----
SCREENING_INSTRUCTIONS = """You are a meticulous systematic-review screener performing TITLE/ABSTRACT screening.

You are given the review's eligibility criteria and ONE study (title + abstract).
Judge ONLY that single study against the criteria.

INDEPENDENCE: You have no memory of any other study. Do not compare this study to
others, do not assume anything about a "set". Treat this as the first and only
record you have ever seen. Your decision must be reproducible and self-contained.

THREE-WAY DECISION: return exactly one of INCLUDE, EXCLUDE, or MAYBE.
Use MAYBE (never force a binary call) when:
  - the abstract is missing or empty, or
  - population / intervention / comparator is ambiguous, or
  - the study looks relevant but cannot be decided from the abstract alone.

TITLE/ABSTRACT STAGE ONLY. Exclude only on grounds that are visible in a title or
abstract (e.g. animal study, pediatric population, healthy volunteers,
sensory-level TENS only, clearly wrong population, no muscle-related outcome
mentioned). Criteria that require the full text (sufficient numeric data for an
effect size, exact timing such as >=5-day post-baseline, crossover washout
adequacy) must NOT trigger an EXCLUDE. If such a full-text-only concern is your
ONLY reason for doubt, return MAYBE.

AUTO-TAG the study when these are detected in the abstract (add to "tags"):
  - "Confound: BFR"  (blood-flow restriction used)
  - "Confound: Protein supplementation"
  - "Spasticity present"

EXCLUSION REASON CATEGORY:
  - If the criteria include a reason list, set "exclusion_reason_category" to the
    SINGLE best-fit item from that list for any EXCLUDE or MAYBE (verbatim).
  - If there is no reason list, set "exclusion_reason_category" to null and put a
    short free-text reason in "reason".
  - For INCLUDE, "exclusion_reason_category" is null.

OUTPUT: return ONLY a single JSON object, no prose and no code fences, with
EXACTLY these keys:
{
  "decision": "INCLUDE" | "EXCLUDE" | "MAYBE",
  "confidence": 0.0-1.0,
  "reason": "one short line",
  "exclusion_reason_category": "<one item from the reason list, or null>",
  "tags": []
}"""

CATEGORY_LABELS = [
    ("pop", "Population"),
    ("int", "Intervention / Exposure"),
    ("comp", "Comparator / Context"),
    ("out", "Outcome"),
    ("study", "Study Characteristics"),
    ("other", "Other"),
]
AUTO_TAGS = ["Confound: BFR", "Confound: Protein supplementation", "Spasticity present"]


def build_criteria_text(criteria: Dict, reason_list: List[str]) -> str:
    """The cached system block (#2): the eligibility criteria + reason list."""
    lines = ["ELIGIBILITY CRITERIA (PICOS). Identical for every record in this run.\n"]
    for key, label in CATEGORY_LABELS:
        inc = (criteria.get(f"{key}_include") or "").strip() or "(none specified)"
        exc = (criteria.get(f"{key}_exclude") or "").strip() or "(none specified)"
        lines.append(f"== {label} ==")
        lines.append(f"INCLUDE: {inc}")
        lines.append(f"EXCLUDE: {exc}\n")
    if reason_list:
        lines.append("EXCLUSION REASON CATEGORIES: for any EXCLUDE or MAYBE, choose the single")
        lines.append("best-fit item below and copy it VERBATIM into exclusion_reason_category:")
        for r in reason_list:
            lines.append(f"  - {r}")
    else:
        lines.append("No predefined exclusion-reason list: set exclusion_reason_category to null")
        lines.append("and write a short free-text reason in the reason field.")
    return "\n".join(lines)


def build_user_message(record: Dict) -> str:
    title = normalize_text(record.get("title")) or "(no title)"
    abstract = normalize_text(record.get("abstract"))
    parts = [f"TITLE: {title}", ""]
    if abstract:
        parts.append(f"ABSTRACT: {abstract}")
    else:
        parts.append("ABSTRACT: (none provided, cannot be content-screened)")
    parts.append("")
    parts.append("Screen this single study now and return only the JSON object.")
    return "\n".join(parts)


# ---- robust JSON parsing ----
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_response(text: str) -> Dict:
    t = (text or "").strip()
    t = _FENCE.sub("", t).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        t = m.group(0)
    return json.loads(t)


def normalize_result(data: Dict, reason_list: List[str], raw: str) -> Dict:
    decision = str(data.get("decision", "")).strip().upper()
    if decision not in ("INCLUDE", "EXCLUDE", "MAYBE"):
        raise ValueError(f"bad decision: {decision!r}")
    try:
        conf = float(data.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))

    reason = " ".join(str(data.get("reason", "")).split())[:400]

    cat = data.get("exclusion_reason_category")
    cat = None if cat in (None, "", "null") else str(cat).strip()
    if reason_list:
        if cat:
            match = next((r for r in reason_list if r.lower() == cat.lower()), None)
            cat = match  # only allow verbatim list members; else null
    else:
        cat = None
    if decision == "INCLUDE":
        cat = None

    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    tags = [str(t).strip() for t in tags if str(t).strip()]

    return {
        "decision": decision,
        "confidence": conf,
        "reason": reason,
        "exclusion_reason_category": cat,
        "tags": tags,
        "raw_response": raw,
        "error": None,
    }


def _failed_result(raw: str, err: str) -> Dict:
    return {
        "decision": "MAYBE",
        "confidence": 0.0,
        "reason": "Unparseable model output. Manual check needed.",
        "exclusion_reason_category": None,
        "tags": [],
        "raw_response": raw,
        "error": err,
    }


def screen_one(client, model: str, system: List[Dict], record: Dict,
               reason_list: List[str]) -> Dict:
    """Screen a single record. Retries once on malformed JSON. API/network
    errors propagate to the caller (so the record stays unscreened and is
    retried on the next run)."""
    user = build_user_message(record)
    last_raw = ""
    for attempt in range(2):
        msg = client.messages.create(
            model=model,
            max_tokens=400,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        last_raw = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            return normalize_result(parse_response(last_raw), reason_list, last_raw)
        except Exception:  # noqa: BLE001 - malformed output
            if attempt == 0:
                user = build_user_message(record) + (
                    "\n\nIMPORTANT: Your previous reply was not valid JSON. "
                    "Return ONLY the JSON object with the required keys.")
                continue
            return _failed_result(last_raw, "json_parse_failed")
    return _failed_result(last_raw, "json_parse_failed")


def request_params(model: str, system: List[Dict], record: Dict) -> Dict:
    """Params block for one Message Batches request (same contract as sync)."""
    return {
        "model": model,
        "max_tokens": 400,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": build_user_message(record)}],
    }


def save_result(conn, pid: int, rec_id: int, res: Dict, model: str, run_type: str) -> None:
    """Write/replace one screening result. Caller commits. Idempotent per record."""
    conn.execute(
        "INSERT INTO screening_results "
        "(project_id, record_id, decision, confidence, reason, exclusion_reason_category, "
        " tags, model, run_type, raw_response, error) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(project_id, record_id) DO UPDATE SET "
        " decision=excluded.decision, confidence=excluded.confidence, reason=excluded.reason, "
        " exclusion_reason_category=excluded.exclusion_reason_category, tags=excluded.tags, "
        " model=excluded.model, run_type=excluded.run_type, raw_response=excluded.raw_response, "
        " error=excluded.error",
        (
            pid, rec_id, res["decision"], res["confidence"], res["reason"],
            res["exclusion_reason_category"], json.dumps(res["tags"]), model,
            run_type, res.get("raw_response", ""), res.get("error"),
        ),
    )
