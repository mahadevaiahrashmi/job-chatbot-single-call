"""CLI entry point: ``job-chatbot-single-call``.

Starts an interactive REPL. Each user prompt drives one tool-use loop via
``chatbot.run_query`` — no orchestrator, no sub-agents.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .chatbot import run_query
from .companies import known_companies

BANNER = """[bold]job-chatbot-single-call[/bold]
Single Claude call + four tools. No sub-agents, no orchestrator.

Type a request like:
  [italic]find AI jobs at PwC in Bangalore[/italic]
  [italic]get data engineer openings from Salesforce[/italic]

Type 'companies' to list supported companies, 'quit' to exit.
"""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="job-chatbot-single-call")
    parser.add_argument(
        "-q",
        "--query",
        help="Run a single query non-interactively and exit.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for CSV + SQLite artifacts (default: output).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    console = Console()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[red]ANTHROPIC_API_KEY is not set. "
            "Copy .env.example to .env and fill in your key.[/red]"
        )
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Non-interactive single-shot mode.
    if args.query:
        try:
            result = run_query(args.query, output_dir=output_dir)
        except Exception as exc:  # pragma: no cover - defensive
            console.print(f"[red]Error: {exc}[/red]")
            return 1
        console.print(Panel(result, title="result"))
        return 0

    # Interactive REPL.
    console.print(Panel.fit(BANNER))
    while True:
        try:
            user = console.input("[bold cyan]you>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0

        if not user:
            continue
        if user.lower() in {"quit", "exit", ":q"}:
            return 0
        if user.lower() == "companies":
            console.print("Supported: " + ", ".join(known_companies()))
            continue

        try:
            result = run_query(user, output_dir=output_dir)
        except Exception as exc:  # pragma: no cover - defensive
            console.print(f"[red]Error: {exc}[/red]")
            continue

        console.print(Panel(result, title="result"))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
