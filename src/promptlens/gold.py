"""Validate the judge against your own labels.

export-gold writes a CSV with a blank `human_category` column. Fill it in, then run eval-gold
to get accuracy, Cohen's kappa and a confusion matrix. This is the number that tells you
whether the judge can be trusted.
"""

from __future__ import annotations

import csv
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .schema import CATEGORIES

FIELDS = ["turn_id", "prev_prompt", "response", "next_prompt", "judge_category", "human_category"]


def export_gold(con: sqlite3.Connection, path: str | Path, n: int, model: str, seed: int = 0) -> int:
    rows = con.execute(
        "select t.id turn_id, t.prev_prompt, t.response, t.next_prompt, a.category judge_category"
        " from analyses a join turns t on t.id = a.turn_id where a.model = ?",
        (model,),
    ).fetchall()
    sample = random.Random(seed).sample(rows, min(n, len(rows)))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(dict(r) for r in sample)
    return len(sample)


def eval_gold(path: str | Path) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("human_category") or "").strip()]
    if not rows:
        raise ValueError("no labelled rows: fill the human_category column first")

    pairs = [(r["human_category"].strip(), r["judge_category"].strip()) for r in rows]
    for h, _ in pairs:
        if h not in CATEGORIES:
            raise ValueError(f"unknown human_category {h!r} (allowed: {', '.join(CATEGORIES)})")
    n = len(pairs)
    accuracy = sum(h == j for h, j in pairs) / n
    human_dist = Counter(h for h, _ in pairs)
    judge_dist = Counter(j for _, j in pairs)
    pe = sum((human_dist[c] / n) * (judge_dist[c] / n) for c in CATEGORIES)
    kappa = 1.0 if pe >= 1 else (accuracy - pe) / (1 - pe)

    confusion: dict[str, Counter] = defaultdict(Counter)
    for h, j in pairs:
        confusion[h][j] += 1

    return {"n": n, "accuracy": accuracy, "kappa": kappa, "confusion": confusion}


def format_eval(res: dict) -> str:
    lines = [f"Labelled turns: {res['n']}", f"Accuracy: {res['accuracy']:.2%}", f"Cohen's kappa: {res['kappa']:.2f}"]
    lines.append("\nConfusion (rows = human, columns = judge)")
    for h, row in sorted(res["confusion"].items()):
        cells = ", ".join(f"{j}: {n}" for j, n in sorted(row.items()))
        lines.append(f"  {h:<20} {cells}")
    return "\n".join(lines)
