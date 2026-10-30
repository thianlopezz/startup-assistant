# HarborDesk Startup Assistant

A command-line assistant for the founder of HarborDesk. Across separate requests it answers
questions from company knowledge, creates and revises marketing campaign briefs, absorbs new
company information, and retrieves saved work, deciding for itself which of those a request needs.

## Recording

- Recording: TODO (link). The 3-hour cutoff is marked at TODO (timestamp) in the video.
- Gaps or technical problems in the recording: TODO

## 3-hour commit

- Preserved commit at the 3-hour cutoff: TODO (link)

## Elapsed working time

- Elapsed working time: TODO
- Recording gaps / technical problems: TODO

## Work after the cutoff

TODO. If nothing was done after the cutoff, say so.

## What was built, setup and run

Requirements: Python 3.14 (the package declares `>=3.10`; 3.14 is what it was built and tested on).

```bash
python3.14 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Authentication goes through the Claude Agent SDK. By default it uses your local Claude Code login
(run `claude` once and log in). If `ANTHROPIC_API_KEY` is set, that key is used instead. The code path
is the same either way, and the CLI prints which one is active at startup. No credentials are stored
in the repo.

Run the assistant:

```bash
.venv/bin/startup-assistant                 # or: .venv/bin/python -m startup_assistant
.venv/bin/startup-assistant --data-dir data --reset --model <model-name>
```

- `--data-dir` (default `data`): where company knowledge and briefs are stored (JSON files).
- `--reset`: delete the data dir first; it is re-seeded from the HarborDesk company data.
- `--model`: model to use (default: SDK default).
- Type `exit` or `quit` (or Ctrl-D) to leave. Data survives restarts.

Each reply prints the model's text, then any brief as a boxed panel, then a footer such as
`[Changed: Company knowledge updated -> v1]` or `[No saved data changed]`. The footer comes from the
tool code, not from the model, so it cannot overclaim.

Run the scripted demo (the six required interactions, with a real process restart before the last):

```bash
.venv/bin/python scripts/demo.py                  # model-backed; writes examples/demo-data and examples/transcript.md
.venv/bin/python scripts/demo.py --check          # same run, then verify the saved data
.venv/bin/python scripts/demo.py --fake --check   # canned replies, no model needed
```

Options: `--data-dir` (default `examples/demo-data`), `--phase 1|2|all` (default `all`: reset, run
turns 1-5 in this process, then turn 6 in a new subprocess), `--check`, `--fake`, `--model`.
`--check` prints PASS/FAIL per check and exits non-zero on any FAIL. It reads the data only through
the store classes.

Tests:

```bash
.venv/bin/pytest -q                  # offline unit tests
RUN_LIVE=1 .venv/bin/pytest -m live  # also calls the real model
```

Example outputs (all from live-model runs):

- `examples/transcript.md`: the six required interactions (turn 6 runs in a fresh process).
- `examples/demo-data/`: the knowledge and brief JSON those turns produced.
- `examples/alt-wording.md`: different phrasings (retrieve with nothing saved, a casual update, a pricing question). Re-run with `.venv/bin/python scripts/alt_wording.py <empty-dir>`.

## Assumptions, design decisions and shortcuts

- **Pricing scope.** The "no pricing" rule covers campaign materials (briefs and draft emails), as the founder wrote it. After the update, the `pricing` field reads "under review". A direct pricing question in chat gets that status, and the old price is mentioned only as out of date. `save_brief` enforces the rule in code; chat replies rely on the prompt.
- **Guardrails in code, not only in the prompt.** `save_brief` rejects a brief that has anything other than 2 channels, an email body over 150 words, any "half"/"halve"/"50%" claim, or, while pricing is restricted, any `$`, "N per month" or the words price/pricing. The model gets the error and retries. These checks are deliberately blunt: "half-day workshop" would be rejected too.
- **Footer written by code.** The `[Changed: …]` footer comes from tool code, not from the model, so the assistant cannot claim a brief was revised when only knowledge changed.
- **One brief series.** Briefs are a single numbered series (v1, v2, …); each revision points at the version it revises, and the newest is current. There are no separately named campaigns and no tool to fetch an old version (the data is there; `BriefStore.get(n)` exists).
- **Knowledge updates.** An update records the founder's message word for word, a summary, changes to the 9 profile fields, and new rules. Facts that don't fit a field go in as rules.
- **Storage.** Plain JSON files with an atomic replace-on-write. Single process, no locking, no recovery from a corrupt file.
- **Assumptions over questions.** For briefs, the assistant goes ahead and lists assumptions and open questions instead of asking first. Retrieval never generates anything: with nothing saved it says so and offers to create a brief.
- **Libraries over hand-written code.** The Claude Agent SDK (agent loop, tool calls, login), pydantic (types, validation, JSON) and rich (terminal output).
- **Locked down.** Built-in Claude Code tools (Bash, Read, Write, web search …), other MCP servers, and user/project settings and CLAUDE.md are all disabled for the assistant (`tools=[]`, `strict_mcp_config`, `setting_sources=[]`, `permission_mode="dontAsk"`).

## How the assistant chooses actions, and how knowledge stays separate from deliverables

- One agent turn per request, with four custom in-process tools: update company knowledge, save a
  brief, get the latest brief, list briefs. The model chooses among them (or none, to just answer)
  from the request; the system prompt says to do only what was asked when a request is ambiguous
  between remembering a fact and revising a brief.
- Company knowledge (`knowledge.json`: seed profile, founder updates, rules) and campaign briefs
  (`briefs.json`: immutable numbered versions) are separate stores. A knowledge update never rewrites a
  brief; it reports which saved briefs were written against older knowledge. Revising a brief is a
  separate, explicit request and creates a new version that points at the one it revises.
- Retrieval prints the stored brief text as-is, with its version and the knowledge version it was
  written against; it does not regenerate it.

## What was verified and what happened

- **Unit tests:** `pytest -q` → 48 passed, 1 skipped (the live test). They cover the stores (persistence across instances, versioning, byte-identical markdown), brief validation (word limit, channels, pricing by field or by rule, rewordings of the "half" claim), the tool handlers (actions and artifacts, nothing saved on error) and the CLI (footer, error handling).
- **Live test:** `RUN_LIVE=1 pytest -m live` → 1 passed. Answering a question uses no tool and changes nothing.
- **Live demo:** `scripts/demo.py --check`.
  - The first run gave 4/5. The "retrieval printed the stored brief verbatim" check failed. The brief *was* verbatim, but the printed block starts with a version header line and the check demanded exact equality. I fixed the check to find the stored text inside the printed block, and the final run passed 5/5. Footers per turn: none / v1 saved / knowledge v1 / none / v2 saved (revises v1) / none.
- **Different wordings** (`examples/alt-wording.md`):
  - retrieval with nothing saved → no brief created
  - a casual "btw, remember…" → knowledge v1, and it says there was nothing to revise
  - "what do we charge?" → under review
  - "who do we sell to these days?" → the new audience
- **Code review:** each parallel track got an AI review before merging. Problems found and fixed:
  - error text containing `[…]` could crash the REPL (rich markup)
  - the pricing restriction turned on only if the model changed the `pricing` field, not when it only added a rule
  - reworded "half" claims got through
  - a retrieved brief could linger as "CURRENT" after a new save
  - an interrupted turn could leak into the next turn

## Unfinished and next steps

- The keyword guardrails can reject harmless wording ("half-day"). A second model call acting as a checker, or a list of allowed phrases, would be more precise.
- No tool to show an older version or compare versions (`get_brief(n)`), and no named campaigns.
- Pricing in chat is guarded by the prompt only.
- The interrupt-and-drain path for a turn cancelled mid-way is checked by hand, with no automated test.
- Context grows within a long session, because the full knowledge block is re-sent every turn.
- Small cleanups: a shared atomic-write helper (duplicated in two stores), and a stronger `render()` test.

## AI tools and models used

- **Claude Code** with Claude Opus 5.5 (`claude-opus-5-5`) as the main session. Superpowers skills shaped the process: brainstorming produced the design doc (`docs/superpowers/specs/`), writing-plans produced the implementation plan (`docs/superpowers/plans/`), and subagent-driven development ran the build.
- **Parallel subagents in git worktrees.**
  - Storage track: Sonnet
  - Tools/agent track: Opus
  - CLI/demo/README track: Sonnet
  - Each track then had an AI code review and one fix round. The main session did the scaffolding, merges, live verification and this README.
- **Claude in Chrome** (in Brave) to read the assessment pages in Notion.
- **At runtime:** the Claude Agent SDK 0.2.175 on the default model (`claude-opus-5-5`), authenticated through the local Claude Code login (or `ANTHROPIC_API_KEY`, if set).

