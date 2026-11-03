import json

from promptlens import db, log_hook


def rows(con):
    return [dict(r) for r in con.execute("select * from events order by id")]


def test_prompt_event_snake_case(con):
    raw = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "timestamp": "2026-11-03T10:00:00Z",
            "cwd": "/work/app",
            "prompt": "fix it, key sk-abcdefghijklmnop1234",
        }
    )
    log_hook.handle_payload(raw)
    r = rows(con)[0]
    assert r["event"] == "prompt" and r["session_id"] == "s1"
    assert "sk-" not in r["prompt"] and "[KEY]" in r["prompt"]


def test_prompt_event_camel_case_with_cli_event_arg(con):
    raw = json.dumps({"sessionId": "s2", "timestamp": 1_762_164_000_000, "cwd": "/x", "prompt": "hello"})
    log_hook.handle_payload(raw, "userPromptSubmitted")
    r = rows(con)[0]
    assert r["session_id"] == "s2" and r["ts"].startswith("2025-11-03")


def test_unknown_event_is_ignored(con):
    assert log_hook.handle_payload(json.dumps({"hook_event_name": "PreToolUse"})) is None
    assert rows(con) == []


def test_stop_event_extracts_last_assistant_text(con, tmp_path):
    transcript = tmp_path / "t.jsonl"
    lines = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "q2"},
        {"type": "assistant.message", "data": {"content": [{"type": "text", "text": "final answer"}]}},
    ]
    transcript.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    log_hook.handle_payload(
        json.dumps({"session_id": "s3", "transcript_path": str(transcript)}), "Stop"
    )
    assert rows(con)[0]["response"] == "final answer"


def test_stop_event_with_missing_transcript_still_logs(con):
    log_hook.handle_payload(json.dumps({"session_id": "s4", "transcript_path": "/nope/x.jsonl"}), "Stop")
    r = rows(con)[0]
    assert r["event"] == "stop" and r["response"] is None


def test_main_never_raises_and_prints_nothing(monkeypatch, capsys, tmp_path):
    import io

    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"{not json")))
    assert log_hook.main(["--event", "UserPromptSubmit"]) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    assert (db.home_dir() / "hook_errors.log").exists()


def test_dump_writes_raw_payload(monkeypatch, tmp_path):
    dump = tmp_path / "dump.jsonl"
    monkeypatch.setenv("PROMPTLENS_DUMP", str(dump))
    log_hook.handle_payload(json.dumps({"hook_event_name": "Other", "x": 1}))
    assert json.loads(dump.read_text().strip()) == {"hook_event_name": "Other", "x": 1}
