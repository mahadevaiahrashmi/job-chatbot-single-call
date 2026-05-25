"""Tool schemas + dispatch table for the single-call chatbot.

All four tools are exposed simultaneously to one Claude call. Claude picks
the order and arguments; the dispatcher below maps `block.name` -> Python
function and returns a JSON-serialisable dict.

Keep tool descriptions self-contained — they are how we steer Claude in
lieu of a long system prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import companies as companies_mod
from . import storage as storage_mod
from . import workday as workday_mod
from .models import JobPosting

# ---------------------------------------------------------------------------
# Tool schemas (Anthropic tool-use format)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "resolve_company",
        "description": (
            "Look up a company name or alias in the supported registry and "
            "return its canonical name plus the Workday tenant/site needed "
            "to search it. Always call this FIRST so you can pass the exact "
            "tenant and site to search_workday. If the company is unknown "
            "the tool returns {error: 'unknown_company', suggestions: [...]} "
            "and you should ask the user to pick one of the suggestions "
            "rather than guessing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Company name or alias as the user typed it, "
                        "e.g. 'pwc', 'JP Morgan', 'SFDC', 'NVIDIA'."
                    ),
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_workday",
        "description": (
            "Query a company's Workday careers API for postings. Returns "
            "{count: int, postings: [...]} where each posting has fields "
            "company, job_id, title, location, posted_on, url. The keyword "
            "is matched server-side (searchText); the location is filtered "
            "client-side as a substring of the posting's location string. "
            "Pagination is handled internally; pass limit to cap results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tenant": {
                    "type": "string",
                    "description": "Workday tenant from resolve_company.",
                },
                "site": {
                    "type": "string",
                    "description": "Workday site from resolve_company.",
                },
                "canonical": {
                    "type": "string",
                    "description": (
                        "Canonical company name from resolve_company "
                        "(e.g. 'PricewaterhouseCoopers')."
                    ),
                },
                "keyword": {
                    "type": "string",
                    "description": (
                        "Topical search term, e.g. 'AI', 'data engineer', "
                        "'machine learning'. Empty string for no filter."
                    ),
                },
                "location": {
                    "type": ["string", "null"],
                    "description": (
                        "Optional city / country substring filter, e.g. "
                        "'Bangalore', 'Mountain View'. null for none."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max postings to return. Default 100.",
                },
            },
            "required": ["tenant", "site", "canonical"],
        },
    },
    {
        "name": "save_results",
        "description": (
            "Persist a list of postings to a timestamped CSV and upsert "
            "into the shared output/jobs.db SQLite database. Returns "
            "{csv_path, sqlite_path, rows}. Call this after search_workday "
            "with the postings array it returned (pass it through unchanged)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "canonical": {
                    "type": "string",
                    "description": "Canonical company name (for filename + PK).",
                },
                "keyword": {
                    "type": "string",
                    "description": (
                        "Keyword used in the search, for the CSV filename. "
                        "Use 'all' if no keyword was supplied."
                    ),
                },
                "postings": {
                    "type": "array",
                    "description": (
                        "Array of posting dicts returned by search_workday. "
                        "Pass through unchanged — do not edit or summarise."
                    ),
                    "items": {"type": "object"},
                },
            },
            "required": ["canonical", "postings"],
        },
    },
    {
        "name": "validate_output",
        "description": (
            "Re-open the CSV and SQLite written by save_results and run "
            "four schema/integrity checks. Returns {ok, checks, issues} "
            "where ok is true only if every check passed. Call this LAST "
            "before summarising to the user so failures surface explicitly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_path": {
                    "type": "string",
                    "description": "Absolute path returned by save_results.",
                },
                "sqlite_path": {
                    "type": "string",
                    "description": "Absolute path returned by save_results.",
                },
                "canonical": {
                    "type": "string",
                    "description": "Canonical company name for SQLite filter.",
                },
            },
            "required": ["csv_path", "sqlite_path", "canonical"],
        },
    },
]


# ---------------------------------------------------------------------------
# Python implementations
# ---------------------------------------------------------------------------


def tool_resolve_company(name: str) -> dict[str, Any]:
    company = companies_mod.resolve_company(name)
    if company is None:
        return {
            "error": "unknown_company",
            "input": name,
            "suggestions": companies_mod.known_companies(),
        }
    return {
        "canonical": company.canonical_name,
        "tenant": company.tenant,
        "site": company.site,
        "base_url": company.base_url,
    }


def tool_search_workday(
    tenant: str,
    site: str,
    canonical: str,
    keyword: str = "",
    location: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    # We rebuild a Company from the resolver because the tool args came from
    # Claude — the registry remains the source of truth for base_url.
    company = companies_mod.resolve_company(canonical)
    if company is None:
        # Fall back to a synthesised Company when canonical is unrecognised
        # (defensive — should never happen since resolve_company gates this).
        return {"error": "unknown_company", "canonical": canonical}

    postings = workday_mod.search_jobs(
        company,
        keywords=keyword or "",
        location=location or None,
        limit=int(limit),
    )
    return {
        "count": len(postings),
        "postings": [p.to_dict() for p in postings],
    }


def tool_save_results(
    canonical: str,
    postings: list[dict[str, Any]],
    keyword: str = "all",
    output_dir: Path = Path("output"),
) -> dict[str, Any]:
    objs = [JobPosting(**row) for row in postings]
    csv_path = storage_mod.write_csv(
        objs, canonical, keyword or "all", output_dir=output_dir
    )
    db_path = storage_mod.write_sqlite(objs, canonical, output_dir=output_dir)
    return {
        "csv_path": str(csv_path),
        "sqlite_path": str(db_path),
        "rows": len(objs),
    }


def tool_validate_output(
    csv_path: str,
    sqlite_path: str,
    canonical: str,
) -> dict[str, Any]:
    issues: list[str] = []
    checks: dict[str, Any] = {}

    cols = storage_mod.csv_columns(Path(csv_path))
    checks["csv_schema_ok"] = cols == storage_mod.EXPECTED_CSV_COLUMNS
    if not checks["csv_schema_ok"]:
        issues.append(
            f"csv schema mismatch: expected {storage_mod.EXPECTED_CSV_COLUMNS}, "
            f"got {cols}"
        )

    csv_rows = storage_mod.count_csv_rows(Path(csv_path))
    checks["csv_row_count"] = csv_rows
    if csv_rows <= 0:
        issues.append("csv has zero data rows")

    duplicates = storage_mod.csv_duplicate_job_ids(Path(csv_path))
    checks["csv_duplicates"] = duplicates
    if duplicates:
        issues.append(f"csv has duplicate job_ids: {duplicates}")

    sqlite_rows = storage_mod.sqlite_row_count(Path(sqlite_path), canonical)
    checks["sqlite_row_count"] = sqlite_rows
    if sqlite_rows < csv_rows:
        issues.append(
            f"sqlite row count ({sqlite_rows}) is less than csv "
            f"row count ({csv_rows}) for company={canonical!r}"
        )

    return {
        "ok": not issues,
        "checks": checks,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch(
    name: str,
    arguments: dict[str, Any],
    output_dir: Path = Path("output"),
) -> dict[str, Any]:
    """Run the named tool with the supplied arguments. Pure Python — no LLM.

    Returns a JSON-serialisable dict to be wrapped in a `tool_result` block.
    Catches per-tool exceptions and returns an `error` payload so the loop
    can continue (the model can decide to recover or surrender).
    """
    try:
        if name == "resolve_company":
            return tool_resolve_company(arguments.get("name", ""))
        if name == "search_workday":
            return tool_search_workday(
                tenant=arguments.get("tenant", ""),
                site=arguments.get("site", ""),
                canonical=arguments.get("canonical", ""),
                keyword=arguments.get("keyword", "") or "",
                location=arguments.get("location"),
                limit=int(arguments.get("limit") or 100),
            )
        if name == "save_results":
            return tool_save_results(
                canonical=arguments.get("canonical", ""),
                postings=arguments.get("postings") or [],
                keyword=arguments.get("keyword", "all") or "all",
                output_dir=output_dir,
            )
        if name == "validate_output":
            return tool_validate_output(
                csv_path=arguments.get("csv_path", ""),
                sqlite_path=arguments.get("sqlite_path", ""),
                canonical=arguments.get("canonical", ""),
            )
        return {"error": "unknown_tool", "name": name}
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": type(exc).__name__, "message": str(exc)}


__all__ = [
    "TOOLS",
    "dispatch",
    "tool_resolve_company",
    "tool_search_workday",
    "tool_save_results",
    "tool_validate_output",
]
