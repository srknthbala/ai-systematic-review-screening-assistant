"""SQLite storage. Everything persists between runs in data/screening.db."""
import sqlite3

from .config import DB_PATH, DEFAULT_MODEL

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  review_type TEXT DEFAULT '',
  question_type TEXT DEFAULT '',
  area_of_research TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS criteria (
  project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  pop_include TEXT DEFAULT '', pop_exclude TEXT DEFAULT '',
  int_include TEXT DEFAULT '', int_exclude TEXT DEFAULT '',
  comp_include TEXT DEFAULT '', comp_exclude TEXT DEFAULT '',
  out_include TEXT DEFAULT '', out_exclude TEXT DEFAULT '',
  study_include TEXT DEFAULT '', study_exclude TEXT DEFAULT '',
  other_include TEXT DEFAULT '', other_exclude TEXT DEFAULT '',
  exclusion_reasons TEXT DEFAULT '[]',
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  title TEXT DEFAULT '',
  abstract TEXT DEFAULT '',
  authors TEXT DEFAULT '',
  first_author TEXT DEFAULT '',
  year TEXT DEFAULT '',
  doi TEXT DEFAULT '',
  pmid TEXT DEFAULT '',
  source_database TEXT DEFAULT '',
  raw_id TEXT DEFAULT '',
  norm_title TEXT DEFAULT '',
  has_abstract INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,           -- 1 = surviving unique record, 0 = merged away
  merged_into INTEGER,                -- id of surviving record this was merged into
  dedup_method TEXT,                  -- doi | pmid | fuzzy
  import_batch TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_records_project ON records(project_id);
CREATE INDEX IF NOT EXISTS idx_records_doi ON records(project_id, doi);
CREATE INDEX IF NOT EXISTS idx_records_pmid ON records(project_id, pmid);
CREATE INDEX IF NOT EXISTS idx_records_active ON records(project_id, active);

CREATE TABLE IF NOT EXISTS merge_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kept_id INTEGER,
  dropped_id INTEGER,
  method TEXT,                        -- doi | pmid | fuzzy
  similarity REAL,
  status TEXT DEFAULT 'merged',       -- merged | pending_review | split
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS screening_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
  decision TEXT,                      -- INCLUDE | EXCLUDE | MAYBE
  confidence REAL,
  reason TEXT,
  exclusion_reason_category TEXT,
  tags TEXT DEFAULT '[]',
  model TEXT,
  run_type TEXT,                      -- test | batch
  raw_response TEXT,
  error TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(project_id, record_id)
);
CREATE INDEX IF NOT EXISTS idx_results_project ON screening_results(project_id);

CREATE TABLE IF NOT EXISTS batch_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  batch_id TEXT,                      -- Anthropic message batch id
  status TEXT,                        -- in_progress | ended | canceled | error
  model TEXT,
  record_count INTEGER DEFAULT 0,
  result_count INTEGER DEFAULT 0,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_batch_project ON batch_jobs(project_id);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Default rollback journal: portable across filesystems. Per-record commits
    # give crash durability, which is what matters for resumable screening.
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES ('model', ?)",
            (DEFAULT_MODEL,),
        )
        conn.commit()


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
