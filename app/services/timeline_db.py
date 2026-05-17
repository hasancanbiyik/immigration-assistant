"""
Timeline Events — SQLite Persistence Layer
===========================================

Tier 1 of a two-step migration to consolidate persistence:

  Tier 1 (this module): move timeline events out of the in-memory `_timelines`
    dict and into SQLite. Same DB file as rfe_db so a future migration can
    introduce a shared client identity.

  Tier 2 (planned, NOT implemented here): add a `clients(id, name, ...)` table.
    Replace `client_key` below with `client_id TEXT NOT NULL REFERENCES
    clients(id) ON DELETE CASCADE`. Do the same in rfe_cases. The Doc Q&A
    panel's localStorage client list moves server-side. A "Client Workspace"
    view aggregates documents + timeline + RFE cases per client.

  See the architectural critique in commit message / README for why Tier 2
  matters: without it, the same human ("John Smith") exists as three
  independent records across Doc Q&A, Timeline, and RFE Tracker.

Storage notes
-------------
- Shares the SQLite file with rfe_db (single connection helper, single file).
- `client_key` is the lowercased + stripped client name. This preserves the
  pre-migration behavior where `_timelines["john smith"]` and
  `_timelines["John Smith"]` collapsed into the same bucket. It's a string
  for now — Tier 2 will replace it with `client_id`.
- WAL mode is on for concurrent reads with serialized writes (matches rfe_db).
"""

import sqlite3
import uuid
from datetime import datetime
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

# Shared with rfe_db — same SQLite file, different tables. `APP_DB_PATH`
# is the preferred env var going forward; `RFE_DB_PATH` is honored as a
# fallback for any deployment set up before this consolidation.
DB_PATH = (
    os.getenv("APP_DB_PATH")
    or os.getenv("RFE_DB_PATH")
    or "./data/app.db"
)


# ─── Connection helper ────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─── Schema init ──────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create the timeline_events table if it doesn't exist. Safe to call on
    every startup (idempotent). Called from app.main during lifespan setup.
    """
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS timeline_events (
                id              TEXT PRIMARY KEY,

                -- Tier 2 will replace this column with:
                --   client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE
                -- For now: lowercased+stripped client name, no referential integrity.
                client_key      TEXT NOT NULL,

                event_type      TEXT NOT NULL,
                event_date      TEXT,            -- free-form: "03/15/2026" or "March 15, 2026"
                description     TEXT NOT NULL,
                receipt_number  TEXT,
                form_type       TEXT,
                source_document TEXT DEFAULT 'manual_entry',
                created_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_timeline_events_client_key
                ON timeline_events(client_key);
        """)
    logger.info(f"✅ Timeline events table ready at {DB_PATH}")


# ─── Row -> dict ──────────────────────────────────────────────────────

def _row_to_event(row: sqlite3.Row) -> dict:
    """Convert a DB row to a TimelineEvent-shaped dict (matches Pydantic schema)."""
    return {
        "event_type":      row["event_type"],
        "date":            row["event_date"],   # schema uses `date`; column is `event_date`
        "description":     row["description"],
        "receipt_number":  row["receipt_number"],
        "form_type":       row["form_type"],
        "source_document": row["source_document"],
    }


# ─── CRUD ─────────────────────────────────────────────────────────────

def add_event(
    client_name: str,
    event_type: str,
    description: str,
    date: Optional[str] = None,
    receipt_number: Optional[str] = None,
    form_type: Optional[str] = None,
    source_document: str = "manual_entry",
) -> dict:
    """
    Insert a manual timeline event for a client. Returns the stored event
    (the dict shape matches the TimelineEvent Pydantic schema, so the router
    can return it directly).
    """
    event_id   = str(uuid.uuid4())
    now        = datetime.utcnow().isoformat()
    client_key = client_name.lower().strip()

    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO timeline_events
               (id, client_key, event_type, event_date, description,
                receipt_number, form_type, source_document, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (event_id, client_key, event_type, date, description,
             receipt_number, form_type, source_document, now),
        )
        row = conn.execute(
            "SELECT * FROM timeline_events WHERE id = ?", (event_id,)
        ).fetchone()
    return _row_to_event(row)


def get_events_for_client(client_name: str) -> list[dict]:
    """
    Return all events for a client, sorted by event_date (nulls last), then
    by insertion order. Matches the previous in-memory sort behavior:
    `key=lambda e: e.date or "9999-99-99"`.
    """
    client_key = client_name.lower().strip()
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM timeline_events
               WHERE client_key = ?
               ORDER BY
                 CASE WHEN event_date IS NULL OR event_date = '' THEN 1 ELSE 0 END,
                 event_date,
                 created_at""",
            (client_key,),
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def clear_all_events() -> None:
    """
    Wipe every timeline event. Used by the test fixture for per-test isolation.
    Intentionally NOT exposed via an API endpoint — there's no legitimate
    user-facing reason to wipe everyone's timeline at once.
    """
    with _get_conn() as conn:
        conn.execute("DELETE FROM timeline_events")
