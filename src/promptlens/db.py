"""SQLite storage. One local file, WAL mode so concurrent hook calls do not block each other."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
create table if not exists events (
    id integer primary key,
    ts text not null,
    session_id text,
    event text not null,            -- prompt | stop | session_end
    cwd text,
    prompt text,                    -- redacted
    response text,                  -- redacted, only set on stop events
    transcript_path text
);
create index if not exists idx_events_session on events(session_id, id);

create table if not exists turns (
    id integer primary key,
    session_id text not null,
    idx integer not null,
    prev_event_id integer not null,
    next_event_id integer not null,
    prev_prompt text not null,
    response text,
    next_prompt text not null,
    unique (prev_event_id, next_event_id)
);

create table if not exists analyses (
    id integer primary key,
    turn_id integer not null references turns(id),
    model text not null,
    created_at text not null,
    is_iteration integer not null,
    category text not null,
    subcategory text,
    confidence real not null,
    evidence_quote text,
    reasoning text not null,
    suggested_fix text,             -- JSON or null
    unique (turn_id, model)
);
"""


def home_dir() -> Path:
    return Path(os.environ.get("PROMPTLENS_HOME", Path.home() / ".promptlens"))


def db_path() -> Path:
    override = os.environ.get("PROMPTLENS_DB")
    return Path(override) if override else home_dir() / "log.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("pragma journal_mode=wal")
    con.executescript(SCHEMA)
    return con
