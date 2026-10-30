# HarborDesk Startup Assistant — Design

Date: 2026-10-30
Status: approved direction, pending doc review

## Intent

A take-home assessment (official timebox: 3 hours; Thian is targeting ~2 hours of build time
inside that window, recorded). Build a small assistant a startup founder talks to across
separate requests. It answers questions from company knowledge, creates and revises marketing
campaign briefs, absorbs new company information, and retrieves saved work — deciding on its own
which of those a request calls for.

Reviewers grade prioritization, a small working product, honesty about gaps, verification, and
AI usage — not polish. A README that lets them run it and exercise each capability is required.

## Goals (what the reviewers expect to see)

1. Natural language in, no manual operation selection. Wording in review may differ from examples.
2. Grounded answers: separate known facts from assumptions; say when information is missing.
3. Initial brief with every section: audience and buyer, main message, exactly two channels with
   reasons, a draft email of at most 150 words, assumptions / open questions. Saved for later.
4. Founder update (given as its own message) is retained: new audience, new buyer, no pricing in
   campaign materials. A follow-up question about the current audience reflects it.
5. Updating knowledge and revising a brief are distinct. The assistant must never claim it revised
   a brief unless it actually saved a new version.
6. "Update the campaign brief for our new audience. Focus on coordinating onboarding handoffs across
   teams." produces a new saved version: new audience, onboarding-handoff focus, no pricing anywhere.
7. Persistence: knowledge updates and briefs survive an application restart.
8. "Show me the latest campaign brief" returns the stored version verbatim (no regeneration) and
   says which version is current.

## Non-goals

Deployment, polished UI, production infra, crash recovery, concurrent agents, sending email or
publishing anything, multiple agents.

## Anti-goals (failure even if it "works")

- Brief or answer invents testimonials, statistics, integrations, or capabilities.
- Reuses the "cuts onboarding time in half" claim.
- Presents channel choices as proven (there is no channel performance data — they are proposals).
- Mentions pricing after the founder update.
- Says "I updated the brief" after only a knowledge update.
- Retrieval silently generates a new brief.

## Source data (copied from the HarborDesk Company Data page — the seed)

Starting company profile:
- Company: HarborDesk.
- Product: software that helps teams manage customer onboarding.
- Capabilities: shared onboarding checklists, assigned task owners, reminders, and progress reporting.
- Current target customers: agencies and consultancies with 10–50 employees.
- Primary buyer: founder or operations lead.
- Problem: customer onboarding is scattered across email and spreadsheets, causing missed handoffs.
- Main benefit: clearer ownership and visibility throughout onboarding.
- Pricing: starts at $299 per month.
- Brand voice: direct, practical, and friendly. Avoid hype.

Starting marketing notes:
- LinkedIn posts and targeted email outreach have been used previously.
- There is no reliable data showing which channel performs best. Channel recommendations should be
  presented as proposals.
- Prospects have asked about integrations. Integrations are under development; no specific
  integration is approved for marketing.
- An earlier draft claimed HarborDesk "cuts onboarding time in half." There is no supporting
  evidence. Do not reuse that claim.
- Do not invent customer testimonials, performance statistics, or product capabilities. Identify
  assumptions or open questions when information is missing.

Founder update (entered by the user during the demo, NOT seeded):
> "We're shifting our target to B2B software companies with 100–500 employees. The buyer is the Head
> of Customer Success. Remember this as our target going forward.
> Pricing is under review, so leave prices out of campaign materials. Our product capabilities are
> unchanged."

This replaces the default audience and buyer and adds the no-pricing restriction. It does not by
itself ask for a brief revision.

### Seed field keys (fixed in step 0; every track uses these exact keys)

`company`, `product`, `capabilities`, `target_customers`, `primary_buyer`, `problem`,
`main_benefit`, `pricing`, `brand_voice`. Marketing notes are a list of strings (`marketing_notes`),
and rules added by later updates go in the same list.

### Pricing scope (Claude's call)

The restriction covers **campaign materials** (briefs and draft emails), as the founder wrote it.
After the update, `pricing` becomes "Under review — leave out of campaign materials (previously
$299/month)." In chat, a direct pricing question gets that status, not a bare price. `save_brief`
enforces the restriction in code; chat replies rely on the prompt.

## Submission requirements (from the instructions page)

The repo must contain the code, dependencies, example outputs and a concise README covering:
- link to the recording (hosted video or MP4), with the 3-hour cutoff clearly marked
- link to the preserved 3-hour commit
- elapsed working time, plus any recording gaps or technical problems
- a separate section for any work done after the cutoff: what changed, why, how much time, and how
  to reach that version
- what was built and how to set it up and run it
- important assumptions, design decisions and shortcuts
- how the assistant chooses actions and keeps company knowledge separate from saved deliverables
- what was verified and what happened
- anything unfinished and what would come next
- the AI tools and models used
No credentials in the repo. No other report is required. Track C drafts these sections and step 3
fills them in.

## Decided by Thian

- Python.
- Anthropic models via the **Claude Agent SDK** (`claude-agent-sdk`), authenticating with the local
  logged-in Claude Code session by default; if `ANTHROPIC_API_KEY` is set, it is used instead. Same
  code path either way. README documents both.
- Work is split into parallel git worktrees run in separate sessions, then merged.

## Architecture (Claude's calls, approved as a direction)

Command-line chat. One agent per request with four custom in-process tools (SDK MCP server via
`create_sdk_mcp_server` / `@tool`). Built-in Claude Code tools (Bash, Read, Write, WebSearch, …) are
disabled; user/project Claude settings and CLAUDE.md are not loaded (`setting_sources` empty).
Answering a question needs no tool — current knowledge and an index of saved briefs are injected
into every request.

### Package layout

```
pyproject.toml                    # step 0
src/startup_assistant/
  __init__.py                     # step 0
  seed.py                         # step 0 — seed profile + marketing notes as data
  contracts.py                    # step 0 — dataclasses shared by all tracks
  knowledge.py                    # Track A
  briefs.py                       # Track A
  tools.py                        # Track B — tool definitions, validation, brief rendering
  prompts.py                      # Track B — system prompt + per-turn context block
  agent.py                        # Track B — Assistant
  cli.py                          # Track C — REPL entry point
scripts/demo.py                   # Track C — scripted demo, writes examples/
tests/                            # A: store tests; B: tool validation tests
examples/                         # Track C output, committed
README.md                         # Track C draft, finalized in step 3
```

### Shared contracts (written in step 0 as stubs; tracks implement against them)

```python
# contracts.py
@dataclass
class Channel:
    name: str
    reason: str

@dataclass
class BriefDraft:                 # what the model submits to save_brief
    title: str
    audience: str                 # who we target (company profile)
    buyer: str                    # who signs off
    main_message: str
    channels: list[Channel]       # exactly 2
    email_subject: str
    email_body: str               # <= 150 words
    assumptions: list[str]
    open_questions: list[str]

@dataclass
class BriefRecord:                # what BriefStore persists
    version: int                  # 1, 2, 3 … global, monotonically increasing
    created_at: str               # ISO 8601
    kind: str                     # "created" | "revised"
    revises: int | None           # version this one revises
    knowledge_version: int        # knowledge version it was written against
    request: str                  # the founder message that triggered it
    draft: BriefDraft
    markdown: str                 # rendered once at save time; retrieval returns exactly this

@dataclass
class KnowledgeUpdate:
    version: int                  # 1, 2, … (0 = seed)
    created_at: str
    source_text: str              # founder's original message, verbatim
    summary: str
    field_changes: dict[str, str] # e.g. {"target_customers": "...", "primary_buyer": "...",
                                  #       "pricing": "Under review — do not mention in campaign materials."}
    new_rules: list[str]          # e.g. ["Leave prices out of campaign materials."]

@dataclass
class Reply:                      # what Assistant.handle returns to the CLI
    text: str                     # the model's message
    artifacts: list[str]          # verbatim markdown to print (saved/retrieved briefs)
    actions: list[str]            # deterministic log of state changes this turn,
                                  # e.g. "Company knowledge updated → v1",
                                  #      "Brief v2 saved (revises v1)". Empty = nothing changed.
```

```python
# knowledge.py  (Track A)
class KnowledgeStore:
    def __init__(self, path: Path): ...      # creates file from seed.py on first use
    @property
    def version(self) -> int: ...           # 0 until first update
    def current_profile(self) -> dict[str, str]: ...  # seed profile with field_changes applied in order
    def rules(self) -> list[str]: ...       # seed marketing notes + all new_rules
    def updates(self) -> list[KnowledgeUpdate]: ...
    def apply_update(self, source_text: str, summary: str,
                     field_changes: dict[str, str], new_rules: list[str]) -> KnowledgeUpdate: ...
    def render(self) -> str: ...            # text block for the prompt; marks which fields came
                                            # from which update ("updated in v1")

# briefs.py  (Track A)
class BriefStore:
    def __init__(self, path: Path): ...
    def save(self, draft: BriefDraft, markdown: str, kind: str, revises: int | None,
             knowledge_version: int, request: str) -> BriefRecord: ...
    def latest(self) -> BriefRecord | None: ...
    def get(self, version: int) -> BriefRecord | None: ...
    def list(self) -> list[BriefRecord]: ...
```

```python
# agent.py  (Track B)
class Assistant:
    def __init__(self, data_dir: Path, model: str | None = None): ...
    async def handle(self, text: str) -> Reply: ...
```

Persistence: one JSON file per store under the data dir (default `./data`, gitignored). Writes go
to a temp file then `os.replace` (cheap atomicity; full crash recovery is a non-goal).

### Tools (Track B)

| Tool | Does | Records action |
|---|---|---|
| `update_company_knowledge(summary, field_changes, new_rules)` | `KnowledgeStore.apply_update` with the user's message as `source_text`. Returns new version and the list of saved briefs now based on older knowledge (stale). | "Company knowledge updated → vN" |
| `save_brief(draft, revises?)` | Validates, renders markdown, saves. Rejects (returns error text to the model so it fixes and retries) if: channels ≠ 2; email body > 150 words; any `$` amount or the word "price/pricing" appears while the pricing restriction is active; "half" claim appears. | "Brief vN saved (new)" or "(revises vM)" |
| `get_latest_brief()` | Returns the stored record; appends its stored markdown to `Reply.artifacts` unchanged. | none |
| `list_briefs()` | Version, kind, created_at, title, knowledge_version. | none |

`get_brief(version)` is optional if time allows.

Pricing restriction detection: active when the current profile's `pricing` field has been changed
by an update or any rule mentions leaving prices out. (Builder may simplify, e.g. a flag set by
`field_changes["pricing"]`.)

### Honesty about what changed

- The CLI prints `Reply.actions` after the model's text as a footer, e.g.
  `[Changed: Company knowledge updated → v1]` or `[No saved data changed]`. These come from the tool
  code, not from the model, so the footer can't overclaim.
- The system prompt tells the model: after a knowledge update, say what was saved and that existing
  briefs were *not* revised (name the stale versions) unless the user asks.
- Retrieval: model may add one line of context, but the brief itself is printed from `artifacts`,
  with a header like `Brief v2 — CURRENT (revises v1, written against knowledge v1, 2026-10-30 …)`.
  If older versions exist, say so.

### System prompt essentials (Track B)

- Role: HarborDesk's marketing assistant for the founder. Decide per request: answer, update
  knowledge, create/revise brief, retrieve. When the request is ambiguous between remembering a fact
  and revising a brief, only do what was asked.
- Grounding: use only the knowledge block. Label facts vs assumptions; say what's missing.
- All anti-goals above as explicit rules; brand voice: direct, practical, friendly, no hype.
- Missing info: for briefs, proceed and list assumptions/open questions rather than asking first.
  If asked to retrieve and nothing is saved, say so and offer to create — do not create.
- Revisions: call `get_latest_brief` first, then `save_brief` with `revises` set.

### Per-turn context

Each request is sent as: current knowledge block (`KnowledgeStore.render()`), brief index
(`list_briefs` output), then the founder's message. Conversation continuity within one run uses a
single `ClaudeSDKClient` session; across restarts, state comes only from the stores.

### CLI (Track C)

`python -m startup_assistant` (or `startup-assistant` script). Flags: `--data-dir`, `--reset`
(delete data dir, re-seed), `--model`. Prints model text, then artifacts, then the actions footer.
Exit on `exit`/`quit`/Ctrl-D. Prints which auth mode is in use at startup (session vs API key).

### Demo script (Track C)

`scripts/demo.py --data-dir examples/demo-data` runs the six required interactions in two processes
to show a real restart:

- Process 1: (1) "Who are we targeting, and what problem do we solve for them?" (2) create + save
  the initial brief (3) the founder update verbatim (4) "Who is our current target audience?"
  (5) the revision request.
- Process 2 (fresh start): (6) "Show me the latest campaign brief."

Each turn's input, reply, artifacts, and actions are written to `examples/transcript-<n>.md`. A
`--check` mode runs cheap assertions on the saved data: brief v1 has two channels and email ≤150
words; after the update, knowledge v1 has the new audience/buyer; brief v2 revises v1, mentions
Customer Success, contains no `$`/"price"; retrieval in process 2 returned v2 markdown byte-identical
to the stored one and did not add a brief version.

## Execution plan

| Step | Where | Owner | Time |
|---|---|---|---|
| 0 | `main` | this session | ~10 min: pyproject, package skeleton, `seed.py`, `contracts.py`, stubs for every interface above, `.gitignore`, commit |
| A | worktree `store` | session A | ~25 min |
| B | worktree `agent` | session B | ~35 min |
| C | worktree `cli` | session C | ~25 min |
| 3 | `main` | this session | ~30 min: merge A→B→C, run demo end to end, fix, finalize README, commit, record cutoff |

Tracks code only against step-0 contracts. B and C may use an in-memory fake store until A lands.
Each track commits on its own branch; this session merges.

Decided by Thian: tracks A, B and C run as background subagents started from this session, each
in its own git worktree with a self-contained task brief. This session does step 0, the merges,
the end-to-end demo and the final README, so the whole run is visible in one terminal for the
recording.

## Left to the builders

Exact prompt wording, markdown layout of the rendered brief, JSON file shape, test structure,
venv tooling (pip + venv; `uv` is not installed), how tool-call errors are surfaced to the model,
the default model id.

## Known risks

- Python 3.14 compatibility of `claude-agent-sdk` — check in step 0; fall back to another installed
  Python if needed.
- Agent SDK subprocess startup is a few seconds per client; acceptable.
- Subscription-session auth is for local personal use; the API-key path is the portable option.
