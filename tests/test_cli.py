import json
from pathlib import Path

from promptlens import cli

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo_events.jsonl"


def test_init_hooks_writes_valid_config_and_refuses_overwrite(tmp_path, capsys):
    assert cli.main(["init-hooks", "--target", str(tmp_path)]) == 0
    cfg = json.loads((tmp_path / ".github" / "hooks" / "promptlens.json").read_text())
    assert cfg["version"] == 1 and set(cfg["hooks"]) == {"UserPromptSubmit", "Stop"}
    assert cli.main(["init-hooks", "--target", str(tmp_path)]) == 1
    assert cli.main(["init-hooks", "--target", str(tmp_path), "--force"]) == 0


def test_demo_pipeline_dry_run(capsys):
    assert cli.main(["import-jsonl", str(DEMO)]) == 0
    assert cli.main(["judge", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "judged=" in out and "skipped=1" in out  # the final "thanks" in demo-1
    assert cli.main(["report", "--model", "dry-run"]) == 0
    assert "unclear" in capsys.readouterr().out


def test_judge_requires_model_without_dry_run(capsys, monkeypatch):
    monkeypatch.delenv("PROMPTLENS_MODEL", raising=False)
    assert cli.main(["judge"]) == 2
