"""Results + CSV export integration test (content-aware fake). Run: python tests/test_results.py"""
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SCREENING_DB_PATH"] = os.path.join(tempfile.gettempdir(), "screening_results_test.db")
for ext in ("", "-journal"):
    try:
        os.remove(os.environ["SCREENING_DB_PATH"] + ext)
    except OSError:
        pass

from app import config, db                                   # noqa: E402
from app.services import dedup, importer, ris_parser         # noqa: E402

PASS, FAIL = 0, 0
def check(label, cond):
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(("  ok   " if cond else "  FAIL ") + label)


class FBlock:
    def __init__(self, t): self.text = t
class FMsg:
    def __init__(self, t): self.content = [FBlock(t)]
class FakeMessages:
    def create(self, model=None, max_tokens=0, temperature=0, system=None, messages=None):
        c = messages[0]["content"].lower()
        if "(none provided" in c:
            return FMsg('{"decision":"MAYBE","confidence":0.4,"reason":"no abstract to judge","exclusion_reason_category":null,"tags":[]}')
        if "tens" in c:
            return FMsg('{"decision":"EXCLUDE","confidence":0.92,"reason":"sensory TENS only","exclusion_reason_category":"Sensory-level TENS only","tags":[]}')
        if "vibration" in c or "palsy" in c:
            return FMsg('{"decision":"EXCLUDE","confidence":0.8,"reason":"wrong population","exclusion_reason_category":"Wrong population","tags":["Spasticity present"]}')
        if "blood flow" in c:
            return FMsg('{"decision":"INCLUDE","confidence":0.7,"reason":"BFR relevant","exclusion_reason_category":null,"tags":["Confound: BFR"]}')
        return FMsg('{"decision":"INCLUDE","confidence":0.9,"reason":"meets criteria","exclusion_reason_category":null,"tags":[]}')
class FakeClient:
    def __init__(self): self.messages = FakeMessages()

FAKE = FakeClient()
import app.routers.screen as screen_mod  # noqa: E402
screen_mod.get_client = lambda: FAKE
config.set_api_key("sk-ant-dummy")

import warnings; warnings.filterwarnings("ignore")
from fastapi.testclient import TestClient  # noqa: E402
c = TestClient(__import__("app.main", fromlist=["app"]).app)

pid = c.post("/api/projects", json={"name": "Results Test"}).json()["project"]["id"]
c.put("/api/criteria", json={"project_id": pid, "pop_include": "adult stroke survivors",
      "pop_exclude": "animals, children, healthy volunteers",
      "exclusion_reasons": ["Wrong population", "Sensory-level TENS only", "Animal study"]})
FIX = ROOT / "tests" / "fixtures"
with db.get_conn() as conn:
    for fn, src in [("pubmed_results.txt", "PubMed"), ("embase.ris", "Embase"), ("scopus.ris", "Scopus"), ("cochrane.ris", "Cochrane CENTRAL")]:
        parsed = ris_parser.parse_file((FIX / fn).read_text(encoding="utf-8"), fn)
        importer.insert_records(conn, pid, parsed["records"], src, "b1")
    dedup.deduplicate(conn, pid)

unique = c.get(f"/api/screen/status?project_id={pid}").json()["total_unique"]
c.post("/api/screen/test", json={"project_id": pid, "sample_size": unique})
for _ in range(80):
    if not c.get(f"/api/screen/test/progress?project_id={pid}").json()["running"]:
        break
    time.sleep(0.1)

print("\n== Results meta ==")
meta = c.get(f"/api/results/meta?project_id={pid}").json()
sm = meta["summary"]
print("  summary:", {k: sm[k] for k in ("INCLUDE", "EXCLUDE", "MAYBE", "total")})
check("all unique screened", sm["total"] == unique)
check("has INCLUDE + EXCLUDE + MAYBE", sm["INCLUDE"] > 0 and sm["EXCLUDE"] > 0 and sm["MAYBE"] >= 1)
check("by_category populated", "Wrong population" in sm["by_category"])
check("categories listed", "Wrong population" in meta["categories"])
check("tags listed", "Spasticity present" in meta["tags"])

print("\n== Filters ==")
only_exc = c.get(f"/api/results?project_id={pid}&decision=EXCLUDE").json()["rows"]
check("decision filter", all(r["decision"] == "EXCLUDE" for r in only_exc) and only_exc)
by_cat = c.get(f"/api/results?project_id={pid}&category=Wrong population").json()["rows"]
check("category filter", all(r["exclusion_reason_category"] == "Wrong population" for r in by_cat) and by_cat)
by_tag = c.get(f"/api/results?project_id={pid}&tag=Spasticity present").json()["rows"]
check("tag filter", all("Spasticity present" in r["tags"] for r in by_tag) and by_tag)
no_abs = c.get(f"/api/results?project_id={pid}&has_abstract=0").json()["rows"]
check("has_abstract filter -> MAYBE no-abstract", no_abs and all(r["has_abstract"] == 0 for r in no_abs))

print("\n== Provenance + ordering ==")
allrows = c.get(f"/api/results?project_id={pid}").json()["rows"]
merged = [r for r in allrows if set(r["source_databases"]) == {"PubMed", "Embase"}]
check("merged record shows both sources", len(merged) == 1)
order_ok = [{"INCLUDE": 0, "MAYBE": 1, "EXCLUDE": 2}[r["decision"]] for r in allrows]
check("rows ordered include->maybe->exclude", order_ok == sorted(order_ok))

print("\n== CSV export ==")
resp = c.get(f"/api/results/export.csv?project_id={pid}")
check("csv content-type", resp.headers["content-type"].startswith("text/csv"))
check("csv attachment header", "attachment" in resp.headers.get("content-disposition", ""))
lines = resp.text.strip().splitlines()
check("csv header correct", lines[0].startswith("title,year,source_databases,decision,confidence,reason"))
check("csv row count == screened", len(lines) - 1 == unique)
check("csv filter applies", len(c.get(f"/api/results/export.csv?project_id={pid}&decision=EXCLUDE").text.strip().splitlines()) - 1 == sm["EXCLUDE"])

try:
    os.remove(ROOT / "secrets.local.json")
except OSError:
    pass
print(f"\n==== {PASS} passed, {FAIL} failed ====")
sys.exit(1 if FAIL else 0)
