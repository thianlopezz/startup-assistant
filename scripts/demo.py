#!/usr/bin/env python
"""Two-process demo of the HarborDesk assistant, with optional checks on the saved data.

    python scripts/demo.py                    # reset, phase 1, then phase 2 in a NEW process
    python scripts/demo.py --phase 2          # only the restart-and-retrieve turn
    python scripts/demo.py --check            # run, then verify the saved data
    python scripts/demo.py --fake --check     # canned replies instead of the model

Every turn is appended to examples/transcript.md.
"""

import argparse
import asyncio
import re
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from startup_assistant.agent import Assistant, auth_mode
from startup_assistant.briefs import BriefStore
from startup_assistant.cli import render_reply, reset_data
from startup_assistant.contracts import BriefDraft, Channel, Reply
from startup_assistant.knowledge import KnowledgeStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "examples" / "demo-data"
DEFAULT_TRANSCRIPT = ROOT / "examples" / "transcript.md"
FAKE_DATA_DIR = ROOT / "examples" / "fake-data"
FAKE_TRANSCRIPT = ROOT / "examples" / "fake-transcript.md"

FOUNDER_UPDATE = (
    "We're shifting our target to B2B software companies with 100–500 employees. The buyer is the "
    "Head of Customer Success. Remember this as our target going forward. Pricing is under review, "
    "so leave prices out of campaign materials. Our product capabilities are unchanged."
)

PHASE1 = [
    "Who are we targeting, and what problem do we solve for them?",
    "Create a brief for our next customer acquisition campaign using what we know about the "
    "company. Save it so I can retrieve it later.",
    FOUNDER_UPDATE,
    "Who is our current target audience and buyer?",
    "Update the campaign brief for our new audience. Focus on coordinating onboarding handoffs "
    "across teams.",
]
PHASE2 = ["Show me the latest campaign brief."]


# --------------------------------------------------------------------------- transcript


def _err(exc: BaseException) -> str:
    """Exception text made safe to print through rich markup."""
    return escape(f"{type(exc).__name__}: {exc}")


def turn_marker(n: int) -> str:
    return f"### Turn {n} — You:"


def format_turn(n: int, text: str, reply: Reply) -> str:
    parts = [f"{turn_marker(n)}\n\n> {text}\n", "**Reply:**\n", reply.text.strip() + "\n"]
    for i, artifact in enumerate(reply.artifacts, 1):
        # A tilde fence keeps the artifact byte-for-byte while staying readable.
        parts.append(f"**Artifact {i}:**\n\n~~~~markdown\n{artifact}\n~~~~\n")
    footer = (
        f"[Changed: {'; '.join(reply.actions)}]" if reply.actions else "[No saved data changed]"
    )
    parts.append(f"**Footer:** `{footer}`\n")
    return "\n".join(parts) + "\n"


def format_error(n: int, text: str, exc: BaseException) -> str:
    return f"{turn_marker(n)}\n\n> {text}\n\n**ERROR:** {type(exc).__name__}: {exc}\n\n"


# --------------------------------------------------------------------------- fake assistant


def _words(n: int, stem: str) -> str:
    return " ".join(f"{stem}{i}" for i in range(n))


def _canned_draft(version: int) -> BriefDraft:
    if version == 1:
        return BriefDraft(
            title="Customer acquisition campaign (fake v1)",
            audience="Small support teams",
            buyer="Support lead",
            main_message="Keep every customer conversation in one shared inbox.",
            channels=[Channel(name="LinkedIn", reason="reach"), Channel(name="Email", reason="direct")],
            email_subject="One inbox for support",
            email_body="Hi, " + _words(20, "w"),
            assumptions=["canned fake data"],
            open_questions=["none"],
        )
    return BriefDraft(
        title="Customer acquisition campaign (fake v2)",
        audience="B2B software companies with 100-500 employees",
        buyer="Head of Customer Success",
        main_message="Coordinate onboarding handoffs across teams without losing context.",
        channels=[Channel(name="LinkedIn", reason="reach"), Channel(name="Email", reason="direct")],
        email_subject="Smoother onboarding handoffs",
        email_body="Hi, " + _words(20, "w"),
        assumptions=["canned fake data"],
        open_questions=["none"],
    )


def _brief_markdown(draft: BriefDraft, version: int) -> str:
    return (
        f"# {draft.title}\n\n**Audience:** {draft.audience}\n\n**Buyer:** {draft.buyer}\n\n"
        f"**Main message:** {draft.main_message}\n\n**Email:** {draft.email_subject}\n\n"
        f"{draft.email_body}\n\n_(fake brief v{version})_"
    )


class FakeAssistant:
    """Same interface as Assistant, canned replies. Writes through the real stores when they work."""

    def __init__(self, data_dir: Path, model: str | None = None):
        self.knowledge = KnowledgeStore(data_dir / "knowledge.json")
        self.briefs = BriefStore(data_dir / "briefs.json")
        self.step = 0

    async def __aenter__(self) -> "FakeAssistant":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def handle(self, text: str) -> Reply:
        try:
            return self._handle(text)
        except NotImplementedError:
            return Reply(text="(fake) the stores are not implemented yet; nothing was saved.")

    def _handle(self, text: str) -> Reply:
        if text == PHASE2[0]:
            rec = self.briefs.latest()
            if rec is None:
                return Reply(text="No brief has been saved yet.")
            return Reply(
                text=f"Here is the latest brief (v{rec.version}).", artifacts=[rec.markdown]
            )
        if text == PHASE1[0]:
            return Reply(text="(fake) Small support teams; they lose track of customer conversations.")
        if text == PHASE1[1]:
            draft = _canned_draft(1)
            md = _brief_markdown(draft, 1)
            rec = self.briefs.save(draft, md, "created", None, self.knowledge.version, text)
            return Reply(
                text="Saved the brief.", artifacts=[rec.markdown],
                actions=[f"Saved brief v{rec.version}"],
            )
        if text == FOUNDER_UPDATE:
            upd = self.knowledge.apply_update(
                text,
                "New target: B2B software companies, 100-500 employees; buyer Head of Customer "
                "Success; pricing under review.",
                {
                    "target_customers": "B2B software companies with 100-500 employees",
                    "primary_buyer": "Head of Customer Success",
                    "pricing": "Under review - leave out of campaign materials.",
                },
                ["Leave prices out of campaign materials."],
            )
            return Reply(
                text="Saved. Existing brief v1 was NOT revised.",
                actions=[f"Company knowledge updated -> v{upd.version}"],
            )
        if text == PHASE1[3]:
            profile = self.knowledge.current_profile()
            return Reply(
                text=f"Audience: {profile['target_customers']}. Buyer: {profile['primary_buyer']}."
            )
        if text == PHASE1[4]:
            draft = _canned_draft(2)
            md = _brief_markdown(draft, 2)
            rec = self.briefs.save(draft, md, "revised", 1, self.knowledge.version, text)
            return Reply(
                text="Saved a revised brief.", artifacts=[rec.markdown],
                actions=[f"Saved brief v{rec.version} (revises v1)"],
            )
        return Reply(text="(fake) no canned answer for that.")


# --------------------------------------------------------------------------- running


async def run_turns(
    console: Console, assistant, messages: list[str], first_turn: int, transcript: Path
) -> int:
    """Send messages, echo and log each turn. Returns the number of turns that errored."""
    errors = 0
    for n, text in enumerate(messages, first_turn):
        console.rule(f"Turn {n}")
        console.print(f"[bold cyan]You>[/] {text}", highlight=False)
        try:
            reply = await assistant.handle(text)
        except Exception as exc:
            errors += 1
            console.print(f"[red]Error:[/] {_err(exc)}", highlight=False)
            entry = format_error(n, text, exc)
        else:
            render_reply(console, reply)
            entry = format_turn(n, text, reply)
        with transcript.open("a", encoding="utf-8") as f:
            f.write(entry)
    return errors


def run_phase(args: argparse.Namespace, console: Console, phase: int) -> int:
    messages, first = (PHASE1, 1) if phase == 1 else (PHASE2, len(PHASE1) + 1)
    transcript: Path = args.transcript
    transcript.parent.mkdir(parents=True, exist_ok=True)
    if phase == 1:
        transcript.write_text(
            "# Demo transcript\n\nProcess 1 covers turns 1-5; process 2 (a fresh process) covers "
            "turn 6.\n\n",
            encoding="utf-8",
        )
    else:
        with transcript.open("a", encoding="utf-8") as f:
            f.write("---\n\n## Process 2 (fresh start)\n\n")
    console.rule(f"[bold]Phase {phase}[/]")
    try:
        mode = "fake" if args.fake else auth_mode()
    except Exception as exc:  # e.g. stub
        mode = f"unknown ({type(exc).__name__})"
    console.print(f"Data dir: {args.data_dir}   Auth: {mode}")

    async def go() -> int:
        cls = FakeAssistant if args.fake else Assistant
        async with cls(args.data_dir, args.model) as assistant:
            return await run_turns(console, assistant, messages, first, transcript)

    try:
        return asyncio.run(go())
    except Exception as exc:  # startup failure (auth, SDK)
        console.print(f"[red]Phase {phase} failed to run:[/] {_err(exc)}")
        return 1


def run_phase2_subprocess(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable, str(Path(__file__).resolve()), "--phase", "2",
        "--data-dir", str(args.data_dir), "--transcript", str(args.transcript),
    ]
    if args.fake:
        cmd.append("--fake")
    if args.model:
        cmd += ["--model", args.model]
    return subprocess.run(cmd).returncode


# --------------------------------------------------------------------------- checks


def _count_words(text: str) -> int:
    return len(text.split())


def run_checks(
    knowledge: KnowledgeStore, briefs: BriefStore, transcript_text: str
) -> list[tuple[str, bool, str]]:
    """Each check is independent; an exception (e.g. NotImplementedError) is a FAIL."""
    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        try:
            out = fn()
            ok, detail = out if isinstance(out, tuple) else (bool(out), "")
        except NotImplementedError:
            ok, detail = False, "not implemented"
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append((name, ok, detail))

    def v1_ok():
        v1 = briefs.get(1)
        if v1 is None:
            return False, "no brief v1"
        words = _count_words(v1.draft.email_body)
        ok = v1.kind == "created" and v1.knowledge_version == 0 and words <= 150
        return ok, f"kind={v1.kind} knowledge_version={v1.knowledge_version} email_words={words}"

    def knowledge_ok():
        buyer = knowledge.current_profile().get("primary_buyer", "")
        ok = knowledge.version == 1 and "Customer Success" in buyer and knowledge.pricing_restricted
        return ok, (
            f"version={knowledge.version} buyer={buyer!r} "
            f"pricing_restricted={knowledge.pricing_restricted}"
        )

    def count_ok():
        n = len(briefs.list())
        return n == 2, f"{n} brief version(s)"

    def v2_ok():
        v2 = briefs.get(2)
        if v2 is None:
            return False, "no brief v2"
        md = v2.markdown
        low = md.lower()
        problems = []
        if v2.revises != 1:
            problems.append(f"revises={v2.revises}")
        if v2.knowledge_version != 1:
            problems.append(f"knowledge_version={v2.knowledge_version}")
        if "Customer Success" not in md:
            problems.append("missing 'Customer Success'")
        if "handoff" not in low:
            problems.append("missing 'handoff'")
        for bad in ("$", "price", "pricing"):
            if bad in low:
                problems.append(f"contains {bad!r}")
        return not problems, "; ".join(problems) or "ok"

    def transcript_ok():
        v2 = briefs.get(2)
        if v2 is None:
            return False, "no brief v2 to compare"
        marker = turn_marker(len(PHASE1) + 1)
        if marker not in transcript_text:
            return False, f"transcript has no {marker!r}"
        section = transcript_text.rsplit(marker, 1)[-1]
        # Only artifact fences count: the brief must have been printed from the store,
        # not pasted into the model's reply text.
        fences = re.findall(r"~~~~markdown\n(.*?)\n~~~~", section, flags=re.S)
        return v2.markdown in fences, "phase-2 artifact compared with stored v2 markdown"

    check("v1 exists, created, knowledge v0, email <= 150 words", v1_ok)
    check("knowledge v1: buyer is Customer Success, pricing restricted", knowledge_ok)
    check("exactly 2 brief versions (update and retrieval created none)", count_ok)
    check("v2 revises v1 at knowledge v1; Customer Success + handoff; no price text", v2_ok)
    check("phase-2 transcript contains v2 markdown verbatim", transcript_ok)
    return results


def run_check_mode(console: Console, args: argparse.Namespace) -> int:
    try:
        knowledge = KnowledgeStore(args.data_dir / "knowledge.json")
        briefs = BriefStore(args.data_dir / "briefs.json")
        text = args.transcript.read_text(encoding="utf-8") if args.transcript.exists() else ""
        results = run_checks(knowledge, briefs, text)
    except Exception as exc:
        console.print(f"[red]FAIL[/] could not open stores: {_err(exc)}")
        return 1
    console.rule("[bold]Checks[/]")
    for name, ok, detail in results:
        tag = "[green]PASS[/]" if ok else "[red]FAIL[/]"
        tail = f"  ({escape(detail)})" if detail else ""
        console.print(f"{tag} {escape(name)}{tail}", highlight=False)
    failed = sum(1 for _, ok, _ in results if not ok)
    console.print(f"{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


# --------------------------------------------------------------------------- main


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=None,
                   help=f"default: {DEFAULT_DATA_DIR} (examples/fake-data with --fake)")
    p.add_argument("--phase", choices=["1", "2", "all"], default="all")
    p.add_argument("--check", action="store_true", help="verify the saved data afterwards")
    p.add_argument("--fake", action="store_true", help="canned replies instead of the model")
    p.add_argument("--model", default=None)
    p.add_argument("--transcript", type=Path, default=None,
                   help=f"default: {DEFAULT_TRANSCRIPT} (examples/fake-transcript.md with --fake)")
    args = p.parse_args(argv)
    if args.data_dir is None:
        args.data_dir = FAKE_DATA_DIR if args.fake else DEFAULT_DATA_DIR
    if args.transcript is None:
        args.transcript = FAKE_TRANSCRIPT if args.fake else DEFAULT_TRANSCRIPT
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    console = Console()
    rc = 0
    if args.phase == "all":
        reset_data(args.data_dir)
        rc |= run_phase(args, console, 1)
        console.print("\n[bold]Restarting: phase 2 runs in a new process.[/]\n")
        rc |= run_phase2_subprocess(args)
    else:
        if args.phase == "1":
            reset_data(args.data_dir)
        rc |= run_phase(args, console, int(args.phase))
    if args.check:
        rc |= run_check_mode(console, args)
    return 1 if rc else 0


if __name__ == "__main__":
    raise SystemExit(main())
