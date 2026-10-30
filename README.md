# HarborDesk Startup Assistant

A command-line assistant for the founder of HarborDesk. Across separate requests it answers
questions from company knowledge, creates and revises marketing campaign briefs, absorbs new
company information, and retrieves saved work, deciding for itself which of those a request needs.

## Quick start

Needs Python 3.11+ (macOS, Linux or WSL). The first run creates `.venv` and installs everything (about 10 seconds).

```bash
./run.sh test        # offline unit tests, no login needed
./run.sh demo        # the six required interactions with canned replies + checks, no login needed
./run.sh             # chat with the assistant (uses the real model)
```

To use the real model, either be logged in to Claude Code on this machine, or run `export ANTHROPIC_API_KEY=sk-ant-...` first.
Claude Code doesn't have to be installed, because the SDK ships its own copy. If neither login nor key is found, the assistant says so at startup and exits.

More:

- `./run.sh --reset` starts from fresh company data. Without it, data in `data/` survives restarts.
- `./run.sh demo-live` runs the six interactions against the real model and checks the result. It writes to a temp dir, never over `examples/`, and takes a few minutes.
- `examples/transcript.md` shows the messages the demo sends, if you want to type them yourself.

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

Requirements: Python 3.11+ (built and tested on 3.14). `./run.sh` (see Quick start) does the setup below
for you. To do it by hand:

```bash
python3 -m venv .venv               # python3 must be 3.11+; on macOS the system one is 3.9
.venv/bin/pip install -e '.[dev]'
```

Authentication goes through the Claude Agent SDK, which includes its own Claude Code CLI. By default it uses your local Claude Code login
(`claude auth login`). If `ANTHROPIC_API_KEY` is set, that key is used instead. The code path
is the same either way. At startup the CLI asks the SDK's CLI (`claude auth status`) which one is
available, prints it, and exits with instructions if there is neither. No credentials are stored
in the repo.

Run the assistant:

```bash
.venv/bin/startup-assistant                 # or: .venv/bin/python -m startup_assistant
.venv/bin/startup-assistant --data-dir data --reset --model <model-name>
```

- `--data-dir` (default `data`): where company knowledge and briefs are stored (JSON files).
- `--reset`: delete the data dir first; it is re-seeded from the HarborDesk company data.
- `--model`: model to use (default: `ASSISTANT_MODEL` env var, else the SDK default).
- Type `exit` or `quit` (or Ctrl-D) to leave. Data survives restarts.
- Pasting multi-line text (for example the founder update) sends it as one message: the prompt uses `prompt_toolkit` with bracketed paste, so only your own Enter submits. When input is piped, each line is a separate message.

Each reply prints the model's text, then any brief as a boxed panel, then a footer such as
`[Changed: Company knowledge updated → v1]` or `[No saved data changed]`. The footer comes from the
tool code, not from the model, so it cannot overclaim.

Run the scripted demo (the six required interactions, with a real process restart before the last):

```bash
# Model-backed run + checks, written to /tmp so the committed examples/ outputs are kept:
.venv/bin/python scripts/demo.py --check --data-dir /tmp/hd-demo --transcript /tmp/hd-transcript.md
.venv/bin/python scripts/demo.py --fake --check   # canned replies, no model needed
```

Careful: a model-backed run with no `--data-dir`/`--transcript` overwrites `examples/demo-data` and `examples/transcript.md` in place (that is how the committed examples were made). `./run.sh demo-live` always writes to a temp dir. `--fake` runs write to the git-ignored `examples/fake-data` and `examples/fake-transcript.md`.

Options: `--data-dir` (default `examples/demo-data`), `--transcript` (default `examples/transcript.md`), `--phase 1|2|all` (default `all`: reset, run
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
- `examples/alt-wording.md`: different phrasings. It covers retrieving with nothing saved, a casual update, a pricing question, a revision, "show me version 1", "what changed between v1 and v2", a second campaign, and "latest" across campaigns. Re-run with `.venv/bin/python scripts/alt_wording.py <empty-dir>`.

Environment variables (all optional):

- `ANTHROPIC_API_KEY`: use an API key instead of the local Claude Code login.
- `ASSISTANT_MODEL`: the assistant's model (default: the SDK default).
- `ASSISTANT_BRIEF_CHECK=0`: turn off the AI brief checker. The code checks still run.
- `ASSISTANT_CHECK_MODEL`: the checker's model (default `claude-sonnet-5-5`).

## Assumptions, design decisions and shortcuts

- **Pricing scope.** The "no pricing" rule covers campaign materials (briefs and draft emails), as the founder wrote it. After the update, the `pricing` field reads "under review". A direct pricing question in chat gets that status, and the old price is mentioned only as out of date. `save_brief` enforces the rule in code. Chat replies have a code check too: once pricing is restricted, a reply that states a price as current gets one automatic rewrite. If it still does, it gets a note that the figure isn't current. The check is a simple heuristic, so a frequency like "4 per month" also triggers a rewrite.
- **Guardrails in code, not only in the prompt.** `save_brief` rejects a brief that has anything other than 2 channels, an email body over 150 words, a reduction claim with "half" ("cuts … in half", "by half", "half the time", "halve", "50%"; "half-day" is fine), or, while pricing is restricted, any `$`, "N per month", the words price/pricing or "commercial terms". The model gets the error and retries. The prompt also tells it not to mention that pricing was left out.
- **AI brief checker.** After the code checks pass, a second, tool-less model call (`claude-sonnet-5-5`) reads the brief next to the company knowledge. It flags things keywords miss: made-up stats, testimonials, integrations or capabilities, any hint at pricing, reworded performance claims, channels presented as proven, or an audience that contradicts the knowledge. Problems reject the save and the assistant fixes the brief. It takes a few seconds per save and is capped at 2 rejections per turn; after that the brief is saved and the leftover points are shown to the founder. If the checker itself fails, the brief is saved with a note saying the check was skipped. `ASSISTANT_BRIEF_CHECK=0` turns it off.
- **Footer written by code.** The `[Changed: …]` footer comes from tool code, not from the model, so the assistant cannot claim a brief was revised when only knowledge changed.
- **Named campaigns.** Each brief belongs to a campaign, and each campaign has its own versions (v1, v2, …). A revision points at the version it revises, and the newest is current. The first brief goes in "Customer acquisition" unless the founder names another campaign, and data saved before campaigns existed loads into that campaign. "Show me the latest brief" shows the most recently saved brief and names any other campaigns. Any version can be shown ("show me version 1", labelled as superseded). "What changed between v1 and v2?" prints a line-by-line diff made by code (`difflib`), and the model adds a short summary.
- **Knowledge updates.** An update records the founder's message word for word, a summary, changes to the 9 profile fields, and new rules. Facts that don't fit a field go in as rules.
- **Context per turn.** Turns always carry the brief index and the founder's message. The full company knowledge goes only on the first turn of a session, after any change, after an aborted turn, or after the SDK compacts the conversation; otherwise the turn says "Unchanged since vN". This departs from the original design (knowledge in every request) to keep long sessions small. It was a deliberate choice.
- **Storage.** Plain JSON files with an atomic replace-on-write. Single process, no locking, no recovery from a corrupt file.
- **Assumptions over questions.** For briefs, the assistant goes ahead and lists assumptions and open questions instead of asking first. Retrieval never generates anything: with nothing saved it says so and offers to create a brief.
- **Libraries over hand-written code.** The Claude Agent SDK (agent loop, tool calls, login), pydantic (types, validation, JSON) and rich (terminal output).
- **Locked down.** Built-in Claude Code tools (Bash, Read, Write, web search …), other MCP servers, and user/project settings and CLAUDE.md are all disabled for the assistant (`tools=[]`, `strict_mcp_config`, `setting_sources=[]`, `permission_mode="dontAsk"`).

## How the assistant chooses actions, and how knowledge stays separate from deliverables

- One agent turn per request, with six custom in-process tools: update company knowledge, save a
  brief, get the latest brief, get a specific brief version, compare two versions, list briefs. The model chooses among them (or none, to just answer)
  from the request; the system prompt says to do only what was asked when a request is ambiguous
  between remembering a fact and revising a brief.
- Company knowledge (`knowledge.json`: seed profile, founder updates, rules) and campaign briefs
  (`briefs.json`: immutable numbered versions per campaign) are separate stores. A knowledge update never rewrites a
  brief; it reports which saved briefs were written against older knowledge. Revising a brief is a
  separate, explicit request and creates a new version that points at the one it revises.
- Retrieval prints the stored brief text as-is, with its version and the knowledge version it was
  written against; it does not regenerate it.

## What was verified and what happened

- **Unit tests:** `pytest -q` → 175 passed, 4 skipped (the live tests). They cover the stores (persistence across instances, versioning, byte-identical markdown), brief validation (word limit, channels, pricing by field or by rule, rewordings of the "half" claim), the tool handlers (actions and artifacts, nothing saved on error), the CLI (footer, error handling) and the startup login check.
- **Live tests:** `RUN_LIVE=1 pytest -m live` → 4 passed. Answering a question uses no tool and changes nothing. The AI checker returns no problems for a clean brief, and flags a made-up customer statistic and an indirect "commercial terms are left out" pricing hint.
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
- **Second round** (parallel agents again, after a manual test):
  - A pasted multi-line message was split into several messages. Fixed with `prompt_toolkit` bracketed paste, plus a test.
  - Replies were hard to tell apart from your own messages. Turns are now labelled You / Assistant.
  - Live brief v2 hinted at pricing ("commercial terms are left out"). The prompt and code now block this.
  - "half-day" was rejected. Only reduction claims are now.
  - New `get_brief(n)` tool.
  - Ctrl-C cancels the running reply instead of quitting. It works for repeated Ctrl-C too, with a test that sends real SIGINTs.
  - Turn cleanup now has automated tests.
  - Company knowledge is sent in full only on the first turn, when it changed, after an aborted turn, or after the SDK compacts the conversation. Other turns say "Unchanged since vN".
  - A shared atomic-write helper.
  - Re-ran the live demo: 5/5. The extended wording run included a revision and "show me version 1".
  - A review of this round found two more problems, both now fixed with tests. A second Ctrl-C during cleanup could leak a cancelled turn into the next one; repeat presses are now ignored until cleanup finishes. After the SDK compacts a long conversation, the "Unchanged since vN" line could point at text the model no longer has; a `PreCompact` hook now forces a full resend. Live demo re-run after the fixes: 5/5.
- **Third round** (named campaigns and version comparison, the AI brief checker, a pricing check on chat replies; 3 parallel agents):
  - Live demo: 6/6. A new check confirms the demo creates no stray campaigns. The real checker ran on every save and was never skipped.
  - Extended wording run:
    - "What changed between v1 and v2?" → a code-made diff and a matching summary (only the email changed).
    - A second "Spring webinar" campaign → its own v1.
    - "Show me the latest brief" → the newest brief, naming the other campaign.
    - "What do we charge?" → "under review", with the old price only as the previous price.
  - The review found three problems, now fixed with tests:
    - Stale README sections, now rewritten.
    - A pricing rewrite could save something the footer wouldn't show; actions from the rewrite now reach the footer.
    - A checker that keeps disagreeing could loop for minutes; it's now capped at 2 rejections per turn.
  - Smaller fixes: the checker's model stream is closed on timeout; a revision without a campaign name stays in the current campaign; diffs show in a "Changes" panel.
  - Re-ran after the fixes: 167 unit tests, 4 live tests, live demo 6/6.

- **Reviewer setup:** a fresh copy was set up from scratch with `./run.sh`. Then `test`, `demo` and a live question all worked. With no login and no key, startup stops with the instructions instead of the SDK's "Not logged in · Please run /login".

## Unfinished and next steps

- The code guardrails are keyword checks, and the AI checker is one model's judgement. Neither is proof: a subtle claim could still pass both.
- The chat pricing check is a heuristic (see above). It can trigger a needless rewrite, for example on "4 per month".
- Each save makes one extra model call (the checker), so saving takes a few seconds longer.
- In piped mode, a Ctrl-C at the prompt before the first reply doesn't interrupt the read. In a real terminal it exits normally.
- No locking: two assistants on the same data folder at once could overwrite each other.

## AI tools and models used

- **Claude Code** with Claude Opus 5.5 (`claude-opus-5-5`) as the main session. Superpowers skills shaped the process: brainstorming produced the design doc (`docs/superpowers/specs/`), writing-plans produced the implementation plan (`docs/superpowers/plans/`), and subagent-driven development ran the build.
- **Parallel subagents in git worktrees.**
  - Storage track: Sonnet
  - Tools/agent track: Opus
  - CLI/demo/README track: Sonnet
  - Each track then had an AI code review and one fix round. The main session did the scaffolding, merges, live verification and this README.
  - Two more rounds ran the same way. Round 2 (after a manual test) covered paste handling, the You/Assistant labels, guardrail precision, `get_brief`, Ctrl-C and context size. Round 3 covered named campaigns with `compare_briefs`, the AI brief checker, and the chat pricing check. Each round was split by file across 3 agents in parallel, merged, then got an Opus review and a fix round.
- **Claude in Chrome** (in Brave) to read the assessment pages in Notion.
- **At runtime:** the Claude Agent SDK 0.2.175. The assistant uses the default model (`claude-opus-5-5`) and the brief checker uses `claude-sonnet-5-5`. Both authenticate through the local Claude Code login (or `ANTHROPIC_API_KEY`, if set).

