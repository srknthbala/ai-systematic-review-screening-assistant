"""Screening engine tests with an injected fake Anthropic client.
Run: python tests/test_screen.py"""
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SCREENING_DB_PATH"] = os.path.join(tempfile.gettempdir(), "screening_screen_test.db")
for ext in ("", "-journal"):
    try:
        os.remove(os.environ["SCREENING_DB_PATH"] + ext)
    except OSError:
        pass

from app import config, db                                  # noqa: E402
from app.services import anthropic_client, batches, importer, ris_parser, screener  # noqa: E402

PASS, FAIL = 0, 0
def check(label, cond):
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(("  ok   " if cond else "  FAIL ") + label)

GOOD = '{"decision":"INCLUDE","confidence":0.91,"reason":"meets criteria","exclusion_reason_category":null,"tags":["Spasticity present"]}'

class FBlock:
    def __init__(self, text): self.text = text
class FMsg:
    def __init__(self, text): self.content = [FBlock(text)]
class FakeMessages:
    def __init__(self): self.calls = []; self.attempts = {}
    def create(self, model=None, max_tokens=0, temperature=0, system=None, messages=None):
        self.calls.append({"system": system, "messages": messages})
        c = messages[0]["content"]
        if "RAISE_API" in c:
            raise RuntimeError("429 rate limit")
        if "ALWAYS_BAD" in c:
            return FMsg("this is not json")
        if "MALFORMED_ONCE" in c:
            self.attempts["m"] = self.attempts.get("m", 0) + 1
            return FMsg("oops" if self.attempts["m"] == 1 else GOOD)
        if "FENCE_ME" in c:
            return FMsg("```json\n" + GOOD + "\n```")
        if "(none provided" in c:
            return FMsg('{"decision":"MAYBE","confidence":0.4,"reason":"no abstract","exclusion_reason_category":null,"tags":[]}')
        return FMsg(GOOD)
class FakeReqCounts:
    def __init__(self, n): self.succeeded = n; self.errored = 0; self.canceled = 0; self.expired = 0; self.processing = 0
class FakeBatches:
    def __init__(self): self.last = []
    def create(self, requests=None): self.last = requests; return types.SimpleNamespace(id="batch_test_1")
    def retrieve(self, bid): return types.SimpleNamespace(processing_status="ended", request_counts=FakeReqCounts(len(self.last)))
    def results(self, bid):
        for r in self.last:
            yield types.SimpleNamespace(custom_id=r["custom_id"],
                result=types.SimpleNamespace(type="succeeded",
                    message=FMsg('{"decision":"EXCLUDE","confidence":0.8,"reason":"animal study","exclusion_reason_category":"Animal study","tags":[]}')))
    def cancel(self, bid): return types.SimpleNamespace(id=bid)
class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()
        self.messages.batches = FakeBatches()

FAKE = FakeClient()

print("\n== parse_response robustness ==")
check("plain json", screener.parse_response(GOOD)["decision"] == "INCLUDE")
check("code-fenced", screener.parse_response("```json\n" + GOOD + "\n```")["decision"] == "INCLUDE")
check("prose-wrapped", screener.parse_response("Here:\n" + GOOD + "\nThanks")["decision"] == "INCLUDE")

print("\n== normalize_result ==")
try:
    screener.normalize_result({"decision": "NOPE"}, [], "")
    check("invalid decision raises", False)
except ValueError:
    check("invalid decision raises", True)
r = screener.normalize_result({"decision": "exclude", "confidence": 5, "reason": "x", "exclusion_reason_category": "wrong POPULATION", "tags": "Spasticity present"}, ["Wrong population", "Animal study"], "")
check("confidence clamped to 1.0", r["confidence"] == 1.0)
check("category mapped verbatim (case-insensitive)", r["exclusion_reason_category"] == "Wrong population")
check("tags coerced to list", r["tags"] == ["Spasticity present"])
r2 = screener.normalize_result({"decision": "INCLUDE", "confidence": 0.7, "exclusion_reason_category": "Wrong population"}, ["Wrong population"], "")
check("INCLUDE forces null category", r2["exclusion_reason_category"] is None)
r3 = screener.normalize_result({"decision": "EXCLUDE", "confidence": 0.7, "exclusion_reason_category": "Not in list"}, ["Wrong population"], "")
check("non-member category -> null", r3["exclusion_reason_category"] is None)
r4 = screener.normalize_result({"decision": "EXCLUDE", "confidence": 0.7, "exclusion_reason_category": "anything"}, [], "")
check("empty reason list -> null category", r4["exclusion_reason_category"] is None)

print("\n== screen_one (fake client) ==")
sysblocks = anthropic_client.system_blocks("CRITERIA TEXT HERE")
check("system has 2 blocks", len(sysblocks) == 2)
check("criteria block is cache-flagged", sysblocks[1].get("cache_control") == {"type": "ephemeral"})
FAKE.messages.calls.clear()
out = screener.screen_one(FAKE, "m", sysblocks, {"title": "FENCE_ME study", "abstract": "abc"}, [])
check("fenced output parsed", out["decision"] == "INCLUDE")
FAKE.messages.calls.clear()
out = screener.screen_one(FAKE, "m", sysblocks, {"title": "MALFORMED_ONCE study", "abstract": "abc"}, [])
check("retry-once recovers", out["decision"] == "INCLUDE" and len(FAKE.messages.calls) == 2)
FAKE.messages.calls.clear()
out = screener.screen_one(FAKE, "m", sysblocks, {"title": "ALWAYS_BAD study", "abstract": "abc"}, [])
check("malformed twice -> MAYBE+error", out["decision"] == "MAYBE" and out["error"] == "json_parse_failed" and len(FAKE.messages.calls) == 2)
try:
    screener.screen_one(FAKE, "m", sysblocks, {"title": "RAISE_API study", "abstract": "abc"}, [])
    check("API error propagates", False)
except RuntimeError:
    check("API error propagates", True)

# inject fake client into the routers/services and spin up the app
import app.routers.screen as screen_mod   # noqa: E402
import app.services.batches as batch_mod  # noqa: E402
screen_mod.get_client = lambda: FAKE
batch_mod.get_client = lambda: FAKE
config.set_api_key("sk-ant-dummy-key-for-tests")

from fastapi.testclient import TestClient  # noqa: E402
import warnings; warnings.filterwarnings("ignore")
c = TestClient(__import__("app.main", fromlist=["app"]).app)

print("\n== Mode A: synchronous test run (HTTP) ==")
pid = c.post("/api/projects", json={"name": "Screen Test"}).json()["project"]["id"]
c.put("/api/criteria", json={"project_id": pid, "pop_include": "adult humans with stroke", "pop_exclude": "animals, children"})
FIX = ROOT / "tests" / "fixtures"
with db.get_conn() as conn:
    for fn, src in [("pubmed_results.txt", "PubMed"), ("embase.ris", "Embase"), ("scopus.ris", "Scopus"), ("cochrane.ris", "Cochrane CENTRAL")]:
        parsed = ris_parser.parse_file((FIX / fn).read_text(encoding="utf-8"), fn)
        importer.insert_records(conn, pid, parsed["records"], src, "b1")
    from app.services import dedup
    dedup.deduplicate(conn, pid)

st = c.get(f"/api/screen/status?project_id={pid}").json()
check("status reports unscreened>0", st["unscreened"] > 0 and st["api_key_set"])
total_unique = st["total_unique"]
FAKE.messages.calls.clear()
r = c.post("/api/screen/test", json={"project_id": pid, "sample_size": 4})
check("test run starts", r.status_code == 200 and r.json()["total"] == 4)
for _ in range(50):
    prog = c.get(f"/api/screen/test/progress?project_id={pid}").json()
    if not prog["running"]:
        break
    time.sleep(0.1)
check("test run completed 4", prog["done"] == 4 and not prog["running"] and not prog["error"])
check("results returned with decisions", len(prog["results"]) == 4 and all(x["decision"] in ("INCLUDE", "EXCLUDE", "MAYBE") for x in prog["results"]))

# INDEPENDENCE: every call had exactly one user message, identical system blocks, one TITLE each
calls = FAKE.messages.calls
check("each call has a single user message", all(len(cl["messages"]) == 1 and cl["messages"][0]["role"] == "user" for cl in calls))
check("no cross-record leakage (one TITLE per call)", all(cl["messages"][0]["content"].count("TITLE:") == 1 for cl in calls))
check("identical cached system block across calls", len({id(cl["system"]) for cl in calls}) == 1 or all(cl["system"] == calls[0]["system"] for cl in calls))

# re-run skips already screened
st2 = c.get(f"/api/screen/status?project_id={pid}").json()
check("unscreened decreased by 4", st2["unscreened"] == st["unscreened"] - 4)

print("\n== Mode B: batch (HTTP) ==")
sub = c.post("/api/screen/batch", json={"project_id": pid}).json()
check("batch submitted with remaining unscreened", sub["count"] == st2["unscreened"])
stx = c.get(f"/api/screen/status?project_id={pid}").json()
check("active batch in_progress", stx["active_batch"] and stx["active_batch"]["status"] == "in_progress")
bs = c.get(f"/api/screen/batch/status?project_id={pid}").json()
check("batch status flips to ended", bs["active_batch"]["status"] == "ended")
st3 = c.get(f"/api/screen/status?project_id={pid}").json()
check("all records now screened", st3["unscreened"] == 0)
# re-poll is a no-op (job already ended, not active)
bs2 = c.get(f"/api/screen/batch/status?project_id={pid}").json()
check("ended batch no longer active", bs2["active_batch"] is None)

try:
    os.remove(ROOT / "secrets.local.json")
except OSError:
    pass
print(f"\n==== {PASS} passed, {FAIL} failed ====")
sys.exit(1 if FAIL else 0)
