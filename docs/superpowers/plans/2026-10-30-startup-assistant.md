# HarborDesk Startup Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CLI chat assistant for the HarborDesk founder that answers from company knowledge, saves knowledge updates, creates/revises/retrieves versioned campaign briefs, and persists across restarts.

**Architecture:** One Claude Agent SDK client per run with four in-process tools; two JSON-backed pydantic stores (knowledge, briefs); a rich-based REPL; a two-process demo script. Built in four phases: Task 0 on `main`, then tracks A (Tasks 1–2), B (Tasks 3–4), C (Tasks 5–6) in parallel worktrees, then Task 7 on `main`.

**Tech Stack:** Python 3.14, `claude-agent-sdk`, `pydantic` v2, `rich`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-30-startup-assistant-design.md` — read it first; it holds the source data, anti-goals and README requirements.

## Global Constraints

- Package `startup_assistant` under `src/`; venv at `.venv`; run tests with `.venv/bin/pytest -q`.
- Only Task 0 edits `pyproject.toml`. A track that needs another dependency reports it instead of adding it.
- Seed field keys exactly: `company, product, capabilities, target_customers, primary_buyer, problem, main_benefit, pricing, brand_voice`; notes list key `marketing_notes`.
- Model access through `claude-agent-sdk` only. No API key in code or repo; `ANTHROPIC_API_KEY` is used if present, otherwise the local Claude Code login.
- The agent gets only our four tools: built-in Claude Code tools off, `setting_sources=[]`.
- Brief email body ≤ 150 words; exactly 2 channels; never "cuts onboarding time in half"; no price in briefs once pricing is restricted.
- Retrieval prints stored markdown unchanged.
- Each track commits only its own files on its own branch. No edits to other tracks' files beyond the Task 0 stubs it owns.

## Review Focus

1. Founder asks to see the brief before any brief exists → says none is saved, offers to create, does **not** create one (Task 4 prompt rule + Task 6 check that the brief count is unchanged).
2. Knowledge update message phrased casually ("btw our buyer is now…") → still an update, footer shows the change, no brief version added (Task 4 prompt; Task 6 demo asserts brief count unchanged after step 3).
3. Model submits an invalid brief (3 channels / 170-word email / "$299") → tool returns errors, nothing saved, model retries (Task 3 tests).
4. Data dir missing or freshly reset → stores seed themselves, no crash (Task 1 & 2 tests).
5. Restart between revision and retrieval → v2 still current, retrieval adds no version (Task 6 `--check`).

---

### Task 0: Scaffold, contracts, stubs (main, this session)

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/startup_assistant/__init__.py`, `src/startup_assistant/__main__.py`, `src/startup_assistant/seed.py`, `src/startup_assistant/contracts.py`, stubs `knowledge.py`, `briefs.py`, `tools.py`, `prompts.py`, `agent.py`, `cli.py`
- Test: `tests/test_contracts.py`

**Interfaces — Produces:**
- `seed.py`: `SEED_PROFILE: dict[str, str]` (keys above, values verbatim from spec), `SEED_MARKETING_NOTES: list[str]` (5 notes verbatim).
- `contracts.py` (pydantic `BaseModel`s): `Channel(name, reason)`, `BriefDraft(title, audience, buyer, main_message, channels: list[Channel] = Field(min_length=2, max_length=2), email_subject, email_body, assumptions: list[str], open_questions: list[str])`, `BriefRecord(version: int, created_at: str, kind: Literal["created","revised"], revises: int | None, knowledge_version: int, request: str, draft: BriefDraft, markdown: str)`, `KnowledgeUpdate(version: int, created_at: str, source_text: str, summary: str, field_changes: dict[str,str], new_rules: list[str])`, `Reply(text: str, artifacts: list[str] = [], actions: list[str] = [])`.
- Stub classes/functions with the exact signatures from Tasks 1–6, bodies `raise NotImplementedError`.
- `pyproject.toml`: deps `claude-agent-sdk>=0.2.175`, `pydantic>=2`, `rich`; optional `dev = ["pytest"]`; script `startup-assistant = "startup_assistant.cli:main"`; pytest marker `live`.
- `.gitignore`: `.venv/`, `data/`, `__pycache__/`, `*.egg-info/`.

- [ ] **Step 1:** Write `tests/test_contracts.py`: `test_seed_keys` (set of `SEED_PROFILE` keys == the 9 keys; `"$299" in SEED_PROFILE["pricing"]`; `len(SEED_MARKETING_NOTES) == 5`) and `test_brief_requires_two_channels` (`BriefDraft` with 3 channels raises `ValidationError`).
- [ ] **Step 2:** `python3.14 -m venv .venv && .venv/bin/pip install -e '.[dev]'`; the test fails on import.
- [ ] **Step 3:** Write the seed, contracts and stubs.
- [ ] **Step 4:** `.venv/bin/pytest -q` → 2 passed.
- [ ] **Step 5:** Commit `chore: scaffold package, contracts, seed, stubs`.

---

## Track A — worktree, Tasks 1–2

### Task 1: KnowledgeStore

**Files:** Modify `src/startup_assistant/knowledge.py`; Test `tests/test_knowledge.py`

**Interfaces:**
- Consumes: `SEED_PROFILE`, `SEED_MARKETING_NOTES`, `KnowledgeUpdate`.
- Produces: `class KnowledgeStore(path: Path)`, `.version -> int`, `.current_profile() -> dict[str,str]`, `.rules() -> list[str]`, `.updates() -> list[KnowledgeUpdate]`, `.pricing_restricted -> bool` (True once any update's `field_changes` has `"pricing"`), `.apply_update(source_text, summary, field_changes, new_rules) -> KnowledgeUpdate`, `.render() -> str`.

- [ ] **Step 1:** Tests, each using `tmp_path / "knowledge.json"`:
  - `test_fresh_store_is_seed`: version 0, `current_profile() == SEED_PROFILE`, `rules() == SEED_MARKETING_NOTES`, not `pricing_restricted`.
  - `test_apply_update_changes_fields_and_persists`: apply `{"target_customers": "B2B software companies with 100–500 employees", "primary_buyer": "Head of Customer Success", "pricing": "Under review — leave out of campaign materials (previously $299/month)"}` with one rule; returned `.version == 1`; a **new** `KnowledgeStore` on the same path has version 1, the new buyer, `pricing_restricted` True, and the rule at the end of `rules()`.
  - `test_unknown_field_is_kept`: a key outside the seed (e.g. `"integrations"`) appears in `current_profile()`.
  - `test_render_marks_updated_fields`: after one update, `render()` contains "Head of Customer Success" and "v1", and does not contain "founder or operations lead" as the current buyer value.
- [ ] **Step 2:** Run → fail (NotImplementedError).
- [ ] **Step 3:** Implement. One file model `KnowledgeFile(updates: list[KnowledgeUpdate])`; profile = seed with updates applied in order. Write via temp file + `os.replace`; create parent dir. `created_at` = `datetime.now(UTC).isoformat(timespec="seconds")`.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit `feat: knowledge store with versioned updates`.

### Task 2: BriefStore

**Files:** Modify `src/startup_assistant/briefs.py`; Test `tests/test_briefs.py`

**Interfaces:**
- Consumes: `BriefDraft`, `BriefRecord`.
- Produces: `class BriefStore(path: Path)`, `.save(draft, markdown, kind, revises, knowledge_version, request) -> BriefRecord`, `.latest() -> BriefRecord | None`, `.get(version: int) -> BriefRecord | None`, `.list() -> list[BriefRecord]`.

- [ ] **Step 1:** Tests:
  - `test_empty_store`: `latest() is None`, `list() == []`.
  - `test_versions_increment_and_latest`: save created (v1) then revised with `revises=1` → versions 1 and 2, `latest().version == 2`, `get(1).kind == "created"`.
  - `test_persists_markdown_exactly`: markdown with unicode and trailing newline round-trips byte-identical through a new `BriefStore` on the same path.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement with `BriefsFile(records: list[BriefRecord])`, same atomic write as Task 1.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit `feat: versioned brief store`.

---

## Track B — worktree, Tasks 3–4 (code against Task 0 stubs; use real stores if Track A has merged, otherwise tests construct records directly)

### Task 3: Tools — validation, rendering, SDK tool server

**Files:** Modify `src/startup_assistant/tools.py`; Test `tests/test_tools.py`

**Interfaces:**
- Consumes: `KnowledgeStore`, `BriefStore`, contracts.
- Produces:
  - `class TurnLog(BaseModel): user_text: str = ""; actions: list[str] = []; artifacts: list[str] = []`
  - `word_count(text: str) -> int`
  - `validate_brief(draft: BriefDraft, pricing_restricted: bool) -> list[str]` (empty = OK)
  - `render_brief_markdown(draft: BriefDraft) -> str` with sections in this order: `# {title}`, `## Audience`, `## Buyer`, `## Main message`, `## Recommended channels (proposals)` (2 items, name + reason), `## Draft email` (subject + body, footnote "Draft for review — not sent."), `## Assumptions`, `## Open questions`
  - `render_record_header(record: BriefRecord, latest_version: int) -> str`, e.g. `Brief v2 — CURRENT · revises v1 · knowledge v1 · 2026-10-30T…`; non-latest shows `superseded by v{latest}`
  - `SERVER_NAME = "harbordesk"`; `TOOL_NAMES: list[str]` = the four `mcp__harbordesk__<tool>` names
  - `build_server(knowledge: KnowledgeStore, briefs: BriefStore, turn: TurnLog)` → `create_sdk_mcp_server(...)` with tools `update_company_knowledge(summary, field_changes, new_rules)`, `save_brief(draft, revises: int | None)`, `get_latest_brief()`, `list_briefs()`
  - Action strings exactly: `Company knowledge updated → v{n}`, `Brief v{n} saved (new)`, `Brief v{n} saved (revises v{m})`
- Tool behaviour: `update_company_knowledge` uses `turn.user_text` as `source_text` and returns the new version plus the stale brief versions (`knowledge_version` < new version). `save_brief` validates the draft (pydantic plus `validate_brief`). On errors it returns `is_error: True` with the list and saves nothing. On success it uses kind `"revised"` if `revises` is set, and appends `header + "\n\n" + markdown` to `turn.artifacts`. `get_latest_brief` appends the same artifact, or returns "No brief saved yet." Tool input schemas come from `BriefDraft.model_json_schema()` where possible. Check the exact `@tool` / `create_sdk_mcp_server` signatures in the installed package source (`.venv/lib/python3.14/site-packages/claude_agent_sdk/`).

- [ ] **Step 1:** Tests (pure functions plus tool handlers called directly with tmp stores):
  - `test_validate_ok`: a valid draft with restriction off → `[]`.
  - `test_validate_long_email`: 151-word body → one error mentioning "150".
  - `test_validate_pricing`: restriction on, body contains "$299/month" → error; "pricing" in main_message → error; restriction off → no pricing error.
  - `test_validate_half_claim`: "cuts onboarding time in half" anywhere → error.
  - `test_render_sections_in_order`: rendered markdown contains all 8 headings in order.
  - `test_save_brief_tool_records_action_and_artifact`: call the `save_brief` handler → `turn.actions == ["Brief v1 saved (new)"]`, `briefs.latest().markdown` is contained in `turn.artifacts[0]`.
  - `test_save_brief_invalid_saves_nothing`: 170-word email → `is_error` True, `briefs.list() == []`, `turn.actions == []`.
  - `test_update_knowledge_tool`: handler → `knowledge.version == 1`, action `Company knowledge updated → v1`, result text names stale brief v1 when one exists.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit `feat: assistant tools with validation and action log`.

### Task 4: Prompt and Assistant

**Files:** Modify `src/startup_assistant/prompts.py`, `src/startup_assistant/agent.py`; Test `tests/test_agent_live.py` (marked `live`, skipped unless `RUN_LIVE=1`), `tests/test_prompts.py`

**Interfaces:**
- Consumes: Task 3 `TurnLog`, `build_server`, `TOOL_NAMES`, `render_record_header`; stores.
- Produces:
  - `SYSTEM_PROMPT: str` covering every "System prompt essentials" bullet and anti-goal in the spec.
  - `build_turn_message(knowledge_text: str, brief_index: str, user_text: str) -> str`: labelled sections `## Current company knowledge`, `## Saved briefs`, `## Founder's message`.
  - `auth_mode() -> Literal["api-key", "claude-session"]` (in `agent.py`)
  - `class Assistant(data_dir: Path, model: str | None = None)` — async context manager (`__aenter__` connects one `ClaudeSDKClient`, `__aexit__` disconnects); `async handle(text: str) -> Reply`. Model falls back to `$ASSISTANT_MODEL`, then the SDK default.
- Options: `system_prompt=SYSTEM_PROMPT`, `mcp_servers={SERVER_NAME: server}`, `allowed_tools=TOOL_NAMES`, built-in tools disabled (use the installed SDK's option for that, e.g. `tools=[]` or `disallowed_tools`), `setting_sources=[]`, a permission mode that never prompts, `max_turns` ≈ 8. `handle` resets the TurnLog, sends `build_turn_message(...)`, and joins the `TextBlock`s from `AssistantMessage`s up to the `ResultMessage` as the text. It returns `Reply(text, turn.artifacts, turn.actions)`. Store files: `data_dir/knowledge.json`, `data_dir/briefs.json`.

- [ ] **Step 1:** `tests/test_prompts.py::test_turn_message_sections` (all three headings present, user text last). `tests/test_agent_live.py::test_answer_needs_no_tool`: with a tmp data dir, ask "Who is our primary buyer?" → `reply.actions == []`, and "founder" or "operations" in `reply.text.lower()`.
- [ ] **Step 2:** Run the non-live tests → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `.venv/bin/pytest -q` passes; `RUN_LIVE=1 .venv/bin/pytest -q -m live` passes (uses the local Claude login).
- [ ] **Step 5:** Commit `feat: agent with system prompt and per-turn context`.

---

## Track C — worktree, Tasks 5–6 (code against `Assistant`/`Reply` stubs; tests use a fake assistant)

### Task 5: CLI

**Files:** Modify `src/startup_assistant/cli.py`, `src/startup_assistant/__main__.py`; Test `tests/test_cli.py`

**Interfaces:**
- Consumes: `Assistant`, `Reply`, `auth_mode`.
- Produces: `main(argv: list[str] | None = None) -> int`; `parse_args(argv) -> argparse.Namespace` (`--data-dir` default `data`, `--reset`, `--model`); `render_reply(console: rich.console.Console, reply: Reply) -> None` (prints the model text as Markdown, then each artifact as Markdown inside a `Panel`, then the footer `[Changed: a; b]` or `[No saved data changed]`); `reset_data(data_dir: Path) -> None`.
- Startup banner shows the data dir and `auth_mode()`. Loop: `exit`/`quit`/EOF ends it. A model or SDK exception prints an error and continues.

- [ ] **Step 1:** Tests with `Console(record=True, width=100)`: `test_footer_no_changes`, `test_footer_lists_actions` (both action strings joined with "; "), `test_artifact_printed` (artifact text appears in the export), `test_reset_removes_dir`, `test_parse_defaults`.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit `feat: rich CLI REPL`.

### Task 6: Demo script, checks, README draft

**Files:** Create `scripts/demo.py`, `README.md`

**Interfaces:**
- Consumes: `Assistant`, `render_reply`, `KnowledgeStore`, `BriefStore`.
- Produces: `python scripts/demo.py [--data-dir examples/demo-data] [--phase 1|2|all] [--check]`.
  - `--phase all` (the default) resets the data dir, runs phase 1 in this process, then runs phase 2 in a **new subprocess** (`sys.executable scripts/demo.py --phase 2 …`).
  - Phase 1 messages, verbatim:
    1. "Who are we targeting, and what problem do we solve for them?"
    2. "Create a brief for our next customer acquisition campaign using what we know about the company. Save it so I can retrieve it later."
    3. the founder update, verbatim from the spec
    4. "Who is our current target audience and buyer?"
    5. "Update the campaign brief for our new audience. Focus on coordinating onboarding handoffs across teams."
  - Phase 2: "Show me the latest campaign brief."
  - Each turn is appended to `examples/transcript.md` (`### Turn n — You:` input, reply text, artifacts, footer) and echoed to the console with `render_reply`.
  - `--check` reads the stores and prints PASS/FAIL per check, exiting non-zero on any FAIL:
    - v1 exists, kind `created`, knowledge_version 0, email ≤ 150 words
    - knowledge.version == 1, buyer contains "Customer Success", `pricing_restricted`
    - exactly 2 brief versions in total, so the update and retrieval created none
    - v2 revises v1, knowledge_version 1, markdown contains "Customer Success" and "handoff", and no `$`, "price" or "pricing"
    - the phase-2 transcript contains v2's stored markdown verbatim
- README draft: every section from the spec's "Submission requirements" as headings, with setup/run/demo commands filled in and `TODO` where Task 7 fills in facts (recording link, commit link, times, verification results).

- [ ] **Step 1:** Implement the demo with the `Assistant` stub patched by a fake (a local `--fake` flag that returns canned `Reply`s and writes through real stores is fine) so it can be checked without the model.
- [ ] **Step 2:** `python scripts/demo.py --fake --check` runs to completion and writes the transcript (checks may FAIL with the fake; the script itself must not crash).
- [ ] **Step 3:** Write the README draft.
- [ ] **Step 4:** Commit `feat: two-process demo with checks; README draft`.

---

### Task 7: Merge, live demo, finalize (main, this session)

- [ ] **Step 1:** Merge track branches in order A → B → C; resolve stub conflicts in favour of the implementation; `.venv/bin/pytest -q` passes.
- [ ] **Step 2:** `RUN_LIVE=1 .venv/bin/pytest -q -m live` passes.
- [ ] **Step 3:** `.venv/bin/python scripts/demo.py --check` (live model) → all checks PASS. Fix prompt/tool issues until they do; note each problem found in the README's verification section.
- [ ] **Step 4:** Short manual session in `startup-assistant` with different wording (e.g. "remember we no longer sell to agencies", "what's our latest brief?").
- [ ] **Step 5:** Fill in the README TODOs (except recording/commit links, which Thian adds); commit `docs: README and example outputs`; record the hash as the 3-hour commit.
