"""promptlens command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import db, gold, judge, log_hook, report, segment
from .redact import load_terms, redact

def _hook(event: str) -> list[dict]:
    cmd = f"promptlens-hook --event {event}"
    return [{"type": "command", "bash": cmd, "powershell": cmd, "timeoutSec": 10}]


HOOK_CONFIG = {"version": 1, "hooks": {ev: _hook(ev) for ev in ("UserPromptSubmit", "Stop")}}


def cmd_init_hooks(args: argparse.Namespace) -> int:
    target = Path(args.target) / ".github" / "hooks" / "promptlens.json"
    if target.exists() and not args.force:
        print(f"{target} exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(HOOK_CONFIG, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target}")
    print("Make sure `promptlens-hook` is on PATH for the editor, or put its absolute path in the file.")
    return 0


def cmd_import_jsonl(args: argparse.Namespace) -> int:
    """Import events from a JSONL file: {"session_id", "event": "prompt"|"stop", "prompt"|"response"}."""
    con = db.connect()
    terms = load_terms()
    n = 0
    with open(args.file, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("event") not in ("prompt", "stop"):
                continue
            log_hook.store(
                {
                    "ts": log_hook._iso(None),
                    "session_id": e.get("session_id", "imported"),
                    "event": e["event"],
                    "cwd": None,
                    "prompt": redact(e["prompt"], terms) if e.get("prompt") else None,
                    "response": redact(e["response"], terms) if e.get("response") else None,
                    "transcript_path": None,
                },
                con,
            )
            n += 1
    print(f"Imported {n} events into {db.db_path()}")
    return 0


def cmd_segment(args: argparse.Namespace) -> int:
    n = segment.build_turns(db.connect(), args.session)
    print(f"Created {n} new turns")
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    con = db.connect()
    segment.build_turns(con, args.session)
    if args.dry_run:
        backend, model = judge.dry_run_backend, "dry-run"
    else:
        model = args.model or os.environ.get("PROMPTLENS_MODEL")
        if not model:
            print("Pass --model or set PROMPTLENS_MODEL (or use --dry-run).", file=sys.stderr)
            return 2
        backend = judge.openai_backend
    stats = judge.run_judge(
        con, backend, model, limit=args.limit, session_id=args.session, max_response_chars=args.max_response_chars
    )
    print(f"model={model} judged={stats['judged']} skipped={stats['skipped_confirmation']} failed={stats['failed']}")
    return 0 if stats["failed"] == 0 else 1


def cmd_report(args: argparse.Namespace) -> int:
    print(report.format_report(report.summarize(db.connect(), args.model)))
    return 0


def cmd_export_gold(args: argparse.Namespace) -> int:
    n = gold.export_gold(db.connect(), args.out, args.n, args.model, args.seed)
    print(f"Wrote {n} rows to {args.out}. Fill in human_category, then run eval-gold.")
    return 0


def cmd_eval_gold(args: argparse.Namespace) -> int:
    print(gold.format_eval(gold.eval_gold(args.file)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="promptlens", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-hooks", help="write .github/hooks/promptlens.json")
    s.add_argument("--target", default=".", help="repository root (default: current directory)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init_hooks)

    s = sub.add_parser("import-jsonl", help="import events from a JSONL file (demo data, other tools)")
    s.add_argument("file")
    s.set_defaults(fn=cmd_import_jsonl)

    s = sub.add_parser("segment", help="build turn triples from logged events")
    s.add_argument("--session")
    s.set_defaults(fn=cmd_segment)

    s = sub.add_parser("judge", help="classify pending turns (segments first)")
    s.add_argument("--model")
    s.add_argument("--dry-run", action="store_true", help="no API calls, labels everything 'unclear'")
    s.add_argument("--limit", type=int)
    s.add_argument("--session")
    s.add_argument("--max-response-chars", type=int, default=4000)
    s.set_defaults(fn=cmd_judge)

    s = sub.add_parser("report", help="aggregate causes and suggested fixes")
    s.add_argument("--model")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("export-gold", help="sample turns into a CSV for manual labelling")
    s.add_argument("--model", required=True)
    s.add_argument("--n", type=int, default=50)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", default="gold.csv")
    s.set_defaults(fn=cmd_export_gold)

    s = sub.add_parser("eval-gold", help="accuracy, kappa and confusion matrix against your labels")
    s.add_argument("file")
    s.set_defaults(fn=cmd_eval_gold)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
