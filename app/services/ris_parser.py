"""Parse RIS and PubMed/MEDLINE (.nbib/.txt) reference files.

Both formats put a tag in a 4-char field with the hyphen at column 5
(RIS uses 2-char tags padded with spaces: 'TY  - '; MEDLINE uses up to
4-char tags: 'PMID- ', 'TI  - '). We sniff which one a file is, then parse.

Each parsed record is a dict with normalized fields:
    title, abstract, authors (list), first_author, year, doi, pmid, raw_id
Text fields are run through normalize_text() so downstream code is ASCII-safe.
"""
import re
from typing import Dict, List

from .normalize import (
    extract_doi,
    extract_pmid,
    normalize_text,
    year_of,
)

# A tag line in either format: 2-4 char tag, optional padding spaces, '- ', value.
_TAG_RE = re.compile(r"^([A-Z][A-Z0-9]{1,3})\s{0,2}-\s?(.*)$")

SOURCE_HINTS = [
    ("pubmed", "PubMed"), ("medline", "MEDLINE"), ("embase", "Embase"),
    ("scopus", "Scopus"), ("cochrane", "Cochrane CENTRAL"),
    ("central", "Cochrane CENTRAL"), ("cinahl", "CINAHL"),
    ("web of science", "Web of Science"), ("webofscience", "Web of Science"),
    ("wos", "Web of Science"), ("proquest", "ProQuest"), ("ovid", "Ovid"),
    ("psycinfo", "PsycINFO"), ("scholar", "Google Scholar"),
]


def infer_source_database(filename: str) -> str:
    f = (filename or "").lower()
    for key, label in SOURCE_HINTS:
        if key in f:
            return label
    return ""


def sniff_format(text: str, filename: str = "") -> str:
    """Return 'ris', 'medline', or 'unknown'."""
    head = "\n".join(text.replace("\r", "\n").split("\n")[:300])
    if re.search(r"^TY\s{0,2}-\s", head, re.M):
        return "ris"
    if re.search(r"^ER\s{0,2}-", head, re.M) and re.search(r"^(AU|TI|T1)\s{0,2}-", head, re.M):
        return "ris"
    if re.search(r"^PMID-\s", head, re.M):
        return "medline"
    if re.search(r"^(FAU|MH|AB|TI)\s{0,2}-", head, re.M) and not re.search(r"^TY\s", head, re.M):
        return "medline"
    fn = (filename or "").lower()
    if fn.endswith(".ris"):
        return "ris"
    if fn.endswith((".txt", ".nbib", ".medline")):
        return "medline"
    return "unknown"


def _tokenize(text: str):
    """Yield (tag, value) pairs, merging continuation (indented) lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cur_tag = None
    cur_val: List[str] = []
    for line in text.split("\n"):
        m = _TAG_RE.match(line)
        if m:
            if cur_tag is not None:
                yield cur_tag, " ".join(cur_val).strip()
            cur_tag = m.group(1)
            cur_val = [m.group(2)]
        elif line.strip() and cur_tag is not None and (line.startswith(" ") or line.startswith("\t")):
            cur_val.append(line.strip())  # continuation of previous tag
        else:
            if cur_tag is not None:
                yield cur_tag, " ".join(cur_val).strip()
            cur_tag = None
            cur_val = []
    if cur_tag is not None:
        yield cur_tag, " ".join(cur_val).strip()


def _blank() -> Dict:
    return {"_tags": {}}


def _add(rec: Dict, tag: str, val: str) -> None:
    rec["_tags"].setdefault(tag, []).append(val)


def parse_ris(text: str) -> List[Dict]:
    records: List[Dict] = []
    cur = None
    for tag, val in _tokenize(text):
        if tag == "TY":
            if cur is not None:
                records.append(cur)
            cur = _blank()
            _add(cur, tag, val)
        elif tag == "ER":
            if cur is not None:
                records.append(cur)
            cur = None
        else:
            if cur is None:
                cur = _blank()
            _add(cur, tag, val)
    if cur is not None:
        records.append(cur)
    return [_map_ris(r["_tags"]) for r in records if r["_tags"]]


def parse_medline(text: str) -> List[Dict]:
    # MEDLINE records are separated by blank lines; each begins with PMID-.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n[ \t]*\n", text)
    records = []
    for block in blocks:
        if not block.strip():
            continue
        tags: Dict[str, List[str]] = {}
        for tag, val in _tokenize(block):
            tags.setdefault(tag, []).append(val)
        if tags:
            records.append(_map_medline(tags))
    return records


def _first(tags: Dict, *keys: str) -> str:
    for k in keys:
        vals = tags.get(k)
        if vals:
            for v in vals:
                if v and v.strip():
                    return v.strip()
    return ""


def _map_ris(tags: Dict) -> Dict:
    title = _first(tags, "TI", "T1", "BT")
    abstract = _first(tags, "AB", "N2")
    authors = [normalize_text(a) for a in (tags.get("AU", []) + tags.get("A1", [])) if a.strip()]
    year = year_of(_first(tags, "PY", "Y1", "DA"))
    doi = _first(tags, "DO", "DI")
    if not doi:
        doi = extract_doi(" ".join(tags.get("L3", []) + tags.get("M3", []) + tags.get("N1", []) + tags.get("UR", [])))
    pmid = ""
    accession = _first(tags, "AN")
    db_tag = _first(tags, "DB").lower()
    if accession and re.fullmatch(r"\d{5,9}", accession) and ("pubmed" in db_tag or "medline" in db_tag or not db_tag):
        pmid = accession
    if not pmid:
        pmid = extract_pmid(" ".join(tags.get("N1", []) + tags.get("ID", []) + [accession]))
    raw_id = _first(tags, "ID", "AN")
    return _finalize(title, abstract, authors, year, doi, pmid, raw_id)


def _map_medline(tags: Dict) -> Dict:
    title = _first(tags, "TI")
    abstract = " ".join(tags.get("AB", [])).strip()
    authors = [normalize_text(a) for a in (tags.get("FAU", []) or tags.get("AU", [])) if a.strip()]
    year = year_of(_first(tags, "DP", "DA", "EDAT"))
    doi = ""
    for v in tags.get("AID", []) + tags.get("LID", []):
        if "[doi]" in v.lower():
            doi = extract_doi(v)
            if doi:
                break
    if not doi:
        doi = extract_doi(" ".join(tags.get("AID", []) + tags.get("LID", [])))
    pmid = _first(tags, "PMID")
    return _finalize(title, abstract, authors, year, doi, pmid, pmid)


def _finalize(title, abstract, authors, year, doi, pmid, raw_id) -> Dict:
    from .normalize import normalize_doi
    title = normalize_text(title)
    abstract = normalize_text(abstract)
    first_author = authors[0] if authors else ""
    return {
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "first_author": first_author,
        "year": year,
        "doi": normalize_doi(doi),
        "pmid": (pmid or "").strip(),
        "raw_id": (raw_id or "").strip(),
        "has_abstract": 1 if abstract.strip() else 0,
    }


def parse_file(text: str, filename: str = "", fmt: str | None = None) -> Dict:
    """Parse a file's text. Returns {format, records}."""
    fmt = fmt or sniff_format(text, filename)
    if fmt == "ris":
        recs = parse_ris(text)
    elif fmt == "medline":
        recs = parse_medline(text)
    else:
        # last-ditch: try both, keep whichever finds more records
        ris, med = parse_ris(text), parse_medline(text)
        if len(ris) >= len(med):
            fmt, recs = "ris", ris
        else:
            fmt, recs = "medline", med
    # drop empty shells (no title and no abstract)
    recs = [r for r in recs if r["title"] or r["abstract"]]
    return {"format": fmt, "records": recs}
