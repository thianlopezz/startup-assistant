"""AI review of a brief before it is saved: a second, tool-less model call that compares the
brief with company knowledge and lists rule violations the keyword checks can't see."""

import asyncio
import contextlib
import json
import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from startup_assistant.contracts import BriefDraft

DEFAULT_CHECK_MODEL = "claude-sonnet-5-5"
TIMEOUT_S = 60

CHECKER_SYSTEM_PROMPT = """\
You are a strict compliance reviewer for marketing briefs written for a startup. You receive the \
company's current knowledge (profile and marketing rules), whether pricing is restricted, and a \
draft campaign brief as JSON. Find real rule violations only.

Flag a problem when the brief:
- contains testimonials, customer names, quotes or statistics that are not in the knowledge;
- claims capabilities or integrations that are not in the knowledge (integrations that are only \
"under development" must not be promoted);
- makes any time-saving or "half"-style performance claim (for example "cuts onboarding time in \
half", "saves X hours", "X% faster");
- presents channels as proven or best-performing rather than as proposals (there is no \
channel performance data);
- describes an audience or buyer that contradicts the current knowledge;
- while pricing is restricted: mentions or hints at price, cost to the customer, commercial \
terms, discounts, free trials, or even that pricing or commercial terms were left out or are \
under review. The brief must simply say nothing about it.

Do NOT flag style or wording preferences, tone, or length. Assumptions and open questions that \
are clearly labelled as such are fine, as long as they do not break a rule above. Use the \
knowledge text as the only source of truth; the latest value of a field wins.

Answer with ONLY a JSON object, no prose and no code fence:
{"problems": ["<field>: <what is wrong and why>", ...]}
Use the brief's field name (title, audience, buyer, main_message, channels, email_subject, \
email_body, assumptions, open_questions). If there are no violations answer {"problems": []}."""


def checker_enabled() -> bool:
    """False when ASSISTANT_BRIEF_CHECK is 0, false or off."""
    return os.environ.get("ASSISTANT_BRIEF_CHECK", "").strip().lower() not in {"0", "false", "off"}


def build_prompt(draft: BriefDraft, knowledge_text: str, pricing_restricted: bool) -> str:
    return (
        "COMPANY KNOWLEDGE\n"
        f"{knowledge_text}\n\n"
        f"PRICING RESTRICTED: {'yes' if pricing_restricted else 'no'}\n\n"
        "BRIEF (JSON)\n"
        f"{draft.model_dump_json(indent=2)}\n\n"
        'Respond with only the JSON object {"problems": [...]}.'
    )


async def _ask(prompt: str, system: str, model: str) -> str:
    """One tool-less model call; returns the text of the answer. Tests monkeypatch this."""
    options = ClaudeAgentOptions(
        system_prompt=system,
        tools=[],  # no built-in Claude Code tools
        strict_mcp_config=True,  # ignore any MCP servers configured on this machine
        setting_sources=[],  # don't load user/project settings or CLAUDE.md
        permission_mode="dontAsk",
        max_turns=1,
        model=model,
    )
    parts: list[str] = []
    result_text: str | None = None
    # aclosing: on timeout or cancellation, close the stream so the `claude` subprocess exits.
    async with contextlib.aclosing(query(prompt=prompt, options=options)) as stream:
        async for message in stream:
            if isinstance(message, AssistantMessage):
                parts += [b.text for b in message.content if isinstance(b, TextBlock)]
            elif isinstance(message, ResultMessage):
                if message.is_error:
                    raise RuntimeError(message.subtype)
                result_text = message.result
    return "".join(parts) or result_text or ""


def _parse_problems(text: str) -> list[str] | None:
    """Take the first {...} JSON object in the text; None unless problems is a list of strings."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            problems = obj.get("problems")
            if isinstance(problems, list) and all(isinstance(p, str) for p in problems):
                return problems
            return None
        start = text.find("{", start + 1)
    return None


async def check_brief(
    draft: BriefDraft, knowledge_text: str, pricing_restricted: bool, model: str | None = None
) -> list[str] | None:
    """Problems found in the brief; [] means OK; None means the check could not run (model
    error, timeout, unparseable answer). Never raises; the caller saves on None (fail-open) and
    says the check was skipped."""
    try:
        chosen = model or os.environ.get("ASSISTANT_CHECK_MODEL") or DEFAULT_CHECK_MODEL
        prompt = build_prompt(draft, knowledge_text, pricing_restricted)
        async with asyncio.timeout(TIMEOUT_S):
            answer = await _ask(prompt, CHECKER_SYSTEM_PROMPT, chosen)
        if not isinstance(answer, str):
            return None
        return _parse_problems(answer)
    except Exception:
        return None
