import pytest

from promptlens import db


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PROMPTLENS_DB", raising=False)
    monkeypatch.delenv("PROMPTLENS_TERMS", raising=False)
    monkeypatch.delenv("PROMPTLENS_DUMP", raising=False)


@pytest.fixture
def con():
    c = db.connect()
    yield c
    c.close()
