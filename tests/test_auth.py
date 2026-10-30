"""auth_mode: what the SDK's own CLI reports (`claude auth status`), without calling the model."""

from startup_assistant import agent
from startup_assistant.agent import auth_mode


def _status(monkeypatch, status):
    monkeypatch.setattr(agent, "_cli_auth_status", lambda: status)


def test_not_logged_in(monkeypatch):
    _status(monkeypatch, {"loggedIn": False, "authMethod": "none"})
    assert auth_mode() == "not-logged-in"


def test_api_key(monkeypatch):
    _status(monkeypatch, {"loggedIn": True, "authMethod": "api_key", "apiKeySource": "ANTHROPIC_API_KEY"})
    assert auth_mode() == "api-key"


def test_claude_login(monkeypatch):
    _status(monkeypatch, {"loggedIn": True, "authMethod": "claude.ai"})
    assert auth_mode() == "claude-session"


def test_falls_back_to_env_when_status_unavailable(monkeypatch):
    _status(monkeypatch, None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert auth_mode() == "claude-session"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert auth_mode() == "api-key"


def test_status_is_none_when_cli_cannot_run(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "_find_cli", lambda: str(tmp_path / "missing-claude"))
    assert agent._cli_auth_status() is None


def test_status_is_none_when_cli_prints_garbage(monkeypatch, tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho not json\n")
    fake.chmod(0o755)
    monkeypatch.setattr(agent, "_find_cli", lambda: str(fake))
    assert agent._cli_auth_status() is None


def test_status_parsed_from_cli_even_on_nonzero_exit(monkeypatch, tmp_path):
    # `claude auth status` exits 1 when logged out but still prints the JSON.
    fake = tmp_path / "claude"
    fake.write_text('#!/bin/sh\necho \'{"loggedIn": false, "authMethod": "none"}\'\nexit 1\n')
    fake.chmod(0o755)
    monkeypatch.setattr(agent, "_find_cli", lambda: str(fake))
    assert agent._cli_auth_status() == {"loggedIn": False, "authMethod": "none"}
