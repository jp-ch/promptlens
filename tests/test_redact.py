from promptlens.redact import load_terms, redact


def test_api_keys_and_tokens():
    out = redact("use sk-abcdefghijklmnop1234 and ghp_abcdefghijklmnopqrstuv")
    assert "sk-abc" not in out and "ghp_" not in out
    assert out.count("[KEY]") == 2


def test_assignment_keeps_key_name():
    assert redact("password: hunter2 and api_key=abc123") == "password: [REDACTED] and api_key=[REDACTED]"


def test_url_credentials_email_ip():
    out = redact("postgres://admin:secret@db.internal/app mail me@example.com host 10.0.0.12")
    assert "admin" not in out and "secret" not in out
    assert "[EMAIL]" in out and "[IP]" in out


def test_jwt_and_bearer():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlMTIzNDU2"
    out = redact(f"Authorization: Bearer abcdefghijklmnopqrstuvwxyz and {jwt}")
    assert "[BEARER]" in out and "[JWT]" in out


def test_custom_terms_case_insensitive(tmp_path, monkeypatch):
    terms_file = tmp_path / "terms.txt"
    terms_file.write_text("# customers\nAcme Motors\nBundesamt Foo\n", encoding="utf-8")
    monkeypatch.setenv("PROMPTLENS_TERMS", str(terms_file))
    out = redact("Projekt für ACME motors und das bundesamt foo", load_terms())
    assert out == "Projekt für [TERM] und das [TERM]"


def test_plain_text_untouched():
    text = "Write a Spring Boot controller for orders."
    assert redact(text) == text
