"""Batch judge: classify every pending turn and store the result.

The backend is a plain callable, so tests and other providers can plug in without changes.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
from typing import Callable

from . import schema
from .redact import load_terms, redact
from .segment import looks_like_confirmation

# (system_prompt, user_message, model) -> dict that matches RESULT_SCHEMA
Backend = Callable[[str, str, str], dict]


def openai_backend(system: str, user: str, model: str) -> dict:
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Install the OpenAI extra: pip install -e '.[openai]'") from e

    kwargs: dict = {}
    if os.environ.get("PROMPTLENS_TEMPERATURE"):  # some models reject the parameter, so it is opt-in
        kwargs["temperature"] = float(os.environ["PROMPTLENS_TEMPERATURE"])
    resp = OpenAI().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": schema.RESULT_SCHEMA},
        **kwargs,
    )
    return json.loads(resp.choices[0].message.content)


def _result(**overrides) -> dict:
    return {
        "reasoning": "",
        "is_iteration": False,
        "category": "none",
        "subcategory": None,
        "confidence": 1.0,
        "evidence_quote": None,
        "suggested_fix": None,
        **overrides,
    }


def dry_run_backend(system: str, user: str, model: str) -> dict:
    """No network. Lets you test the whole pipeline end to end."""
    return _result(reasoning="dry-run", is_iteration=True, category="unclear", confidence=0.0)


def _store(con: sqlite3.Connection, turn_id: int, model: str, r: dict) -> None:
    fix = json.dumps(r["suggested_fix"]) if r["suggested_fix"] else None
    con.execute(
        "insert or replace into analyses(turn_id, model, created_at, is_iteration, category,"
        " subcategory, confidence, evidence_quote, reasoning, suggested_fix)"
        " values (?,?,?,?,?,?,?,?,?,?)",
        (
            turn_id,
            model,
            dt.datetime.now(dt.timezone.utc).isoformat(),
            int(r["is_iteration"]),
            r["category"],
            r["subcategory"],
            r["confidence"],
            r["evidence_quote"],
            r["reasoning"],
            fix,
        ),
    )


def run_judge(
    con: sqlite3.Connection,
    backend: Backend,
    model: str,
    *,
    limit: int | None = None,
    session_id: str | None = None,
    max_response_chars: int = 4000,
    retries: int = 1,
) -> dict:
    """Judge all turns that have no analysis for `model` yet."""
    sql = (
        "select t.* from turns t left join analyses a on a.turn_id = t.id and a.model = ?"
        " where a.id is null"
    )
    params: list = [model]
    if session_id:
        sql += " and t.session_id = ?"
        params.append(session_id)
    sql += " order by t.id"
    if limit:
        sql += " limit ?"
        params.append(limit)

    terms = load_terms()
    stats = {"judged": 0, "skipped_confirmation": 0, "failed": 0}

    for turn in con.execute(sql, params).fetchall():
        if looks_like_confirmation(turn["next_prompt"]):
            _store(con, turn["id"], model, _result(reasoning="heuristic: short confirmation, no iteration"))
            stats["skipped_confirmation"] += 1
            continue

        user = schema.format_user_message(
            redact(turn["prev_prompt"], terms),
            redact((turn["response"] or "")[:max_response_chars], terms) or None,
            redact(turn["next_prompt"], terms),
        )
        result = None
        for _ in range(retries + 1):
            try:
                result = schema.validate_result(backend(schema.SYSTEM_PROMPT, user, model))
                break
            except Exception as e:
                last_error = e
        if result is None:
            print(f"turn {turn['id']} failed: {last_error!r}", file=sys.stderr)
            stats["failed"] += 1
            continue
        _store(con, turn["id"], model, result)
        stats["judged"] += 1

    con.commit()
    return stats
