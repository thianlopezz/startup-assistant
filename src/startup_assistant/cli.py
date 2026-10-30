"""Rich-based chat REPL for the HarborDesk founder assistant."""

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel

from startup_assistant.agent import Assistant, auth_mode
from startup_assistant.contracts import Reply

EXIT_WORDS = {"exit", "quit"}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="startup-assistant", description="Chat with the HarborDesk founder assistant."
    )
    p.add_argument("--data-dir", type=Path, default=Path("data"),
                   help="where company knowledge and briefs are stored (default: data)")
    p.add_argument("--reset", action="store_true",
                   help="delete the data dir first; it is re-seeded on start")
    p.add_argument("--model", default=None, help="model name to use (default: SDK default)")
    return p.parse_args(argv)


def render_reply(console: Console, reply: Reply) -> None:
    """Labelled header, model text, each artifact in a titled panel, then the honest actions footer."""
    console.print()
    console.rule("[bold green]Assistant[/]", align="left", style="green")
    console.print(Markdown(reply.text))
    for artifact in reply.artifacts:
        console.print(Panel(Markdown(artifact), title="Brief", title_align="left", border_style="green"))
    if reply.actions:
        footer = f"[Changed: {'; '.join(reply.actions)}]"
    else:
        footer = "[No saved data changed]"
    console.print(footer, markup=False, highlight=False, style="dim")
    console.print()


def reset_data(data_dir: Path) -> None:
    shutil.rmtree(data_dir, ignore_errors=True)


def make_prompt_session(**kwargs) -> PromptSession:
    """Interactive prompt with bracketed paste: a pasted multi-line block stays one message
    and only the user's own Enter submits it."""
    return PromptSession(**kwargs)


async def _read_message(console: Console, session: PromptSession | None) -> str:
    if session is None:  # piped stdin (scripts, tests): one line per message
        return console.input("[bold cyan]You>[/] ")
    console.rule("[bold cyan]You[/]", align="left", style="cyan")
    return await session.prompt_async(HTML("<ansicyan><b>&gt;</b></ansicyan> "))


async def _repl(
    console: Console, data_dir: Path, model: str | None, session: PromptSession | None = None
) -> None:
    async with Assistant(data_dir, model) as assistant:
        while True:
            try:
                text = (await _read_message(console, session)).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not text:
                continue
            if text.lower() in EXIT_WORDS:
                break
            try:
                reply = await assistant.handle(text)
            except KeyboardInterrupt:
                console.print("Interrupted", markup=False)
                continue
            except Exception as exc:  # model/SDK failure must not kill the session
                msg = escape(f"{type(exc).__name__}: {exc}")
                console.print(f"[red]Error:[/] {msg}", highlight=False)
                continue
            render_reply(console, reply)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    console = Console()
    if args.reset:
        reset_data(args.data_dir)
    console.print(Panel(
        f"HarborDesk assistant\nData dir: {args.data_dir}\nAuth: {auth_mode()}\n"
        "Type 'exit' or 'quit' (or Ctrl-D) to leave.",
        expand=False,
    ))
    session = make_prompt_session() if sys.stdin.isatty() else None
    asyncio.run(_repl(console, args.data_dir, args.model, session))
    return 0
