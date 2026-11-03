"""Turn raw events into (previous prompt, assistant response, next prompt) triples.

A triple is the unit the judge looks at: did the next prompt exist because of the response
to the previous one, and if so, why?
"""

from __future__ import annotations

import re
import sqlite3

_CONFIRMATION = re.compile(
    r"(?i)(ok(ay)?|danke|thanks?|thx|passt|perfekt|super|gut|yes|ja|lgtm|looks good|great)[\s.!]*"
)


def looks_like_confirmation(text: str) -> bool:
    t = text.strip()
    return len(t) <= 30 and bool(_CONFIRMATION.fullmatch(t))


def build_turns(con: sqlite3.Connection, session_id: str | None = None) -> int:
    """Create missing turn rows. Returns the number of new turns."""
    if session_id:
        sessions = [session_id]
    else:
        rows = con.execute("select distinct coalesce(session_id, 'unknown') s from events").fetchall()
        sessions = [r["s"] for r in rows]

    created = 0
    for sid in sessions:
        rows = con.execute(
            "select id, event, prompt, response from events"
            " where coalesce(session_id, 'unknown') = ? and event in ('prompt', 'stop')"
            " order by id",
            (sid,),
        ).fetchall()

        current: dict | None = None
        idx = 0
        for r in rows:
            if r["event"] == "prompt":
                if current is not None:
                    cur = con.execute(
                        "insert or ignore into turns(session_id, idx, prev_event_id, next_event_id,"
                        " prev_prompt, response, next_prompt) values (?,?,?,?,?,?,?)",
                        (sid, idx, current["id"], r["id"], current["prompt"], current["response"], r["prompt"]),
                    )
                    created += cur.rowcount
                    idx += 1
                current = {"id": r["id"], "prompt": r["prompt"], "response": None}
            elif current is not None and r["response"]:
                current["response"] = r["response"]  # last stop before the next prompt wins
    con.commit()
    return created
