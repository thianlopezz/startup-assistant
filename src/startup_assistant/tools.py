"""Track B: tool definitions, brief validation and rendering.

The four tools the model can call. State changes are recorded in a TurnLog by this code,
not by the model, so the CLI's "what changed" footer can't overclaim.
"""

import json
import re
from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from pydantic import BaseModel, ValidationError

from startup_assistant.briefs import BriefStore
from startup_assistant.contracts import BriefDraft, BriefRecord
from startup_assistant.knowledge import KnowledgeStore
from startup_assistant.seed import SEED_PROFILE

SERVER_NAME = "harbordesk"
TOOL_NAMES: list[str] = [
    f"mcp__{SERVER_NAME}__update_company_knowledge",
    f"mcp__{SERVER_NAME}__save_brief",
    f"mcp__{SERVER_NAME}__get_latest_brief",
    f"mcp__{SERVER_NAME}__list_briefs",
]

MAX_EMAIL_WORDS = 150

_PRICE_AMOUNT = re.compile(r"\$\s?\d")
_PRICE_WORD = re.compile(r"\bpric(?:e|es|ed|ing)\b", re.IGNORECASE)
_HALF_CLAIM = re.compile(r"\bin half\b|\bhalv(?:e|es|ed|ing)\b|\b50\s?%", re.IGNORECASE)


class TurnLog(BaseModel):
    user_text: str = ""
    actions: list[str] = []
    artifacts: list[str] = []


def word_count(text: str) -> int:
    return len(text.split())


def _draft_texts(draft: BriefDraft) -> list[tuple[str, str]]:
    """(field label, text) for every string the brief contains."""
    out: list[tuple[str, str]] = [
        ("title", draft.title),
        ("audience", draft.audience),
        ("buyer", draft.buyer),
        ("main_message", draft.main_message),
        ("email_subject", draft.email_subject),
        ("email_body", draft.email_body),
    ]
    for i, ch in enumerate(draft.channels, 1):
        out += [(f"channels[{i}].name", ch.name), (f"channels[{i}].reason", ch.reason)]
    out += [(f"assumptions[{i}]", a) for i, a in enumerate(draft.assumptions, 1)]
    out += [(f"open_questions[{i}]", q) for i, q in enumerate(draft.open_questions, 1)]
    return out


def validate_brief(draft: BriefDraft, pricing_restricted: bool) -> list[str]:
    errors: list[str] = []
    if len(draft.channels) != 2:
        errors.append(f"Exactly 2 channels are required; got {len(draft.channels)}.")
    n = word_count(draft.email_body)
    if n > MAX_EMAIL_WORDS:
        errors.append(
            f"email_body is {n} words; the limit is {MAX_EMAIL_WORDS}. Shorten it."
        )
    for label, text in _draft_texts(draft):
        if _HALF_CLAIM.search(text):
            errors.append(
                f"{label}: the 'cuts onboarding time in half' claim (or any 'half'/50% claim) "
                "has no supporting evidence and must not be used."
            )
        if pricing_restricted and (_PRICE_AMOUNT.search(text) or _PRICE_WORD.search(text)):
            errors.append(
                f"{label}: pricing is under review and must be left out of campaign materials "
                "(no dollar amounts, no mention of price or pricing)."
            )
    return errors


def render_brief_markdown(draft: BriefDraft) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- None."

    channels = "\n".join(
        f"{i}. **{ch.name}** — {ch.reason}" for i, ch in enumerate(draft.channels, 1)
    )
    return (
        f"# {draft.title}\n\n"
        f"## Audience\n\n{draft.audience}\n\n"
        f"## Buyer\n\n{draft.buyer}\n\n"
        f"## Main message\n\n{draft.main_message}\n\n"
        f"## Recommended channels (proposals)\n\n{channels}\n\n"
        f"## Draft email\n\n**Subject:** {draft.email_subject}\n\n{draft.email_body}\n\n"
        f"_Draft for review — not sent._\n\n"
        f"## Assumptions\n\n{bullets(draft.assumptions)}\n\n"
        f"## Open questions\n\n{bullets(draft.open_questions)}\n"
    )


def render_record_header(record: BriefRecord, latest_version: int) -> str:
    status = (
        "CURRENT" if record.version >= latest_version else f"superseded by v{latest_version}"
    )
    origin = f"revises v{record.revises}" if record.revises is not None else "new"
    return (
        f"Brief v{record.version} — {status} · {origin} · "
        f"knowledge v{record.knowledge_version} · {record.created_at}"
    )


def brief_index(briefs: BriefStore) -> str:
    """One line per saved brief; used by list_briefs and the per-turn context."""
    records = briefs.list()
    if not records:
        return "No briefs saved yet."
    latest = records[-1].version
    lines = []
    for r in records:
        origin = f"revised (revises v{r.revises})" if r.kind == "revised" else "created"
        status = "CURRENT" if r.version == latest else f"superseded by v{latest}"
        lines.append(
            f"- v{r.version} · {status} · {origin} · {r.created_at} · "
            f"\"{r.draft.title}\" · written against knowledge v{r.knowledge_version}"
        )
    return "\n".join(lines)


# --- tool input schemas ---------------------------------------------------------------


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve pydantic's local $defs/$ref so the tool schema is a single flat object."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _draft_schema() -> dict[str, Any]:
    schema = _inline_refs(BriefDraft.model_json_schema())
    props = schema["properties"]
    props["channels"]["description"] = (
        "Exactly 2 proposed channels, each with a reason. Proposals, not proven performers."
    )
    props["email_body"]["description"] = f"Plain-text email body, at most {MAX_EMAIL_WORDS} words."
    props["audience"]["description"] = "Who we target (company profile)."
    props["buyer"]["description"] = "Who signs off on the purchase."
    return schema


SAVE_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "draft": _draft_schema(),
        "revises": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": "Version number this brief revises. Omit or null for a new brief.",
        },
    },
    "required": ["draft"],
}

UPDATE_KNOWLEDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "One or two sentences: what the founder told us that changes.",
        },
        "field_changes": {
            "type": "object",
            "description": "New values for profile fields that change. Leave out unchanged fields.",
            "properties": {key: {"type": "string"} for key in SEED_PROFILE},
            "additionalProperties": False,
        },
        "new_rules": {
            "type": "array",
            "items": {"type": "string"},
            "description": "New standing instructions for marketing (e.g. what to leave out).",
        },
    },
    "required": ["summary", "field_changes", "new_rules"],
}

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def make_tools(
    knowledge: KnowledgeStore, briefs: BriefStore, turn: TurnLog
) -> dict[str, SdkMcpTool[Any]]:
    """The four tools, keyed by short name. Handlers close over the stores and the TurnLog."""

    @tool(
        "update_company_knowledge",
        "Save new or changed company facts or standing rules the founder states "
        "(e.g. a new target audience, a new buyer, 'leave prices out'). This only changes "
        "company knowledge; it does NOT revise any saved brief.",
        UPDATE_KNOWLEDGE_SCHEMA,
    )
    async def update_company_knowledge(args: dict[str, Any]) -> dict[str, Any]:
        update = knowledge.apply_update(
            source_text=turn.user_text,
            summary=args["summary"],
            field_changes=dict(args.get("field_changes") or {}),
            new_rules=list(args.get("new_rules") or []),
        )
        turn.actions.append(f"Company knowledge updated → v{update.version}")
        stale = [b for b in briefs.list() if b.knowledge_version < update.version]
        if stale:
            names = ", ".join(f"v{b.version} (knowledge v{b.knowledge_version})" for b in stale)
            brief_note = (
                f"No brief was revised. These saved briefs were written against older "
                f"knowledge and are now stale: {names}. Tell the founder this and offer to "
                f"revise; do not say any brief was updated."
            )
        else:
            brief_note = "There are no saved briefs, so nothing is stale."
        return _text(f"Company knowledge saved as v{update.version}. {brief_note}")

    @tool(
        "save_brief",
        "Validate and save a campaign brief as a new version. Use for a new brief, or with "
        "`revises` set to the version you revised (call get_latest_brief first). The brief "
        "is rejected and nothing is saved if the email body exceeds 150 words, there are not "
        "exactly 2 channels, it repeats the unsupported 'in half' claim, or it mentions "
        "pricing while pricing is restricted. On rejection, fix the listed problems and "
        "call again.",
        SAVE_BRIEF_SCHEMA,
    )
    async def save_brief(args: dict[str, Any]) -> dict[str, Any]:
        raw = args.get("draft")
        if isinstance(raw, str):  # some clients send nested objects as JSON strings
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return _text("Brief NOT saved. `draft` must be an object.", is_error=True)
        try:
            draft = BriefDraft.model_validate(raw)
        except ValidationError as exc:
            problems = [
                f"{'.'.join(str(p) for p in e['loc']) or 'draft'}: {e['msg']}"
                for e in exc.errors()
            ]
            return _text("Brief NOT saved. Fix and retry:\n- " + "\n- ".join(problems), True)

        revises = args.get("revises")
        errors = validate_brief(draft, knowledge.pricing_restricted)
        if revises is not None and briefs.get(revises) is None:
            errors.append(f"revises={revises}: there is no saved brief v{revises}.")
        if errors:
            return _text("Brief NOT saved. Fix and retry:\n- " + "\n- ".join(errors), True)

        markdown = render_brief_markdown(draft)
        record = briefs.save(
            draft=draft,
            markdown=markdown,
            kind="revised" if revises is not None else "created",
            revises=revises,
            knowledge_version=knowledge.version,
            request=turn.user_text,
        )
        if revises is not None:
            # The copy of the old version fetched for revising isn't what the founder asked to see.
            prefix = f"Brief v{revises} — "
            turn.artifacts[:] = [a for a in turn.artifacts if not a.startswith(prefix)]
            turn.actions.append(f"Brief v{record.version} saved (revises v{revises})")
        else:
            turn.actions.append(f"Brief v{record.version} saved (new)")
        turn.artifacts.append(render_record_header(record, record.version) + "\n\n" + markdown)
        return _text(
            f"Saved brief v{record.version}"
            + (f" (revises v{revises})" if revises is not None else " (new)")
            + f", written against knowledge v{record.knowledge_version}. The full brief is "
            "shown to the founder below your reply, so don't repeat it; summarise briefly."
        )

    @tool(
        "get_latest_brief",
        "Fetch the latest saved campaign brief exactly as stored. It is shown to the founder "
        "verbatim. Use for 'show me the brief' requests and before revising a brief.",
        _EMPTY_SCHEMA,
    )
    async def get_latest_brief(args: dict[str, Any]) -> dict[str, Any]:
        record = briefs.latest()
        if record is None:
            return _text("No brief saved yet.")
        header = render_record_header(record, record.version)
        artifact = header + "\n\n" + record.markdown
        turn.artifacts.append(artifact)
        older = record.version - 1
        note = f" {older} older version(s) exist." if older > 0 else ""
        return _text(
            f"{artifact}\n\n(This stored brief is shown to the founder verbatim below your "
            f"reply; don't reprint it.{note})"
        )

    @tool(
        "list_briefs",
        "List every saved brief version: kind, date, title, knowledge version it was written "
        "against.",
        _EMPTY_SCHEMA,
    )
    async def list_briefs(args: dict[str, Any]) -> dict[str, Any]:
        return _text(brief_index(briefs))

    return {
        t.name: t for t in (update_company_knowledge, save_brief, get_latest_brief, list_briefs)
    }


def build_server(knowledge: KnowledgeStore, briefs: BriefStore, turn: TurnLog):
    tools = make_tools(knowledge, briefs, turn)
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=list(tools.values()))
