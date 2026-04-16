"""
RFE Tracker — SQLite Persistence Layer
=======================================
Manages RFE cases and per-case issue checklists.

Storage: ./data/rfe_tracker.db (single file, zero infrastructure)
Tables:
  - rfe_cases   : one row per RFE case (client, deadline, status, etc.)
  - rfe_issues  : checklist items scoped to a case via case_id FK

Design notes:
  - Issues are always fetched via case_id — they can never leak across cases.
  - days_remaining is computed at read time (not stored) so it stays accurate.
  - WAL mode + foreign keys enabled on every connection.
"""

import sqlite3
import uuid
from datetime import datetime, date, timedelta
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("RFE_DB_PATH", "./data/rfe_tracker.db")
RFE_DEFAULT_RESPONSE_DAYS = 87  # Standard USCIS RFE response window


# ─── Connection helper ────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─── Schema init ──────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rfe_cases (
                id                TEXT PRIMARY KEY,
                client_name       TEXT NOT NULL,
                case_type         TEXT,
                receipt_number    TEXT,
                service_center    TEXT,
                rfe_issue_date    TEXT,
                response_deadline TEXT,
                status            TEXT NOT NULL DEFAULT 'open',
                notes             TEXT DEFAULT '',
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rfe_issues (
                id          TEXT PRIMARY KEY,
                case_id     TEXT NOT NULL REFERENCES rfe_cases(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                description TEXT DEFAULT '',
                completed   INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            );
        """)
    logger.info(f"✅ RFE database ready at {DB_PATH}")


# ─── Internal helpers ─────────────────────────────────────────────────

def _row_to_case(row: sqlite3.Row) -> dict:
    """Convert a DB row to a dict, adding computed days_remaining."""
    d = dict(row)
    deadline = d.get("response_deadline")
    if deadline:
        try:
            d["days_remaining"] = (date.fromisoformat(deadline) - date.today()).days
        except ValueError:
            d["days_remaining"] = None
    else:
        d["days_remaining"] = None
    return d


# ─── Case CRUD ────────────────────────────────────────────────────────

def create_case(
    client_name: str,
    case_type: Optional[str] = None,
    receipt_number: Optional[str] = None,
    service_center: Optional[str] = None,
    rfe_issue_date: Optional[str] = None,
    response_deadline: Optional[str] = None,
    notes: str = "",
) -> dict:
    """Create a new RFE case. Auto-calculates deadline (+87 days) if not provided."""
    now = datetime.utcnow().isoformat()
    case_id = str(uuid.uuid4())

    # Auto-calculate response deadline from issue date if not explicitly set
    if not response_deadline and rfe_issue_date:
        try:
            dl = date.fromisoformat(rfe_issue_date) + timedelta(days=RFE_DEFAULT_RESPONSE_DAYS)
            response_deadline = dl.isoformat()
        except ValueError:
            pass

    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO rfe_cases
               (id, client_name, case_type, receipt_number, service_center,
                rfe_issue_date, response_deadline, status, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (case_id, client_name, case_type, receipt_number, service_center,
             rfe_issue_date, response_deadline, "open", notes, now, now),
        )
        row = conn.execute("SELECT * FROM rfe_cases WHERE id=?", (case_id,)).fetchone()
    return _row_to_case(row)


def list_cases(client_name: Optional[str] = None) -> list[dict]:
    """
    List cases sorted by response deadline (most urgent first).
    Nulls (no deadline set) appear last.
    """
    with _get_conn() as conn:
        if client_name:
            rows = conn.execute(
                """SELECT * FROM rfe_cases
                   WHERE client_name = ?
                   ORDER BY
                     CASE WHEN response_deadline IS NULL THEN 1 ELSE 0 END,
                     response_deadline ASC""",
                (client_name,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM rfe_cases
                   ORDER BY
                     CASE WHEN response_deadline IS NULL THEN 1 ELSE 0 END,
                     response_deadline ASC"""
            ).fetchall()
    return [_row_to_case(r) for r in rows]


def get_case(case_id: str) -> Optional[dict]:
    """Fetch a single case with its issues list."""
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM rfe_cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            return None
        case = _row_to_case(row)
        # Issues are always scoped to this case_id — no cross-case leakage possible
        issues = conn.execute(
            "SELECT * FROM rfe_issues WHERE case_id=? ORDER BY created_at ASC",
            (case_id,),
        ).fetchall()
        case["issues"] = [dict(i) for i in issues]
    return case


def update_case(case_id: str, **fields) -> Optional[dict]:
    """Partially update a case. Only whitelisted fields are accepted."""
    allowed = {
        "client_name", "case_type", "receipt_number", "service_center",
        "rfe_issue_date", "response_deadline", "status", "notes",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_case(case_id)

    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [case_id]

    with _get_conn() as conn:
        conn.execute(f"UPDATE rfe_cases SET {set_clause} WHERE id=?", values)

    return get_case(case_id)


def delete_case(case_id: str) -> bool:
    """Delete a case (cascades to its issues)."""
    with _get_conn() as conn:
        result = conn.execute("DELETE FROM rfe_cases WHERE id=?", (case_id,))
    return result.rowcount > 0


# ─── Issue CRUD ───────────────────────────────────────────────────────

def add_issue(case_id: str, title: str, description: str = "") -> Optional[dict]:
    """Add a checklist item to a case. Returns None if case doesn't exist."""
    # Verify the case exists before adding an issue to it
    with _get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM rfe_cases WHERE id=?", (case_id,)
        ).fetchone()
        if not exists:
            return None

        now = datetime.utcnow().isoformat()
        issue_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO rfe_issues (id, case_id, title, description, completed, created_at)
               VALUES (?,?,?,?,0,?)""",
            (issue_id, case_id, title, description, now),
        )
        row = conn.execute("SELECT * FROM rfe_issues WHERE id=?", (issue_id,)).fetchone()
    return dict(row)


def update_issue(issue_id: str, **fields) -> Optional[dict]:
    """Update an issue's title, description, or completed state."""
    allowed = {"title", "description", "completed"}
    updates = {k: v for k, v in fields.items() if k in allowed}

    with _get_conn() as conn:
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            values = list(updates.values()) + [issue_id]
            conn.execute(f"UPDATE rfe_issues SET {set_clause} WHERE id=?", values)
        row = conn.execute("SELECT * FROM rfe_issues WHERE id=?", (issue_id,)).fetchone()
    return dict(row) if row else None


def delete_issue(issue_id: str) -> bool:
    with _get_conn() as conn:
        result = conn.execute("DELETE FROM rfe_issues WHERE id=?", (issue_id,))
    return result.rowcount > 0
