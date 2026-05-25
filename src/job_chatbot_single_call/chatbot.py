"""The single tool-use loop.

This is the *whole* orchestration story for this implementation. There is
no agent graph, no specialist sub-agents, no per-stage system prompt — just
one `client.messages.create` call in a loop, with all four tools exposed
simultaneously. Claude picks the order, the dispatcher runs each tool, and
we feed the results back until `stop_reason == "end_turn"`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic

from .tools import TOOLS, dispatch

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096
MAX_ITERATIONS = 12  # safety bound on the tool-use loop

SYSTEM_PROMPT = """You are a job-search assistant.

Your job: take a user's free-form request (e.g. "find AI jobs at PwC in
Bangalore") and produce a clean CSV + SQLite snapshot of every matching
posting on the company's Workday careers site.

Typical workflow (you may diverge if a tool fails):
  1. resolve_company   - look up the company alias; get tenant + site.
  2. search_workday    - fetch postings using that tenant + site.
  3. save_results      - persist the postings to CSV + SQLite.
  4. validate_output   - sanity-check both artifacts.
  5. Reply with a short summary: company, count, file paths, validation.

Rules:
- If resolve_company returns {error: "unknown_company", suggestions: [...]},
  do NOT guess. Ask the user which supported company they meant.
- Treat words like "AI", "data engineer", "machine learning" as the keyword.
- Treat city/country names ("Bangalore", "Mountain View") as the location.
- Pass the postings array from search_workday into save_results unchanged.
- If validate_output reports ok=false, mention the issues in your summary.
- Keep the final reply to under 6 lines.
"""


def _content_to_blocks(content: Any) -> list[dict[str, Any]]:
    """Coerce SDK content blocks into plain dicts for message history."""
    result: list[dict[str, Any]] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            result.append({"type": "text", "text": block.text})
        elif getattr(block, "type", None) == "tool_use":
            result.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": dict(block.input),
                }
            )
    return result


def _final_text(content: Any) -> str:
    """Return the concatenated text from the assistant's final turn."""
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(p.strip() for p in parts if p.strip())


def run_query(
    user_message: str,
    client: anthropic.Anthropic | None = None,
    output_dir: Path = Path("output"),
    max_iterations: int = MAX_ITERATIONS,
) -> str:
    """Drive the single tool-use loop. Returns Claude's final summary text."""
    client = client or anthropic.Anthropic()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message}
    ]

    final_text = ""
    for _ in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Preserve full assistant turn (text + tool_use blocks) in history.
        messages.append(
            {"role": "assistant", "content": _content_to_blocks(response.content)}
        )

        if response.stop_reason == "end_turn":
            final_text = _final_text(response.content)
            break

        if response.stop_reason != "tool_use":
            # Either max_tokens or an unexpected stop — surface whatever text
            # we got and exit.
            final_text = _final_text(response.content) or (
                f"[stopped: {response.stop_reason}]"
            )
            break

        # Execute every tool_use in this turn, build one user message with
        # all the tool_result blocks, append, and loop.
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            result = dispatch(block.name, dict(block.input), output_dir=output_dir)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return final_text or "[no final text emitted]"


__all__ = ["run_query", "SYSTEM_PROMPT", "MODEL"]
