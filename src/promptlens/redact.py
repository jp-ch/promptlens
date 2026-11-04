"""Redaction that runs before anything is written to disk or sent to a judge model.

Pattern-based, so it is a safety net and not a guarantee. Add customer and project
names (one per line) to ~/.promptlens/redact_terms.txt; they are replaced case-insensitively.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .db import home_dir

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@"), r"\1[CREDENTIALS]@"),
    (
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
            r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
        ),
        "[KEY]",
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[JWT]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), "[BEARER]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
    # key = value style secrets keep the key name so the sentence stays readable
    (
        re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b(\s*[:=]\s*)(\"[^\"]+\"|'[^']+'|\S+)"),
        r"\1\2[REDACTED]",
    ),
]

def load_terms() -> list[str]:
    path = Path(os.environ.get("PROMPTLENS_TERMS", home_dir() / "redact_terms.txt"))
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def redact(text: str, terms: list[str] | tuple[str, ...] = ()) -> str:
    if not text:
        return text
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    for term in sorted(set(terms), key=len, reverse=True):
        out = re.sub(re.escape(term), "[TERM]", out, flags=re.IGNORECASE)
    return out
