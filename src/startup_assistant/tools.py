"""Track B: tool definitions, brief validation and rendering.

The six tools the model can call. State changes are recorded in a TurnLog by this code,
not by the model, so the CLI's "what changed" footer can't overclaim.
"""

import difflib
import json
import re
from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from pydantic import BaseModel, ValidationError

from startup_assistant import checker
from startup_assistant.briefs import DEFAULT_CAMPAIGN, BriefStore, campaign_key
from startup_assistant.contracts import BriefDraft, BriefRecord
from startup_assistant.knowledge import KnowledgeStore
from startup_assistant.seed import SEED_PROFILE

SERVER_NAME = "harbordesk"
TOOL_NAMES: list[str] = [
    f"mcp__{SERVER_NAME}__update_company_knowledge",
    f"mcp__{SERVER_NAME}__save_brief",
    f"mcp__{SERVER_NAME}__get_latest_brief",
    f"mcp__{SERVER_NAME}__list_briefs",
    f"mcp__{SERVER_NAME}__get_brief",
    f"mcp__{SERVER_NAME}__compare_briefs",
]

CHECK_SKIPPED_NOTE = "Note: the AI brief check could not run; saved after the code checks only."
# After this many AI-checker rejections in one turn, the next attempt is saved with the
# checker's points attached, so a checker that keeps (wrongly) objecting can't burn the turn.
MAX_CHECKER_REJECTIONS = 2

MAX_EMAIL_WORDS = 150

_PRICE_AMOUNT = re.compile(r"\$|\d+\s*(?:/|per)\s*mo", re.IGNORECASE)
_PRICE_WORD = re.compile(r"\bpric(?:e|es|ed|ing)\b", re.IGNORECASE)
_COMMERCIAL_TERMS = re.compile(r"\bcommercial\s+terms?\b", re.IGNORECASE)
# Only claims about reduction: "cuts ... in half", "half the time", "halved", "50%".
# Plain uses ("half-day workshop", "second half of Q1") are fine.
_HALF_CLAIM = re.compile(
    r"\b(?:cuts?|cutting|reduc\w+|slash\w*|sav(?:es?|ing))\b[^.!?]{0,80}?\b(?:in|by)\s+half\b"
    r"|\bhalf\s+the\s+time\b"
    r"|\bhalv\w*"
    r"|\b50\s?(?:%|percent)",
    re.IGNORECASE,
)


class TurnLog(BaseModel):
    user_text: str = ""
    actions: list[str] = []
    artifacts: list[str] = []
    # Copies added by get_latest_brief/get_brief this turn; save_brief drops them from `artifacts`.
    retrieved: list[str] = []
    # AI-checker rejections of save_brief in this turn.
    checker_rejections: int = 0

    def start(self, user_text: str) -> None:
        """Begin a turn. Resets in place (clear(), not new lists): the tool handlers hold
        references to these lists."""
        self.user_text = user_text
        self.actions.clear()
        self.artifacts.clear()
        self.retrieved.clear()
        self.checker_rejections = 0


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
        if pricing_restricted and (
            _PRICE_AMOUNT.search(text)
            or _PRICE_WORD.search(text)
            or _COMMERCIAL_TERMS.search(text)
        ):
            errors.append(
                f"{label}: pricing is under review and must be left out of campaign materials "
                "(no dollar amounts, no mention of price, pricing or commercial terms)."
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
    """`latest_version` is the newest version in the record's own campaign."""
    status = (
        "CURRENT" if record.version >= latest_version else f"superseded by v{latest_version}"
    )
    origin = f"revises v{record.revises}" if record.revises is not None else "new"
    return (
        f"Brief \"{record.campaign}\" v{record.version} — {status} · {origin} · "
        f"knowledge v{record.knowledge_version} · {record.created_at}"
    )


def brief_index(briefs: BriefStore) -> str:
    """Saved briefs grouped by campaign, one line each; used by list_briefs and every turn."""
    records = briefs.list()
    if not records:
        return "No briefs saved yet."
    sections = []
    for campaign in briefs.campaigns():
        in_campaign = briefs.list(campaign)
        latest = in_campaign[-1].version
        lines = [f"Campaign \"{campaign}\":"]
        for r in in_campaign:
            origin = f"revised (revises v{r.revises})" if r.kind == "revised" else "created"
            status = "CURRENT" if r.version == latest else f"superseded by v{latest}"
            lines.append(
                f"- v{r.version} · {status} · {origin} · {r.created_at} · "
                f"\"{r.draft.title}\" · written against knowledge v{r.knowledge_version}"
            )
        sections.append("\n".join(lines))
    if len(sections) > 1:
        last = records[-1]
        sections.append(f"Most recently saved: \"{last.campaign}\" v{last.version}.")
    return "\n\n".join(sections)


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


_CAMPAIGN_PROP: dict[str, Any] = {
    "type": "string",
    "description": f'Campaign name (case-insensitive), e.g. "{DEFAULT_CAMPAIGN}".',
}

SAVE_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "draft": _draft_schema(),
        "campaign": {
            "type": "string",
            "description": (
                f'Campaign to save under (case-insensitive). Defaults to "{DEFAULT_CAMPAIGN}". '
                "A name not used before starts a new campaign at v1."
            ),
        },
        "revises": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": (
                "Version number this brief revises, in the same campaign. Omit or null for a "
                "new brief."
            ),
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

_READ_CAMPAIGN_PROP: dict[str, Any] = {
    "type": "string",
    "description": (
        "Campaign name (case-insensitive). Omit to use the campaign of the most recently saved "
        "brief."
    ),
}

GET_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "version": {"type": "integer", "description": "The brief version number to fetch."},
        "campaign": _READ_CAMPAIGN_PROP,
    },
    "required": ["version"],
}

GET_LATEST_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "campaign": {
            "type": "string",
            "description": (
                "Campaign name (case-insensitive). Omit for the most recently saved brief in "
                "any campaign."
            ),
        },
    },
}

COMPARE_BRIEFS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "from_version": {"type": "integer", "description": "The older version, e.g. 1."},
        "to_version": {"type": "integer", "description": "The newer version, e.g. 2."},
        "campaign": _READ_CAMPAIGN_PROP,
    },
    "required": ["from_version", "to_version"],
}

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


def _diff_fence(diff: str) -> str:
    """A backtick fence longer than any backtick run in the diff, so stored code blocks
    can't close it early."""
    longest = max((len(run) for run in re.findall(r"`+", diff)), default=0)
    return "`" * max(3, longest + 1)


def make_tools(
    knowledge: KnowledgeStore, briefs: BriefStore, turn: TurnLog
) -> dict[str, SdkMcpTool[Any]]:
    """The six tools, keyed by short name. Handlers close over the stores and the TurnLog."""
    retrieved = turn.retrieved

    def display_name(campaign: str) -> str:
        """The stored display name for a campaign, or the cleaned-up name if it has none yet."""
        key = campaign_key(campaign)
        return next((c for c in briefs.campaigns() if campaign_key(c) == key), campaign.strip())

    def requested_campaign(args: dict[str, Any]) -> str | None:
        value = args.get("campaign")
        if value is None:
            return None
        return str(value).strip() or None

    def read_campaign(args: dict[str, Any]) -> str:
        """For reads: the named campaign, else the one the most recent brief was saved in."""
        named = requested_campaign(args)
        if named is not None:
            return display_name(named)
        latest = briefs.latest()
        return latest.campaign if latest is not None else DEFAULT_CAMPAIGN

    def campaign_list() -> str:
        return ", ".join(f'"{c}"' for c in briefs.campaigns())

    def latest_version_in(campaign: str) -> int:
        latest = briefs.latest(campaign)
        return latest.version if latest is not None else 0

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
            names = ", ".join(
                f'"{b.campaign}" v{b.version} (knowledge v{b.knowledge_version})' for b in stale
            )
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
        "Validate and save a campaign brief as a new version in a campaign (default "
        f'"{DEFAULT_CAMPAIGN}"; each campaign numbers its own versions). Use for a new brief, '
        "or with `revises` set to the version you revised in the same campaign (call "
        "get_latest_brief first). The brief is rejected and nothing is saved if the email body "
        "exceeds 150 words, there are not exactly 2 channels, it makes any 'half'/50% claim, "
        "or it mentions pricing or commercial terms while pricing is restricted; an AI review "
        "against company knowledge can also reject it. On rejection, fix the listed problems "
        "and call again.",
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
        named = requested_campaign(args)
        if named is None and revises is not None:
            campaign = read_campaign(args)  # a revision without a campaign: the current one
        else:
            campaign = display_name(named or DEFAULT_CAMPAIGN)
        errors = validate_brief(draft, knowledge.pricing_restricted)
        if revises is not None and briefs.get(revises, campaign) is None:
            elsewhere = [f'"{c}"' for c in briefs.campaigns() if briefs.get(revises, c)]
            hint = (
                f" v{revises} exists in {', '.join(elsewhere)}; pass that campaign to revise "
                "it there."
                if elsewhere
                else ""
            )
            errors.append(
                f'revises={revises}: campaign "{campaign}" has no saved brief v{revises}.{hint}'
            )
        if errors:
            return _text("Brief NOT saved. Fix and retry:\n- " + "\n- ".join(errors), True)

        check_note = ""
        if checker.checker_enabled():
            try:
                problems = await checker.check_brief(
                    draft, knowledge.render(), knowledge.pricing_restricted
                )
            except Exception:  # the contract says it never raises; fail open like None if it does
                problems = None
            if problems and turn.checker_rejections < MAX_CHECKER_REJECTIONS:
                turn.checker_rejections += 1
                return _text(
                    "Brief check found problems:\n- "
                    + "\n- ".join(problems)
                    + "\n\nBrief NOT saved. Fix these problems and call save_brief again.",
                    True,
                )
            if problems:
                points = "; ".join(p.rstrip(".") for p in problems)
                check_note = (
                    f"\n\nThe AI brief check still reported: {points}. Saved after "
                    f"{MAX_CHECKER_REJECTIONS} rejected attempts; review these points."
                )
            elif problems is None:
                check_note = f"\n\n{CHECK_SKIPPED_NOTE}"

        markdown = render_brief_markdown(draft)
        try:
            record = briefs.save(
                draft=draft,
                markdown=markdown,
                kind="revised" if revises is not None else "created",
                revises=revises,
                knowledge_version=knowledge.version,
                request=turn.user_text,
                campaign=campaign,
            )
        except ValueError as exc:
            return _text(f"Brief NOT saved. {exc}", True)
        # Copies fetched by get_latest_brief/get_brief earlier in this turn (e.g. to revise) aren't
        # what the founder asked to see once a new version exists. This also drops a v1 the
        # founder asked to see in the same turn ("show me v1 and draft a new brief"): known, kept.
        turn.artifacts[:] = [a for a in turn.artifacts if a not in retrieved]
        retrieved.clear()
        origin = f"revises v{revises}" if revises is not None else "new"
        turn.actions.append(f'Brief "{record.campaign}" v{record.version} saved ({origin})')
        turn.artifacts.append(render_record_header(record, record.version) + "\n\n" + markdown)
        return _text(
            f'Saved brief "{record.campaign}" v{record.version} ({origin}), written against '
            f"knowledge v{record.knowledge_version}. The full brief is shown to the founder "
            "below your reply, so don't repeat it; summarise briefly." + check_note
        )

    @tool(
        "get_latest_brief",
        "Fetch the latest saved campaign brief exactly as stored. It is shown to the founder "
        "verbatim. Use for 'show me the brief' requests and before revising a brief. Without "
        "`campaign` it returns the most recently saved brief in any campaign.",
        GET_LATEST_BRIEF_SCHEMA,
    )
    async def get_latest_brief(args: dict[str, Any]) -> dict[str, Any]:
        named = requested_campaign(args)
        if named is not None:
            record = briefs.latest(named)
            if record is None:
                known = campaign_list()
                return _text(
                    f'No brief saved in campaign "{named}".'
                    + (f" Saved campaigns: {known}." if known else " No brief saved yet.")
                )
        else:
            record = briefs.latest()
            if record is None:
                return _text("No brief saved yet.")
        header = render_record_header(record, record.version)
        artifact = header + "\n\n" + record.markdown
        turn.artifacts.append(artifact)
        retrieved.append(artifact)
        older = record.version - 1
        note = (
            f' {older} older version(s) exist in "{record.campaign}".' if older > 0 else ""
        )
        others = [c for c in briefs.campaigns() if c != record.campaign]
        if others:
            listed = ", ".join(f'"{c}" (latest v{latest_version_in(c)})' for c in others)
            note += (
                f" Other campaigns also have briefs: {listed}. Tell the founder this is the "
                f'"{record.campaign}" brief and that the others exist.'
            )
        return _text(
            f"{artifact}\n\n(This stored brief is shown to the founder verbatim below your "
            f"reply; don't reprint it.{note})"
        )

    @tool(
        "get_brief",
        "Fetch a specific saved campaign brief version exactly as stored. It is shown to the "
        "founder verbatim. Use when the founder asks for a particular, older or previous "
        "version (see list_briefs for version numbers; versions are numbered per campaign).",
        GET_BRIEF_SCHEMA,
    )
    async def get_brief(args: dict[str, Any]) -> dict[str, Any]:
        version = int(args["version"])
        campaign = read_campaign(args)
        record = briefs.get(version, campaign)
        if record is None:
            return _text(f'No brief v{version} saved. (Looked in campaign "{campaign}".)')
        artifact = (
            render_record_header(record, latest_version_in(record.campaign))
            + "\n\n"
            + record.markdown
        )
        turn.artifacts.append(artifact)
        retrieved.append(artifact)
        return _text(
            f"{artifact}\n\n(This stored brief is shown to the founder verbatim below your "
            "reply; don't reprint it.)"
        )

    @tool(
        "list_briefs",
        "List every saved brief version, grouped by campaign: kind, date, title, knowledge "
        "version it was written against.",
        _EMPTY_SCHEMA,
    )
    async def list_briefs(args: dict[str, Any]) -> dict[str, Any]:
        return _text(brief_index(briefs))

    @tool(
        "compare_briefs",
        "Show what changed between two saved versions of a campaign's brief. The app builds a "
        "line-by-line diff of the stored briefs and shows it to the founder verbatim. Use for "
        "'what changed between v1 and v2' requests.",
        COMPARE_BRIEFS_SCHEMA,
    )
    async def compare_briefs(args: dict[str, Any]) -> dict[str, Any]:
        a, b = int(args["from_version"]), int(args["to_version"])
        campaign = read_campaign(args)
        old, new = briefs.get(a, campaign), briefs.get(b, campaign)
        missing = [f"v{v}" for v, r in ((a, old), (b, new)) if r is None]
        if old is None or new is None:
            return _text(
                f'Cannot compare: campaign "{campaign}" has no saved brief '
                f"{' or '.join(missing)}. Check list_briefs for the version numbers.",
                True,
            )
        diff = "\n".join(
            difflib.unified_diff(
                old.markdown.splitlines(),
                new.markdown.splitlines(),
                fromfile=f"v{a}",
                tofile=f"v{b}",
                lineterm="",
            )
        )
        title = f'Changes in "{old.campaign}": v{a} → v{b}'
        if diff:
            fence = _diff_fence(diff)
            artifact = f"{title}\n\n{fence}diff\n{diff}\n{fence}"
        else:
            artifact = f"{title}\n\nNo differences: the two stored briefs are identical."
        turn.artifacts.append(artifact)
        return _text(
            f"{artifact}\n\n(This diff is shown to the founder verbatim below your reply; don't "
            "reprint it. You may add a one-paragraph summary of what changed.)"
        )

    return {
        t.name: t
        for t in (
            update_company_knowledge,
            save_brief,
            get_latest_brief,
            list_briefs,
            get_brief,
            compare_briefs,
        )
    }


def build_server(knowledge: KnowledgeStore, briefs: BriefStore, turn: TurnLog):
    tools = make_tools(knowledge, briefs, turn)
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=list(tools.values()))
