# Testing Guide

For developers maintaining `job-chatbot-single-call`. The companion
[`docs/UAT-PLAN.md`](UAT-PLAN.md) covers end-to-end manual verification;
this document covers the automated test suite under `tests/`.

---

## Testing philosophy

- **Offline by default.** No test hits the live Anthropic API, and no
  test hits the live Workday HTTP endpoints. CI must run on a laptop in
  airplane mode.
- **Fast.** The whole suite finishes in well under a second. If a new
  test takes more than ~100 ms, it is doing too much.
- **The test file is the source of truth.** `tests/test_smoke.py`
  enumerates exactly what we currently guarantee. This document
  describes what's there — it does not promise tests that haven't been
  written.
- **Focused on tools, not the LLM.** We test the four Python tool
  functions and their dispatch wiring. We deliberately do **not** test
  the tool-use loop with a real model — see [What's deliberately NOT
  tested](#whats-deliberately-not-tested-and-why).

---

## What's covered today

The complete suite lives in a single file, `tests/test_smoke.py`. The
test functions, in declaration order:

| Test function | What it asserts |
|---|---|
| `test_modules_import` | The package and every module under it (`chatbot`, `companies`, `models`, `storage`, `tools`, `workday`) import cleanly and `__version__` is set. |
| `test_extract_job_id_with_suffix` | The Workday URL regex pulls `712616WD` out of a path that has a trailing `-2` suffix. |
| `test_extract_job_id_without_suffix` | Same regex works on a path without the numeric suffix. |
| `test_extract_job_id_fallback_for_unparseable` | When the regex can't match, the function falls back to the last path segment (or the empty string). |
| `test_resolve_company_canonical_and_alias` | `resolve_company` returns the right canonical name for `pwc`, `JP Morgan`, and `SFDC`, and returns `None` for an unknown input. |
| `test_known_companies_count` | The registry has exactly 8 entries. |
| `test_resolve_company_tool_unknown_returns_error_and_suggestions` | The dispatch-level wrapper returns `{error: "unknown_company", suggestions: [...]}` with `PricewaterhouseCoopers` in the suggestions list. |
| `test_storage_round_trip` | Writing 3 postings to CSV + SQLite and reading them back yields the expected schema, row counts, and no duplicates. Uses `tmp_path`. |
| `test_validate_output_ok_on_clean_data` | `tool_validate_output` returns `ok=true`, no issues, and the right per-check details on a clean 3-row corpus. |
| `test_validate_output_fails_on_duplicate_job_ids` | Same tool returns `ok=false` with a duplicate-ID issue when a duplicate is forced into the CSV. |
| `test_dispatch_resolve_company_matches_direct_call` | `tools.dispatch("resolve_company", ...)` returns the same payload as calling `tool_resolve_company` directly. |
| `test_dispatch_unknown_tool_returns_error` | Dispatching an unrecognised tool name returns `{error: "unknown_tool"}` instead of raising. |
| `test_dispatch_search_workday_monkeypatched` | Verifies `dispatch("search_workday", ...)` routes correctly when `workday.search_jobs` is monkeypatched to return canned postings. Confirms the count and the first row's `job_id`. |
| `test_dispatch_save_results_writes_files` | `dispatch("save_results", ...)` writes both CSV and SQLite under `tmp_path` and reports the correct row count. |
| `test_tools_list_has_four_tools_with_required_fields` | The `TOOLS` constant has exactly 4 entries with the expected names and well-formed `input_schema` objects (`type: "object"`). |

Total: **15 test functions**, all in one file.

---

## Test categories present in the repo

Even though everything lives in one file, the tests fall into four
categories that map onto the single-call architecture:

1. **Unit tests** — `test_extract_job_id_*`, `test_resolve_company_*`,
   `test_known_companies_count`, `test_storage_round_trip`. These exercise
   individual pure functions (regex, registry lookups, CSV/SQLite I/O).
2. **Integration tests on tool dispatch + validate** —
   `test_dispatch_*`, `test_validate_output_*`. These call `tools.dispatch`
   the same way `chatbot.run_query` would, but with `workday.search_jobs`
   monkeypatched so no HTTP happens.
3. **Contract tests on the JSON tool schemas** —
   `test_tools_list_has_four_tools_with_required_fields`. Guards the
   shape of what Claude sees: 4 tools, each with a description and an
   object-typed input schema.
4. **Smoke / import tests** — `test_modules_import`. Catches accidental
   circular imports or missing `__version__`.

There are **no live API tests** anywhere in CI. The Anthropic and
Workday calls are exercised only via manual UAT (see `docs/UAT-PLAN.md`).

---

## How to run tests

All commands assume you've run `uv sync` once.

```bash
# Run the full suite quietly (typical CI invocation)
uv run pytest -q

# Verbose: print every test name as it runs
uv run pytest -v

# Run a single test by node ID
uv run pytest tests/test_smoke.py::test_extract_job_id_with_suffix

# Run every test whose name contains "storage"
uv run pytest -k storage

# Stop at the first failure (useful when debugging)
uv run pytest -x

# Re-run only the tests that failed last time
uv run pytest --lf
```

The suite finishes in under a second on a 2020-era laptop. If it ever
takes more than 5 seconds, something has regressed — probably a real
HTTP or API call sneaking in.

---

## Mocking strategy

There is exactly one external dependency we mock: Workday HTTP via the
`workday.search_jobs` function. We use pytest's built-in `monkeypatch`
fixture to swap it at the **call site** in the `workday` module:

```python
def test_dispatch_search_workday_monkeypatched(monkeypatch, tmp_path):
    canned = _sample_postings()

    def fake_search_jobs(company, keywords="", location=None, limit=100):
        return canned

    monkeypatch.setattr(workday, "search_jobs", fake_search_jobs)
    result = tools.dispatch("search_workday", {...})
```

This works because `tools.tool_search_workday` calls
`workday_mod.search_jobs(...)` — i.e. it looks up `search_jobs` on the
`workday` module object at call time, not at import time. Patching the
attribute on the module is therefore sufficient.

**Why we don't mock Anthropic.** We are not testing the LLM. We are
testing the four tools that the LLM would invoke. If we mocked the
Anthropic client, the test would just verify that our mock behaves the
way we wrote it to — circular and worthless. The right place to verify
real Anthropic behaviour is manual UAT, where it costs cents and surfaces
real prompt-tuning issues.

---

## Adding a new test

1. Pick a descriptive name following the existing `test_<what>`
   convention. Use snake_case. Keep it under ~50 characters.
2. Open `tests/test_smoke.py`. Append the new function next to the most
   topically-similar existing test. The file is already split with
   comment banners by category — keep that grouping.
3. If your test writes files, accept the `tmp_path: Path` fixture and
   pass it as `output_dir=tmp_path`. **Do not** write into the real
   `output/` directory from a test.
4. If your test would otherwise hit the network, monkeypatch
   `workday.search_jobs` to return a canned list (see the pattern above).
5. Run `uv run pytest -q` and confirm green before committing.

### Worked example: testing a new company alias

Suppose we add `"meta"` as an alias for `Meta` in
`src/job_chatbot_single_call/companies.py`. The corresponding test:

```python
def test_resolve_company_meta_alias():
    meta = companies.resolve_company("meta")
    assert meta is not None
    assert meta.canonical_name == "Meta"
    assert companies.resolve_company("Meta").canonical_name == "Meta"
    assert companies.resolve_company("META").canonical_name == "Meta"
```

Drop it next to `test_resolve_company_canonical_and_alias`. Also bump
the expected count in `test_known_companies_count` from 8 to 9.

---

## Adding a new tool

This is particularly relevant for the single-call architecture, because
all four tools are exposed simultaneously to one Claude call. Adding a
fifth is a four-step change.

1. **Implement the Python function** in `tools.py` next to the existing
   `tool_*` functions. Make it a pure function that takes its arguments
   as keyword args and returns a JSON-serialisable dict. Catch nothing —
   the `dispatch` wrapper does that.
2. **Add the JSON schema** to the `TOOLS` list in `tools.py`. Use the
   same shape as the four existing entries: `name`, `description`,
   `input_schema` with `type: "object"`. Keep the description
   self-contained; that's how we steer Claude in lieu of a long system
   prompt.
3. **Wire it into `dispatch`** in `tools.py`. Add another `if name ==
   "your_tool"` branch that calls your Python function with the
   arguments unpacked from the `arguments` dict.
4. **Update the system prompt** in `chatbot.py` only if Claude needs to
   know about the new tool in the "typical workflow" section. If it's
   strictly optional, the tool description alone is usually enough.
5. **Add 2-3 unit tests** in `tests/test_smoke.py`:
   - One direct call of your Python function with happy-path inputs.
   - One via `tools.dispatch("your_tool", {...})` to prove the wiring.
   - One error / edge case (missing arg, bad input, etc.).
6. **Bump the expected count** in
   `test_tools_list_has_four_tools_with_required_fields` (the test
   name is also worth updating, e.g. to `..._has_five_tools_...`).

---

## Test data / fixtures

There are currently no static fixture files. The single helper,
`_sample_postings()` in `test_smoke.py`, constructs three `JobPosting`
objects inline. That's deliberate: postings are small and inline data is
easier to read than chasing a JSON file in a subdirectory.

If we ever need larger fixtures (e.g. captured Workday HTTP responses
for a deeper regex test), place them under `tests/fixtures/` and load
them with `pathlib.Path(__file__).parent / "fixtures" / "..."`. Do not
commit anything over ~50 kB — capture a representative slice, not the
whole API response.

---

## What's deliberately NOT tested (and why)

- **The live Claude tool-use loop.** Running `chatbot.run_query` for
  real would burn Anthropic tokens on every CI run and depend on model
  behaviour we don't control. We test the tools the model would invoke;
  manual UAT (`docs/UAT-PLAN.md`) covers the loop itself.
- **Workday HTTP.** Rate-limited, geo-flaky, can change schema at any
  time, and outside our control. The single test that exercises the
  search path monkeypatches `workday.search_jobs` instead.
- **The interactive REPL in `main.py`.** Driving a `rich`-powered REPL
  with `pexpect` is more pain than it's worth for a CLI this small. The
  REPL is thin glue around `run_query`; smoke tests cover the glue, and
  manual UAT covers the user experience.
- **Concurrency / race conditions.** The bot is single-threaded by
  design. The SQLite writes use `INSERT ... ON CONFLICT` so re-running
  the same query is safe, but we don't test two simultaneous writers.

If someone wants to add a gated live-API integration test, the pattern
is:

```python
import os
import pytest

@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs a real Anthropic key",
)
def test_run_query_happy_path_live():
    from job_chatbot_single_call.chatbot import run_query
    reply = run_query("find jobs at Workday")
    assert "Workday" in reply
```

Place it in a new file like `tests/test_live.py` and tag it so CI can
opt out by default.

---

## Coverage

The codebase is small — the package weighs in at well under 1000 lines
of Python. The smoke suite touches every module:

| Module | Covered by |
|---|---|
| `chatbot.py` | (not directly — covered by manual UAT) |
| `companies.py` | `test_resolve_company_*`, `test_known_companies_count` |
| `main.py` | (not directly — covered by manual UAT) |
| `models.py` | indirectly via `_sample_postings` and storage tests |
| `storage.py` | `test_storage_round_trip`, `test_validate_output_*` |
| `tools.py` | every test in the "Tool dispatch" and "validate_output" sections |
| `workday.py` | `test_extract_job_id_*` and the monkeypatched dispatch test |

`pytest-cov` is **not** currently a dependency. If you want a numeric
line-coverage report, add `pytest-cov` to the dev deps and run:

```bash
uv add --dev pytest-cov
uv run pytest --cov=job_chatbot_single_call --cov-report=term-missing
```

Coverage today is informally "all branches of the four tool functions
plus the regex" — probably 70-80% of `tools.py` and `storage.py`, near
zero for `chatbot.py` and `main.py`.

---

## Continuous integration

There is no CI configured yet. A minimal GitHub Actions workflow that
matches how a human runs the tests would look like this — drop it at
`.github/workflows/test.yml` when ready:

```yaml
name: test

on:
  pull_request:
  push:
    branches: [main]

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.11"
      - run: uv sync
      - run: uv run pytest -q
```

No secrets are needed — the suite is offline. If we later add the gated
live-API tests, those would need `ANTHROPIC_API_KEY` as a repo secret
and would run only on `workflow_dispatch`.

---

## Test smells to watch for

Reject any PR (yours or someone else's) where a test:

- **Calls the live network** without a `monkeypatch` or skip-marker.
  Grep for `requests.`, `httpx.`, `urlopen`, or `anthropic.Anthropic(`
  in new tests — those are red flags.
- **Asserts on exact LLM output text.** Models drift; phrasing changes;
  the test becomes flaky. Assert on structure (keys in a dict, row
  counts in a CSV) instead.
- **Depends on test execution order.** Each test should pass when run
  in isolation via `pytest tests/test_smoke.py::<name>`.
- **Writes into the real `output/` directory.** Always use `tmp_path`.
- **Sleeps.** If a test needs a sleep, the code under test has a race
  condition we should fix rather than paper over.
- **Catches and ignores `Exception`.** Let failures fail loudly.
- **Has commented-out assertions.** Either keep it or delete it.

---

## Linting + type-checking

Not configured yet. Plausible future additions:

- **`ruff`** for lint + format. Drop a `[tool.ruff]` block in
  `pyproject.toml` with `line-length = 88` and the default rule set.
- **`mypy`** for type checks. The codebase already uses `from
  __future__ import annotations` and PEP 604 union syntax (`X | None`),
  so `mypy --strict` is realistic from day one.

Neither tool runs in CI today. Don't claim "the project lints" until
one of them is wired up and green.
