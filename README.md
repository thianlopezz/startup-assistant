# HarborDesk Startup Assistant

A command-line assistant for the founder of HarborDesk. Across separate requests it answers
questions from company knowledge, creates and revises marketing campaign briefs, absorbs new
company information, and retrieves saved work, deciding for itself which of those a request needs.

> Draft. Items marked `TODO` are filled in after the recorded run.

## Recording

- Recording: TODO (link). The 3-hour cutoff is marked at TODO (timestamp) in the video.
- Gaps or technical problems in the recording: TODO

## 3-hour commit

- Preserved commit at the 3-hour cutoff: TODO (link)

## Elapsed working time

- Elapsed working time: TODO
- Recording gaps / technical problems: TODO

## Work after the cutoff

TODO. For each change: what changed, why, how much time it took, and how to reach that version.
If nothing was done after the cutoff, say so.

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

Example outputs: `examples/transcript.md` (TODO: committed after the recorded run).

## Assumptions, design decisions and shortcuts

- The "no pricing" restriction covers campaign materials (briefs and draft emails), as the founder
  wrote it. After the update the `pricing` field reads "Under review" and a direct pricing question in
  chat gets that status, not a bare price. `save_brief` enforces the restriction in code; chat replies
  rely on the prompt.
- Built on the Claude Agent SDK, pydantic and rich rather than a hand-written tool loop, validation
  layer or terminal formatting.
- Storage is plain JSON files with a version number, not a database. Single process, no concurrency.
- Built-in Claude Code tools (Bash, Read, Write, web search) and user/project settings are disabled for
  the assistant.
- TODO: further shortcuts discovered during the build.

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

- Offline unit tests: TODO (results).
- `scripts/demo.py --check` against the real model: TODO (results).
- Live test (`RUN_LIVE=1`): TODO (results).
- Manual run through the six required interactions: TODO (results).

## Unfinished and next steps

TODO. Known gaps and what would come next.

## AI tools and models used

TODO. For example: Claude Code (model: TODO) for planning and implementation; the Claude Agent SDK
with TODO model at runtime.
