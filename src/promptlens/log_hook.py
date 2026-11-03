"""Copilot hook entrypoint: append one row per prompt / stop event to the local DB.

Design rules:
- Never fail and never print to stdout: a broken logger must not disturb the agent.
- Redact before writing.
- No model calls here. Analysis runs later as a batch (see cli.py).

Payloads differ slightly between Copilot CLI (camelCase) and the VS Code format
(snake_case), so both spellings are accepted. The event name can be passed with --event
or is read from `hook_event_name`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import traceback
from pathlib import Path
from typing import Any

from . import db
from .redact import load_terms, redact

MAX_RESPONSE_CHARS = 20_000
MAX_TRANSCRIPT_BYTES = 2_000_000

_EVENT_MAP = {
    "userpromptsubmit": "prompt",
    "userpromptsubmitted": "prompt",
    "stop": "stop",
    "agentstop": "stop",
    "sessionend": "session_end",
}


def canonical_event(name: str | None) -> str | None:
    if not name:
        return None
    return _EVENT_MAP.get(re.sub(r"[^a-z]", "", name.lower()))


def _iso(ts: Any) -> str:
    if ts is None:
        return dt.datetime.now(dt.timezone.utc).isoformat()
    if isinstance(ts, (int, float)):
        seconds = ts / 1000 if ts > 1e11 else ts
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()
    return str(ts)


# --- transcript parsing -------------------------------------------------------------
# The transcript format is not a stable API, so everything here is best effort.


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(t for t in (_text_of(c) for c in content) if t)
    if isinstance(content, dict):
        for key in ("text", "content", "message"):
            if key in content:
                t = _text_of(content[key])
                if t:
                    return t
    return ""


def _is_assistant(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    for key in ("role", "type", "sender"):
        v = obj.get(key)
        if isinstance(v, str) and "assistant" in v.lower():
            return True
    for key in ("message", "data"):
        if isinstance(obj.get(key), dict) and _is_assistant(obj[key]):
            return True
    return False


def _assistant_text(obj: dict) -> str:
    paths = (
        ("content",),
        ("message", "content"),
        ("data", "content"),
        ("text",),
        ("message", "text"),
        ("data", "text"),
    )
    for path in paths:
        cur: Any = obj
        for p in path:
            cur = cur.get(p) if isinstance(cur, dict) else None
        text = _text_of(cur).strip()
        if text:
            return text
    return ""


def last_assistant_text(path: str) -> str | None:
    try:
        p = Path(path).expanduser()
        size = p.stat().st_size
        with p.open("rb") as f:
            if size > MAX_TRANSCRIPT_BYTES:
                f.seek(size - MAX_TRANSCRIPT_BYTES)
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    items: list[Any] = []
    stripped = data.lstrip()
    if stripped.startswith("["):
        try:
            items = json.loads(stripped)
        except ValueError:
            items = []
    else:
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except ValueError:
                continue  # also covers a partial first line after seeking

    for obj in reversed(items):
        if _is_assistant(obj):
            text = _assistant_text(obj)
            if text:
                return text
    return None


# --- core ---------------------------------------------------------------------------


def normalize(payload: dict, event_name: str | None = None) -> dict | None:
    event = canonical_event(event_name) or canonical_event(payload.get("hook_event_name"))
    if event is None:
        return None

    def g(*keys: str) -> Any:
        return next((payload[k] for k in keys if payload.get(k) is not None), None)

    terms = load_terms()
    record: dict[str, Any] = {
        "ts": _iso(g("timestamp")),
        "session_id": g("session_id", "sessionId"),
        "event": event,
        "cwd": g("cwd"),
        "prompt": None,
        "response": None,
        "transcript_path": g("transcript_path", "transcriptPath"),
    }
    if event == "prompt":
        prompt = g("prompt")
        if not prompt:
            return None
        record["prompt"] = redact(str(prompt), terms)
    elif event == "stop" and record["transcript_path"]:
        text = last_assistant_text(str(record["transcript_path"]))
        if text:
            record["response"] = redact(text[:MAX_RESPONSE_CHARS], terms)
    return record


def store(record: dict, con: sqlite3.Connection | None = None) -> None:
    own = con is None
    con = con or db.connect()
    try:
        con.execute(
            "insert into events(ts, session_id, event, cwd, prompt, response, transcript_path)"
            " values (:ts, :session_id, :event, :cwd, :prompt, :response, :transcript_path)",
            record,
        )
        con.commit()
    finally:
        if own:
            con.close()


def handle_payload(raw: str, event_name: str | None = None) -> dict | None:
    dump = os.environ.get("PROMPTLENS_DUMP")
    if dump:  # format discovery: appends the raw, unredacted payload to this file
        with open(dump, "a", encoding="utf-8") as f:
            f.write(raw.strip() + "\n")
    payload = json.loads(raw) if raw.strip() else {}
    record = normalize(payload, event_name)
    if record:
        store(record)
    return record


def _log_error() -> None:
    try:
        path = db.home_dir() / "hook_errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat()}\n{traceback.format_exc()}\n")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        ap = argparse.ArgumentParser(prog="promptlens-hook")
        ap.add_argument("--event", help="UserPromptSubmit | Stop | SessionEnd")
        args = ap.parse_args(argv)
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        handle_payload(raw, args.event)
    except BaseException:
        _log_error()
    return 0


if __name__ == "__main__":
    sys.exit(main())
