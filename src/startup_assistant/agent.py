"""Track B: the Assistant — one Claude Agent SDK session with four in-process tools."""

import asyncio
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import claude_agent_sdk
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    ResultMessage,
    TextBlock,
)

from startup_assistant.briefs import BriefStore
from startup_assistant.contracts import Reply
from startup_assistant.knowledge import KnowledgeStore
from startup_assistant.prompts import SYSTEM_PROMPT, build_turn_message
from startup_assistant.reply_guard import current_price_claims
from startup_assistant.tools import SERVER_NAME, TOOL_NAMES, TurnLog, brief_index, build_server

MAX_TURNS = 8
DRAIN_TIMEOUT_S = 10
AUTH_CHECK_TIMEOUT_S = 15

PRICING_NOTE = "_Note: pricing is under review; any figure above is not a current price._"
PRICING_FOLLOWUP = (
    'Your last reply presented a price as current: "{claim}". Pricing is under review. '
    "Rewrite your whole reply for the founder so that no price is stated as current; you may "
    "say pricing is under review and mention the old figure only as the previous price. "
    "Do not call any tools."
)


def _find_cli() -> str | None:
    """The Claude Code CLI the SDK will run: its bundled copy, else one on PATH."""
    name = "claude.exe" if platform.system() == "Windows" else "claude"
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / name
    return str(bundled) if bundled.is_file() else shutil.which("claude")


def _cli_auth_status() -> dict | None:
    """`claude auth status` as JSON, or None if it can't be run or read."""
    cli = _find_cli()
    if cli is None:
        return None
    try:
        # Exits 1 when logged out, but still prints the JSON.
        proc = subprocess.run(
            [cli, "auth", "status"], capture_output=True, text=True, timeout=AUTH_CHECK_TIMEOUT_S
        )
        status = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def auth_mode() -> Literal["api-key", "claude-session", "not-logged-in"]:
    """The SDK uses ANTHROPIC_API_KEY when set, otherwise the local Claude Code login. Asks the
    SDK's CLI which one is available; if it can't be asked, assumes the env var / login and
    leaves any problem to the first request."""
    status = _cli_auth_status()
    if status is None:
        return "api-key" if os.environ.get("ANTHROPIC_API_KEY") else "claude-session"
    if not status.get("loggedIn"):
        return "not-logged-in"
    return "api-key" if status.get("authMethod") == "api_key" else "claude-session"


class Assistant:
    def __init__(self, data_dir: Path, model: str | None = None):
        self.data_dir = Path(data_dir)
        self.model = model or os.environ.get("ASSISTANT_MODEL") or None
        self.turn = TurnLog()
        self.knowledge: KnowledgeStore | None = None
        self.briefs: BriefStore | None = None
        self._client: ClaudeSDKClient | None = None
        # Knowledge version the model has already seen in full in this client session.
        self._sent_knowledge_version: int | None = None

    def _options(self) -> ClaudeAgentOptions:
        server = build_server(self.knowledge, self.briefs, self.turn)
        return ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={SERVER_NAME: server},
            strict_mcp_config=True,  # ignore any other MCP servers configured on this machine
            tools=[],  # no built-in Claude Code tools (Bash, Read, Write, WebSearch, ...)
            allowed_tools=TOOL_NAMES,
            setting_sources=[],  # don't load user/project settings or CLAUDE.md
            permission_mode="dontAsk",  # never prompt; anything not pre-approved is denied
            max_turns=MAX_TURNS,
            model=self.model,
            hooks={"PreCompact": [HookMatcher(hooks=[self._on_pre_compact])]},
        )

    async def _on_pre_compact(
        self, input: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        """Compaction may summarise away the full knowledge block we sent earlier, so the next
        turn must resend it rather than say "Unchanged since vN"."""
        self._sent_knowledge_version = None
        return {}

    def _make_client(self) -> ClaudeSDKClient:
        """Seam for tests: they return a fake client here."""
        return ClaudeSDKClient(options=self._options())

    async def __aenter__(self) -> "Assistant":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge = KnowledgeStore(self.data_dir / "knowledge.json")
        self.briefs = BriefStore(self.data_dir / "briefs.json")
        self._client = self._make_client()
        self._sent_knowledge_version = None
        await self._client.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def _abort_turn(self) -> None:
        """Best effort: stop the in-flight turn and drain its messages up to the ResultMessage,
        so they don't leak into the next turn. Never raises."""
        client = self._client
        if client is None:
            return
        try:
            async with asyncio.timeout(DRAIN_TIMEOUT_S):
                await client.interrupt()
                async for _ in client.receive_response():
                    pass
        except BaseException:
            pass

    async def handle(self, text: str) -> Reply:
        if self._client is None:
            raise RuntimeError("Assistant is not connected; use `async with Assistant(...)`.")
        # Reset in place: the tool handlers hold a reference to this TurnLog.
        self.turn.user_text = text
        self.turn.actions.clear()
        self.turn.artifacts.clear()

        # Send the full knowledge only when the model hasn't seen this version yet (first turn,
        # after a change, including one a tool made last turn, or after an aborted turn).
        version = self.knowledge.version
        knowledge_text = None if version == self._sent_knowledge_version else self.knowledge.render()
        try:
            # Set before query(): a PreCompact hook may reset it while the turn runs.
            self._sent_knowledge_version = version
            await self._client.query(
                build_turn_message(knowledge_text, brief_index(self.briefs), text, version)
            )
            parts, _ = await self._collect()
        except BaseException:  # includes CancelledError / KeyboardInterrupt
            self._sent_knowledge_version = None  # unsure what the model saw; resend next turn
            await self._abort_turn()
            raise

        reply_text = self._join(parts)
        artifacts, actions = list(self.turn.artifacts), list(self.turn.actions)
        if self.knowledge.pricing_restricted:
            reply_text = await self._guard_pricing(reply_text)
            # The rewrite is told not to call tools but can't be stopped. Anything it did
            # must reach the footer, which must never under-report.
            actions += [a for a in self.turn.actions if a not in actions]
            artifacts += [a for a in self.turn.artifacts if a not in artifacts]

        return Reply(text=reply_text, artifacts=artifacts, actions=actions)

    @staticmethod
    def _join(parts: list[str]) -> str:
        return "\n\n".join(p.strip() for p in parts if p.strip())

    async def _collect(self) -> tuple[list[str], bool]:
        """Read one response: its text parts, and whether the model/stream reported an error."""
        parts: list[str] = []
        failed = False
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                if message.error:
                    failed = True
                    parts.append(f"[Model error: {message.error}]")
                parts += [b.text for b in message.content if isinstance(b, TextBlock)]
            elif isinstance(message, ResultMessage) and message.is_error:
                failed = True
                detail = "; ".join(message.errors or []) or message.subtype
                parts.append(f"[The request did not finish cleanly: {detail}]")
        return parts, failed

    async def _guard_pricing(self, text: str) -> str:
        """Pricing is under review, so a chat reply must not state a price as current. Send at
        most one corrective follow-up. It is not a knowledge-sending turn, so it leaves
        `_sent_knowledge_version` alone."""
        claims = current_price_claims(text)
        if not claims:
            return text
        try:
            await self._client.query(PRICING_FOLLOWUP.format(claim=claims[0]))
            parts, failed = await self._collect()
        except Exception:
            await self._abort_turn()
            return f"{text}\n\n{PRICING_NOTE}"
        except BaseException:
            self._sent_knowledge_version = None
            await self._abort_turn()
            raise
        rewrite = self._join(parts)
        if failed or not rewrite:
            return f"{text}\n\n{PRICING_NOTE}"
        if current_price_claims(rewrite):
            return f"{rewrite}\n\n{PRICING_NOTE}"
        return rewrite
