"""Turn raw events into (previous prompt, assistant response, next prompt) triples.

A triple is the unit the judge looks at: did the next prompt exist because of the response
to the previous one, and if so, why?
"""

from __future__ import annotations

import itertools
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
    sql = (
        "select coalesce(session_id, 'unknown') sid, id, event, prompt, response from events"
        " where event in ('prompt', 'stop')"
    )
    params: tuple = ()
    if session_id:
        sql += " and coalesce(session_id, 'unknown') = ?"
        params = (session_id,)
    rows = con.execute(sql + " order by sid, id", params).fetchall()

    created = 0
    for sid, group in itertools.groupby(rows, key=lambda r: r["sid"]):
        current: dict | None = None
        idx = 0
        for r in group:
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
