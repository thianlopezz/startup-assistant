from pathlib import Path

from rich.console import Console

from startup_assistant import cli
from startup_assistant.cli import parse_args, render_reply, reset_data
from startup_assistant.contracts import Reply


def _render(reply: Reply) -> str:
    console = Console(record=True, width=100)
    render_reply(console, reply)
    return console.export_text()


def test_footer_no_changes():
    out = _render(Reply(text="Hello there"))
    assert "Hello there" in out
    assert "[No saved data changed]" in out


def test_footer_lists_actions():
    out = _render(Reply(text="ok", actions=["Saved brief v1", "Company knowledge updated -> v1"]))
    assert "[Changed: Saved brief v1; Company knowledge updated -> v1]" in out
    assert "No saved data changed" not in out


def test_artifact_printed():
    out = _render(Reply(text="Here it is", artifacts=["# Brief v2\n\nUnique artifact body"]))
    assert "Unique artifact body" in out
    assert out.index("Here it is") < out.index("Unique artifact body") < out.index("[No saved data changed]")


def test_reply_is_labelled_as_assistant():
    out = _render(Reply(text="Hello there", artifacts=["Brief body"]))
    lines = [l for l in out.splitlines() if l.strip()]
    assert "Assistant" in lines[0]  # header line comes before the reply text
    assert out.index("Assistant") < out.index("Hello there")
    assert "Brief" in out.split("Hello there", 1)[1].split("Brief body", 1)[0]  # titled brief panel


def test_reset_removes_dir(tmp_path: Path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "x.json").write_text("{}")
    reset_data(d)
    assert not d.exists()
    reset_data(d)  # missing dir is fine


def test_parse_defaults():
    ns = parse_args([])
    assert ns.data_dir == Path("data")
    assert ns.reset is False
    assert ns.model is None


def test_parse_flags():
    ns = parse_args(["--data-dir", "x", "--reset", "--model", "m"])
    assert ns.data_dir == Path("x") and ns.reset is True and ns.model == "m"


class _FakeAssistant:
    def __init__(self, data_dir, model=None):
        self.seen = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def handle(self, text):
        self.seen.append(text)
        if text == "boom":
            raise RuntimeError("model exploded")
        return Reply(text=f"echo {text}")


def test_repl_continues_after_error_and_exits(monkeypatch, tmp_path, capsys):
    inputs = iter(["boom", "", "hi", "quit"])
    monkeypatch.setattr(cli, "Assistant", _FakeAssistant)
    monkeypatch.setattr(cli, "auth_mode", lambda: "claude-session")
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
    assert cli.main(["--data-dir", str(tmp_path / "d")]) == 0
    out = capsys.readouterr().out
    assert "model exploded" in out
    assert "echo hi" in out
    assert "claude-session" in out


def test_repl_exits_on_eof(monkeypatch, tmp_path):
    def raise_eof(*a, **k):
        raise EOFError

    monkeypatch.setattr(cli, "Assistant", _FakeAssistant)
    monkeypatch.setattr(cli, "auth_mode", lambda: "api-key")
    monkeypatch.setattr("builtins.input", raise_eof)
    assert cli.main(["--data-dir", str(tmp_path / "d")]) == 0


class _BracketAssistant(_FakeAssistant):
    async def handle(self, text):
        if text == "boom":
            raise RuntimeError("bad [/usr/bin/claude] path")
        if text == "intr":
            raise KeyboardInterrupt
        return await super().handle(text)


def test_repl_survives_markup_in_error_and_interrupt(monkeypatch, tmp_path, capsys):
    inputs = iter(["boom", "intr", "hi", "quit"])
    monkeypatch.setattr(cli, "Assistant", _BracketAssistant)
    monkeypatch.setattr(cli, "auth_mode", lambda: "claude-session")
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
    assert cli.main(["--data-dir", str(tmp_path / "d")]) == 0
    out = capsys.readouterr().out
    assert "bad [/usr/bin/claude] path" in out
    assert "Interrupted" in out
    assert "echo hi" in out


class _RecordingAssistant(_FakeAssistant):
    received: list[str] = []

    async def handle(self, text):
        _RecordingAssistant.received.append(text)
        return Reply(text="ok")


def test_pasted_multiline_text_is_one_message(monkeypatch, tmp_path):
    import asyncio

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    _RecordingAssistant.received = []
    monkeypatch.setattr(cli, "Assistant", _RecordingAssistant)
    with create_pipe_input() as inp:
        # A terminal wraps pasted text in bracketed-paste markers; the newline inside is
        # part of the paste, and only the final Enter (\r) submits.
        inp.send_text("\x1b[200~We're shifting our target.\nPricing is under review.\x1b[201~\r")
        inp.send_text("exit\r")
        session = cli.make_prompt_session(input=inp, output=DummyOutput())
        asyncio.run(cli._repl(Console(file=open("/dev/null", "w")), tmp_path / "d", None, session))
    assert _RecordingAssistant.received == ["We're shifting our target.\nPricing is under review."]
