"""Aggregate judge results across sessions."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter


def summarize(con: sqlite3.Connection, model: str | None = None) -> dict:
    where = "where a.model = ?" if model else ""
    params = (model,) if model else ()
    rows = con.execute(
        "select a.*, t.session_id from analyses a join turns t on t.id = a.turn_id "
        + where,
        params,
    ).fetchall()

    iterations = [r for r in rows if r["is_iteration"]]
    by_category = Counter(r["category"] for r in iterations)
    by_sub = Counter((r["category"], r["subcategory"]) for r in iterations if r["subcategory"])

    fixes: dict[str, list[dict]] = {}
    for r in iterations:
        if r["suggested_fix"]:
            fix = json.loads(r["suggested_fix"])
            fixes.setdefault(fix["artifact_type"], []).append(
                {"turn_id": r["turn_id"], "text": fix["text"], "confidence": r["confidence"]}
            )

    return {
        "analyzed_turns": len(rows),
        "iterations": len(iterations),
        "by_category": dict(by_category),
        "by_subcategory": {f"{c}/{s}": n for (c, s), n in by_sub.most_common()},
        "suggested_fixes": fixes,
    }


def format_report(s: dict) -> str:
    lines = [f"Analyzed turns: {s['analyzed_turns']}   Iterations: {s['iterations']}"]
    total = s["iterations"] or 1
    if s["by_category"]:
        lines.append("\nCauses of iterations")
        for cat, n in sorted(s["by_category"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  {cat:<20} {n:>4}  {100 * n / total:5.1f}%")
    if s["by_subcategory"]:
        lines.append("\nBy subcategory")
        for key, n in s["by_subcategory"].items():
            lines.append(f"  {key:<42} {n:>4}")
    if s["suggested_fixes"]:
        lines.append("\nSuggested fixes (review before adopting)")
        for artifact, items in s["suggested_fixes"].items():
            lines.append(f"  {artifact} ({len(items)})")
            for it in items[:5]:
                lines.append(f"    - [turn {it['turn_id']}] {it['text']}")
    return "\n".join(lines)
