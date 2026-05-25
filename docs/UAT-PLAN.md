# User Acceptance Test (UAT) Plan

A practical checklist for verifying that `job-chatbot-single-call` does
what its README promises, **before** declaring a release "shippable".
The intended reader is a product person, a friendly colleague, or the
author wearing their QA hat — not a Python developer.

---

## What UAT covers

UAT is **end-to-end verification from the user's seat**: start a fresh
clone, install, type natural-language requests at the REPL, and confirm
the right files appear on disk with the right contents. It is *not* a
substitute for unit tests. Those live in `tests/test_smoke.py` and are
documented separately in [`docs/TESTING.md`](TESTING.md). If `pytest`
is red, do not bother running UAT — fix the unit tests first.

Pass criteria are explicit per scenario below. A scenario passes only
if every listed expectation holds; partial matches are failures.

---

## Prerequisites

These mirror the [User Manual](USER-MANUAL.md) prerequisites, plus one
extra item that matters for UAT specifically.

- macOS, Linux, or Windows with WSL / Git Bash.
- Python 3.11 or newer (`python3 --version`).
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- A valid Anthropic API key (`sk-ant-...`) with billing enabled.
- **A working internet connection.** The `search_workday` tool makes
  real HTTPS calls to each company's Workday careers API. UAT is *not*
  offline; if the corporate VPN blocks `*.myworkdayjobs.com`, most
  scenarios will fail through no fault of the chatbot.
- A clock that is roughly correct (the CSV filename embeds today's date,
  and validation re-opens the file by that name).

---

## Setup checklist

Run through this before starting the scenarios. Tick each box as you go.

- [ ] Cloned the repo: `git clone git@github.com:mahadevaiahrashmi/job-chatbot-single-call.git`
- [ ] `cd job-chatbot-single-call`
- [ ] Created the virtualenv: `uv venv`
- [ ] Installed dependencies: `uv sync`
- [ ] Copied env template: `cp .env.example .env`
- [ ] Edited `.env` and pasted a real `ANTHROPIC_API_KEY=sk-ant-...`
- [ ] Ran the unit tests and saw all green: `uv run pytest -q`
- [ ] Started the REPL: `uv run job-chatbot-single-call`
- [ ] Saw the banner and the `you>` prompt blinking
- [ ] Typed `companies` and got back the 8-company list

If any of the boxes above cannot be ticked, **stop and fix the
environment** before going further. UAT failures caused by setup mistakes
waste everyone's time.

---

## Acceptance test scenarios

Each scenario is one user prompt typed at the `you>` REPL. The "Expected
output files" column refers to artifacts under `output/` (the default
directory; override with `--output-dir`). All file paths in the bot's
reply should be absolute and openable.

| ID | Title | Input query | Expected behavior | Expected output files | Pass / Fail criteria |
|---|---|---|---|---|---|
| UAT-001 | Happy path | `find AI jobs at PwC in Bangalore` | Bot calls `resolve_company` -> `search_workday` -> `save_results` -> `validate_output`, then prints a 1-6 line summary with company, count, paths, and "validation: ok". | `output/pricewaterhousecoopers_ai_<YYYY-MM-DD>.csv` + `output/jobs.db` | CSV has >=1 data row, schema is `company,job_id,title,location,posted_on,url`, no duplicate `job_id`, validate reports `ok=true`. |
| UAT-002 | Alias resolution | `find jobs at SFDC` | Bot resolves `SFDC` to `Salesforce` without asking a clarifying question. | `output/salesforce_all_<YYYY-MM-DD>.csv` | The CSV's `company` column reads `Salesforce` on every row. No prompt back to the user about which company. |
| UAT-003 | Unknown company graceful fail | `find jobs at Acme Corp` | `resolve_company` returns `error: unknown_company` with `suggestions`. Bot lists the 8 supported companies and asks the user to pick one. Does **not** guess and does **not** call `save_results`. | None | No new file created under `output/`. The reply mentions the 8 known names (or links the user to the `companies` REPL command). |
| UAT-004 | Empty result set | `find COBOL jobs at NVIDIA` | `search_workday` returns `count: 0`. Bot still calls `save_results` (writes an empty-data CSV with headers) and `validate_output`. Validation flags the zero-row issue. | `output/nvidia_cobol_<YYYY-MM-DD>.csv` (headers only) + `output/jobs.db` | Reply explicitly says "0 results" (or equivalent). `validate_output` reports `ok=false` with an issue containing "zero data rows". No crash, exit code from the REPL is still 0. |
| UAT-005 | Multi-keyword | `find machine learning jobs at Adobe` | Bot searches Adobe for "machine learning". | `output/adobe_machine learning_<YYYY-MM-DD>.csv` (the keyword is used verbatim in the filename) | At least one row exists; spot-check three job titles and confirm they relate to ML / data science. |
| UAT-006 | Location filter applied | `find data engineer jobs at Cisco in San Jose` | Bot calls `search_workday` with `keyword="data engineer"`, `location="San Jose"`. Client-side filter keeps only postings whose location string contains "San Jose". | `output/cisco_data engineer_<YYYY-MM-DD>.csv` | Every row's `location` column contains "San Jose" (case-insensitive substring). |
| UAT-007 | No location filter | `find product manager jobs at Netflix` | Bot calls `search_workday` with `location=null`. Results span multiple cities / countries. | `output/netflix_product manager_<YYYY-MM-DD>.csv` | The CSV has at least 2 distinct values in `location` (or all rows share Netflix's one office, which is also acceptable — just confirm no filtering happened). |
| UAT-008 | Idempotent re-run | Run UAT-001 twice in a row without leaving the REPL. | Second run overwrites the CSV in place. SQLite `INSERT ... ON CONFLICT` upserts mean the row count for that company in `jobs.db` does not double. | Same CSV path as UAT-001 | After two runs, `sqlite_row_count(jobs.db, 'PricewaterhouseCoopers')` equals the CSV row count of the most recent run — not 2x. |
| UAT-009 | CSV opens in a spreadsheet | After UAT-001, open the CSV in Excel, Numbers, or Google Sheets. | Columns line up. No mojibake. URLs are clickable. | (same as UAT-001) | Six columns visible, header row matches the User Manual's "Reading the CSV" table, every `url` opens a real job posting in a browser. |
| UAT-010 | Cost sanity | After completing UAT-001 through UAT-009, open the Anthropic Console -> Usage tab. | Single-call architecture stays cheap because there's only one `messages.create` call per user prompt (looped for tool turns). | n/a | Total cost for all 9 scenarios combined under ~50¢ (USD) on Claude Haiku 4.5. Each individual query under ~10¢. If a single query exceeds that, file a bug. |

---

## Negative tests

These verify that the bot **fails cleanly** rather than crashing or
silently doing the wrong thing. The "expected behavior" is the failure
mode itself.

| ID | Scenario | How to set it up | Expected behavior |
|---|---|---|---|
| NEG-001 | Missing API key | Unset the env var: `unset ANTHROPIC_API_KEY` and remove (or rename) `.env`. Then `uv run job-chatbot-single-call`. | CLI prints the red `ANTHROPIC_API_KEY is not set...` message and exits with code 1. No REPL banner. |
| NEG-002 | Network offline | Turn off Wi-Fi (or block `*.myworkdayjobs.com` at the firewall) and run `find AI jobs at PwC`. | `search_workday` raises a `requests` / `httpx` exception. The dispatcher catches it and returns `{error: "<ExceptionType>", message: "..."}`. The bot's reply surfaces the failure rather than pretending it succeeded. No CSV is written. |
| NEG-003 | No `.env` file at all | Delete `.env` (keep `ANTHROPIC_API_KEY` unset in the shell too). | Same as NEG-001 — `load_dotenv()` is a no-op when the file is missing, and the env-var check fails. |
| NEG-004 | Empty input | At the `you>` prompt, just hit Enter on an empty line. | REPL loops back to `you>` without calling Claude. No tokens consumed. |
| NEG-005 | Whitespace-only input | Type three spaces and Enter. | Same as NEG-004 — stripped to empty, loops. |
| NEG-006 | Quit shortcut | Type `quit`, `exit`, or `:q`. | Exits with code 0, no traceback. |

---

## Performance expectations

The single-call architecture is the fastest of the five siblings because
there is only ever **one** Anthropic `messages.create` call per turn of
the tool-use loop, and the loop typically runs 4-5 turns (one per tool +
the final summary). Workday HTTP latency dominates total wall-clock time.

| Metric | Expected | Hard ceiling |
|---|---|---|
| End-to-end wall-clock for a typical UAT scenario | 5 - 15 seconds | 30 seconds |
| Anthropic tokens per query | < 8k input, < 1k output | 16k input, 2k output |
| `search_workday` Workday roundtrip | 1 - 4 seconds | 10 seconds |
| Cost per query (Haiku 4.5) | ~3 - 8 cents | 10 cents |

If a query takes longer than 30 seconds, suspect network issues or a
runaway tool-use loop. The hard safety bound is `MAX_ITERATIONS = 12`
in `chatbot.py` — if the bot hits that, it will return whatever final
text it has (often "[no final text emitted]"). Treat that as a bug.

---

## Sign-off template

Fill this in at the end of a UAT pass and attach it to the release PR.

```markdown
## UAT Sign-off

- Tester: <your name>
- Date: <YYYY-MM-DD>
- Version (git commit): <output of `git rev-parse HEAD`>
- Python: <output of `python3 --version`>
- OS: <macOS 15.x / Ubuntu 24.04 / ...>

### Scenarios

| ID | Result | Notes |
|---|---|---|
| UAT-001 | pass / fail | |
| UAT-002 | pass / fail | |
| UAT-003 | pass / fail | |
| UAT-004 | pass / fail | |
| UAT-005 | pass / fail | |
| UAT-006 | pass / fail | |
| UAT-007 | pass / fail | |
| UAT-008 | pass / fail | |
| UAT-009 | pass / fail | |
| UAT-010 | pass / fail | |

### Negative tests

| ID | Result | Notes |
|---|---|---|
| NEG-001 | pass / fail | |
| NEG-002 | pass / fail | |
| NEG-003 | pass / fail | |
| NEG-004 | pass / fail | |
| NEG-005 | pass / fail | |
| NEG-006 | pass / fail | |

### Overall verdict

- [ ] **Ship it** — every scenario passed, no blocking bugs.
- [ ] **Ship with known issues** — list them below, with severity.
- [ ] **Block release** — at least one P0/P1 bug; do not ship.

### Free-form notes

<anything else worth recording — cost surprises, slow scenarios, UX
papercuts, suggestions for the next round>
```

---

## Reporting bugs

If a scenario fails, file an issue at
<https://github.com/mahadevaiahrashmi/job-chatbot-single-call/issues>
with the following details so a developer can reproduce it:

1. **Scenario ID** (e.g. `UAT-004`) or "ad-hoc" if you went off-script.
2. **Exact input query** you typed, copy-pasted.
3. **Expected behavior**, in one sentence.
4. **Actual behavior** — paste the bot's reply verbatim, plus any
   traceback from the terminal.
5. **Version**: output of `git rev-parse HEAD` from the repo root.
6. **Environment**: OS, Python version, `uv --version`.
7. **Relevant files**: attach the CSV (or note that none was written),
   and the last ~50 lines of any traceback.

Redact your API key from any pasted output. Anthropic keys start with
`sk-ant-` — search for that prefix before submitting.
