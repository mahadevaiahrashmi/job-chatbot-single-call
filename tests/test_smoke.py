"""Offline smoke tests.

No live Anthropic API calls. No live HTTP to Workday. The one place where
Workday would normally be hit (`search_workday` dispatch) is monkeypatched
to a stub that returns canned postings.

These tests cover:
  - the Workday job-ID regex (with suffix, without suffix, fallback)
  - the company registry (canonical names, aliases, unknown returns error)
  - the registry has 8 entries
  - storage round-trip (write + read back CSV + SQLite)
  - `validate_output` passes on clean data
  - `validate_output` fails on duplicate job IDs
  - tool dispatch routes each tool name to the right Python function
"""

from __future__ import annotations

from pathlib import Path

import job_chatbot_single_call
from job_chatbot_single_call import chatbot, companies, models, storage, tools, workday
from job_chatbot_single_call.workday import _extract_job_id


# ---------------------------------------------------------------------------
# Import smoke
# ---------------------------------------------------------------------------


def test_modules_import():
    assert job_chatbot_single_call.__version__
    assert chatbot and companies and models and storage and tools and workday


# ---------------------------------------------------------------------------
# Workday job-ID regex
# ---------------------------------------------------------------------------


def test_extract_job_id_with_suffix():
    assert (
        _extract_job_id(
            "/Global_Experienced_Careers/job/Bengaluru/Senior-Manager_712616WD-2"
        )
        == "712616WD"
    )


def test_extract_job_id_without_suffix():
    assert (
        _extract_job_id(
            "/Global_Experienced_Careers/job/Mumbai/Director-Cloud_712616WD"
        )
        == "712616WD"
    )


def test_extract_job_id_fallback_for_unparseable():
    assert _extract_job_id("/jobs/legacy-role") == "legacy-role"
    assert _extract_job_id("") == ""


# ---------------------------------------------------------------------------
# Company registry
# ---------------------------------------------------------------------------


def test_resolve_company_canonical_and_alias():
    pwc = companies.resolve_company("pwc")
    assert pwc is not None
    assert pwc.canonical_name == "PricewaterhouseCoopers"
    assert pwc.tenant == "pwc"
    assert pwc.site == "Global_Experienced_Careers"

    assert (
        companies.resolve_company("JP Morgan").canonical_name == "JPMorgan Chase"
    )
    assert companies.resolve_company("SFDC").canonical_name == "Salesforce"
    assert companies.resolve_company("never-heard-of-them") is None


def test_known_companies_count():
    assert len(companies.known_companies()) == 8


def test_resolve_company_tool_unknown_returns_error_and_suggestions():
    result = tools.tool_resolve_company("never-heard-of-them")
    assert result["error"] == "unknown_company"
    assert isinstance(result["suggestions"], list)
    assert "PricewaterhouseCoopers" in result["suggestions"]


# ---------------------------------------------------------------------------
# Storage round-trip
# ---------------------------------------------------------------------------


def _sample_postings() -> list[models.JobPosting]:
    return [
        models.JobPosting(
            company="PricewaterhouseCoopers",
            job_id="712616WD",
            title="AI Engineer",
            location="Bengaluru",
            posted_on="2026-05-20",
            url="https://example.com/job/712616WD",
        ),
        models.JobPosting(
            company="PricewaterhouseCoopers",
            job_id="712617WD",
            title="ML Engineer",
            location="Mumbai",
            posted_on="2026-05-21",
            url="https://example.com/job/712617WD",
        ),
        models.JobPosting(
            company="PricewaterhouseCoopers",
            job_id="712618WD",
            title="Data Engineer",
            location="Hyderabad",
            posted_on="2026-05-22",
            url="https://example.com/job/712618WD",
        ),
    ]


def test_storage_round_trip(tmp_path: Path):
    postings = _sample_postings()
    csv_path = storage.write_csv(postings, "pwc", "ai", output_dir=tmp_path)
    db_path = storage.write_sqlite(postings, "pwc", output_dir=tmp_path)

    assert csv_path.exists()
    assert db_path.exists()
    assert storage.csv_columns(csv_path) == storage.EXPECTED_CSV_COLUMNS
    assert storage.count_csv_rows(csv_path) == 3
    assert storage.csv_duplicate_job_ids(csv_path) == []
    assert storage.sqlite_row_count(db_path, "PricewaterhouseCoopers") == 3


# ---------------------------------------------------------------------------
# validate_output
# ---------------------------------------------------------------------------


def test_validate_output_ok_on_clean_data(tmp_path: Path):
    postings = _sample_postings()
    csv_path = storage.write_csv(postings, "pwc", "ai", output_dir=tmp_path)
    db_path = storage.write_sqlite(postings, "pwc", output_dir=tmp_path)

    result = tools.tool_validate_output(
        csv_path=str(csv_path),
        sqlite_path=str(db_path),
        canonical="PricewaterhouseCoopers",
    )
    assert result["ok"] is True
    assert result["issues"] == []
    assert result["checks"]["csv_schema_ok"] is True
    assert result["checks"]["csv_row_count"] == 3
    assert result["checks"]["csv_duplicates"] == []
    assert result["checks"]["sqlite_row_count"] == 3


def test_validate_output_fails_on_duplicate_job_ids(tmp_path: Path):
    # Manually write a CSV with a duplicate job_id to trigger the dedup check.
    postings = _sample_postings()
    dup = models.JobPosting(
        company="PricewaterhouseCoopers",
        job_id="712616WD",  # duplicate of first
        title="AI Engineer (dup)",
        location="Bengaluru",
        posted_on="2026-05-20",
        url="https://example.com/job/712616WD",
    )
    csv_path = storage.write_csv(
        postings + [dup], "pwc", "ai", output_dir=tmp_path
    )
    # SQLite upsert collapses the duplicate so its row count is the unique total.
    db_path = storage.write_sqlite(
        postings + [dup], "pwc", output_dir=tmp_path
    )

    result = tools.tool_validate_output(
        csv_path=str(csv_path),
        sqlite_path=str(db_path),
        canonical="PricewaterhouseCoopers",
    )
    assert result["ok"] is False
    assert result["checks"]["csv_duplicates"] == ["712616WD"]
    assert any("duplicate" in issue.lower() for issue in result["issues"])


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def test_dispatch_resolve_company_matches_direct_call():
    via_dispatch = tools.dispatch("resolve_company", {"name": "pwc"})
    direct = tools.tool_resolve_company("pwc")
    assert via_dispatch == direct
    assert via_dispatch["canonical"] == "PricewaterhouseCoopers"


def test_dispatch_unknown_tool_returns_error():
    result = tools.dispatch("not_a_real_tool", {})
    assert result["error"] == "unknown_tool"


def test_dispatch_search_workday_monkeypatched(monkeypatch, tmp_path: Path):
    """Verify the dispatcher routes to search_workday without hitting the net."""
    canned = _sample_postings()

    def fake_search_jobs(company, keywords="", location=None, limit=100):
        # The real signature; we ignore the args and return canned postings.
        return canned

    monkeypatch.setattr(workday, "search_jobs", fake_search_jobs)

    result = tools.dispatch(
        "search_workday",
        {
            "tenant": "pwc",
            "site": "Global_Experienced_Careers",
            "canonical": "PricewaterhouseCoopers",
            "keyword": "ai",
            "location": None,
            "limit": 10,
        },
    )
    assert result["count"] == 3
    assert len(result["postings"]) == 3
    assert result["postings"][0]["job_id"] == "712616WD"


def test_dispatch_save_results_writes_files(monkeypatch, tmp_path: Path):
    postings_dicts = [p.to_dict() for p in _sample_postings()]
    result = tools.dispatch(
        "save_results",
        {
            "canonical": "PricewaterhouseCoopers",
            "keyword": "ai",
            "postings": postings_dicts,
        },
        output_dir=tmp_path,
    )
    assert result["rows"] == 3
    assert Path(result["csv_path"]).exists()
    assert Path(result["sqlite_path"]).exists()


# ---------------------------------------------------------------------------
# Tools list sanity
# ---------------------------------------------------------------------------


def test_tools_list_has_four_tools_with_required_fields():
    assert len(tools.TOOLS) == 4
    names = {t["name"] for t in tools.TOOLS}
    assert names == {
        "resolve_company",
        "search_workday",
        "save_results",
        "validate_output",
    }
    for t in tools.TOOLS:
        assert "description" in t and t["description"]
        assert "input_schema" in t
        assert t["input_schema"]["type"] == "object"
