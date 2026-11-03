import json

import pytest

from promptlens import gold, judge, report, schema, segment


def add(con, sid, event, prompt=None, response=None):
    con.execute(
        "insert into events(ts, session_id, event, prompt, response) values ('t', ?, ?, ?, ?)",
        (sid, event, prompt, response),
    )
    con.commit()


def seed_session(con):
    add(con, "a", "prompt", "no lombok please")
    add(con, "a", "stop", response="used lombok")
    add(con, "a", "prompt", "you used lombok, I said no lombok")
    add(con, "a", "stop", response="fixed")
    add(con, "a", "prompt", "thanks")
    add(con, "b", "prompt", "only one prompt")  # no follow-up, so no turn


def good(category="llm_error", is_iteration=True, **kw):
    d = {
        "reasoning": "r",
        "is_iteration": is_iteration,
        "category": category if is_iteration else "none",
        "subcategory": None,
        "confidence": 0.9,
        "evidence_quote": None,
        "suggested_fix": None,
    }
    d.update(kw)
    return d


def test_segment_builds_pairs_and_is_idempotent(con):
    seed_session(con)
    assert segment.build_turns(con) == 2
    assert segment.build_turns(con) == 0
    turns = con.execute("select * from turns order by idx").fetchall()
    assert turns[0]["prev_prompt"] == "no lombok please"
    assert turns[0]["response"] == "used lombok"
    assert turns[0]["next_prompt"].startswith("you used")
    assert turns[1]["response"] == "fixed" and turns[1]["next_prompt"] == "thanks"


def test_confirmation_heuristic():
    assert segment.looks_like_confirmation("Thanks!")
    assert segment.looks_like_confirmation("lgtm")
    assert not segment.looks_like_confirmation("thanks, but also add retries")


def test_judge_stores_results_and_skips_confirmation(con):
    seed_session(con)
    segment.build_turns(con)
    calls = []

    def backend(system, user, model):
        calls.append(user)
        return good(subcategory="ignored_instruction")

    stats = judge.run_judge(con, backend, "m1")
    assert stats == {"judged": 1, "skipped_confirmation": 1, "failed": 0}
    assert len(calls) == 1 and "you used lombok" in calls[0]
    assert judge.run_judge(con, backend, "m1")["judged"] == 0  # nothing pending any more
    rows = con.execute("select category, is_iteration from analyses order by turn_id").fetchall()
    assert [(r["category"], r["is_iteration"]) for r in rows] == [("llm_error", 1), ("none", 0)]


def test_judge_retries_then_counts_failures(con):
    seed_session(con)
    segment.build_turns(con)
    attempts = {"n": 0}

    def flaky(system, user, model):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("api hiccup")
        return good()

    assert judge.run_judge(con, flaky, "m", retries=1)["judged"] == 1

    def broken(system, user, model):
        return {"category": "nonsense"}

    con.execute("delete from analyses")
    stats = judge.run_judge(con, broken, "m", retries=1)
    assert stats["failed"] == 1


def test_judge_sends_only_redacted_text(con):
    add(con, "s", "prompt", "use key sk-abcdefghijklmnop1234")
    add(con, "s", "prompt", "still key ghp_abcdefghijklmnopqrstuv")
    segment.build_turns(con)
    seen = []
    judge.run_judge(con, lambda s, u, m: seen.append(u) or good(), "m")
    assert "sk-abc" not in seen[0] and "ghp_" not in seen[0]


def test_validate_result_rules():
    assert schema.validate_result(good(confidence=7))["confidence"] == 1.0
    with pytest.raises(ValueError):
        schema.validate_result(good(category="none", is_iteration=True) | {"category": "none"})
    with pytest.raises(ValueError):
        schema.validate_result(good() | {"is_iteration": False})  # category must be none
    with pytest.raises(ValueError):
        schema.validate_result(good(suggested_fix={"artifact_type": "poem", "text": "x"}))
    ok = schema.validate_result(good(suggested_fix={"artifact_type": "instruction", "text": "Never use Lombok."}))
    assert ok["suggested_fix"]["artifact_type"] == "instruction"


def test_schema_is_strict_and_consistent():
    s = schema.RESULT_SCHEMA["schema"]
    assert set(s["required"]) == set(s["properties"])
    assert s["additionalProperties"] is False
    json.dumps(schema.RESULT_SCHEMA)  # serializable


def test_report_and_gold_roundtrip(con, tmp_path):
    seed_session(con)
    segment.build_turns(con)
    judge.run_judge(
        con,
        lambda s, u, m: good(
            subcategory="ignored_instruction",
            suggested_fix={"artifact_type": "instruction", "text": "Never use Lombok."},
        ),
        "m",
    )
    rep = report.summarize(con, "m")
    assert rep["iterations"] == 1 and rep["by_category"] == {"llm_error": 1}
    assert "instruction" in rep["suggested_fixes"]
    assert "llm_error" in report.format_report(rep)

    path = tmp_path / "gold.csv"
    assert gold.export_gold(con, path, n=10, model="m") == 2

    import csv

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["human_category"] = "llm_error" if r["judge_category"] == "llm_error" else "none"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=gold.FIELDS)
        w.writeheader()
        w.writerows(rows)
    res = gold.eval_gold(path)
    assert res["n"] == 2 and res["accuracy"] == 1.0 and res["kappa"] == 1.0


def test_eval_gold_rejects_unknown_label(tmp_path):
    path = tmp_path / "g.csv"
    path.write_text("turn_id,prev_prompt,response,next_prompt,judge_category,human_category\n1,a,b,c,llm_error,typo\n")
    with pytest.raises(ValueError):
        gold.eval_gold(path)
