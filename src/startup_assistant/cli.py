"""Rich-based chat REPL for the HarborDesk founder assistant."""

import argparse
import asyncio
import shutil
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
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
    """Model text, then each artifact in a panel, then the honest actions footer."""
    console.print(Markdown(reply.text))
    for artifact in reply.artifacts:
        console.print(Panel(Markdown(artifact)))
    if reply.actions:
        console.print(f"[Changed: {'; '.join(reply.actions)}]", markup=False, highlight=False)
    else:
        console.print("[No saved data changed]", markup=False, highlight=False)


def reset_data(data_dir: Path) -> None:
    shutil.rmtree(data_dir, ignore_errors=True)


async def _repl(console: Console, data_dir: Path, model: str | None) -> None:
    async with Assistant(data_dir, model) as assistant:
        while True:
            try:
                text = console.input("[bold cyan]You>[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not text:
                continue
            if text.lower() in EXIT_WORDS:
                break
            try:
                reply = await assistant.handle(text)
            except Exception as exc:  # model/SDK failure must not kill the session
                console.print(f"[red]Error:[/] {type(exc).__name__}: {exc}", highlight=False)
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
    asyncio.run(_repl(console, args.data_dir, args.model))
    return 0
