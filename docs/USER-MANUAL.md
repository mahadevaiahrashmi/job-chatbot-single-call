# User Manual

A friendly, step-by-step guide to running `job-chatbot-single-call`. No
Python knowledge required — if you can copy and paste a shell command,
you can use this tool.

---

## What this tool does

Type a request in plain English — for example, *"find AI jobs at PwC in
Bangalore"* — and the bot turns it into a real search against PwC's
careers website. It quietly fetches **every** matching job posting, saves
them as a spreadsheet (CSV file) and a small database (SQLite file) on
your computer, and tells you how many it found.

This is the **single-call** sibling. Where the other four implementations
in this family (anthropic-sdk, langchain, crewai, vteam-hybrid) coordinate
four separate AI agents, this one uses a single Claude call that knows
about all four tools and figures out the order itself. You get the same
spreadsheet and database files; the bot is just simpler under the hood.

---

## What you need before starting

- A computer running **macOS, Linux, or Windows** (with WSL or Git Bash
  on Windows).
- **Python 3.11 or newer.** Check with `python3 --version`. If you don't
  have it, grab it from
  [python.org/downloads](https://www.python.org/downloads/).
- An **Anthropic API key**. Sign up at
  [console.anthropic.com](https://console.anthropic.com), create a key
  under *API Keys*, and copy the value (it starts with `sk-ant-`).
- **`uv`** — a fast Python project manager. Install with one line:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`.

That's it. No databases to set up, no servers to configure.

---

## Installing for the first time

Open a terminal and run these commands one at a time:

```bash
# 1. Clone the repository
git clone git@github.com:mahadevaiahrashmi/job-chatbot-single-call.git

# 2. Move into the project folder
cd job-chatbot-single-call

# 3. Create an isolated Python environment
uv venv

# 4. Install all dependencies
uv sync

# 5. Copy the example environment file
cp .env.example .env
```

Now open the `.env` file in any text editor (TextEdit, Notepad, VS Code…)
and replace the placeholder with your real Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-paste-your-real-key-here
```

Save and close the file. You're done installing.

---

## Running the bot

From the project folder, run:

```bash
uv run job-chatbot-single-call
```

You'll see a welcome banner and a prompt that looks like this:

```
you>
```

That's where you type your question. The bot waits there until you press
Enter. Each line you type kicks off one search — usually 5–15 seconds of
work — and prints a summary panel when it's done.

There are two special commands:

- Type **`companies`** to see the full list of supported companies.
- Type **`quit`** (or `exit`, or press Ctrl+D) to leave.

You can also run a **single query non-interactively**:

```bash
uv run job-chatbot-single-call -q "find AI jobs at PwC in Bangalore"
```

This is handy for scripts or cron jobs.

---

## Example queries

Here are eight queries you can try right away. After each, the bot creates
a CSV inside the `output/` folder and appends the same rows to
`output/jobs.db`.

| You type | What the bot does |
|---|---|
| `find AI jobs at PwC in Bangalore` | Searches PwC's Workday site for "AI", keeps only postings whose location mentions Bangalore. Saves `output/pricewaterhousecoopers_ai_<date>.csv`. |
| `Find data scientist jobs at NVIDIA` | Searches NVIDIA worldwide for "data scientist". Saves `output/nvidia_data_scientist_<date>.csv`. |
| `List all PwC AI roles in Bangalore` | Same as the first query — the bot is forgiving about phrasing. |
| `get data engineer openings from Salesforce` | Searches Salesforce's careers site for "data engineer". |
| `show me all machine learning jobs at Adobe` | Searches Adobe for "machine learning". Often returns 50–100 results. |
| `Cisco openings in San Jose` | No keyword filter — returns every Cisco posting whose location mentions San Jose. |
| `JPMorgan Chase software engineer roles` | Recognises "JPMorgan Chase", "JP Morgan", "JPMC", and "Chase" as the same company. |
| `Netflix engineering jobs` | Returns Netflix engineering postings worldwide. |

When a query succeeds you'll see something like:

```
+- result -------------------------------------------------------------+
| Found 17 AI postings at PricewaterhouseCoopers in Bangalore.         |
| Saved to /.../output/pricewaterhousecoopers_ai_2026-05-25.csv        |
| and upserted into /.../output/jobs.db.                               |
| Validation: 4/4 checks passed.                                       |
+----------------------------------------------------------------------+
```

The exact wording is up to Claude — the system prompt asks for a short
summary covering company, count, file paths, and validation status.

---

## Where the results live

Every artifact ends up in the `output/` folder next to where you ran the
command:

- **`output/<company>_<keyword>_<date>.csv`** — one CSV per query.
  Example: `output/nvidia_data_scientist_2026-05-25.csv`. Open it in
  Excel, Numbers, Google Sheets, or any text editor.
- **`output/jobs.db`** — a single SQLite database that accumulates every
  posting you've ever fetched across every company. Browse it with free
  tools like [DB Browser for SQLite](https://sqlitebrowser.org/) or query
  from the command line with `sqlite3 output/jobs.db`.

The database is **idempotent**: running the same query twice doesn't
create duplicates. If a posting changes (new title, new location), the
database row is updated in place — the primary key is
`(company, job_id)`.

---

## Reading the CSV

Every CSV has the same six columns, in this order:

| Column | What it means |
|---|---|
| **company** | Canonical company name (e.g. `PricewaterhouseCoopers`, not `pwc`). |
| **job_id** | Unique ID assigned by the careers site, e.g. `712616WD`. Use this when applying or following up. |
| **title** | Job title as posted, e.g. `Senior Manager - AI/ML`. |
| **location** | Free-text location string from the careers site. |
| **posted_on** | When the listing went live, in the careers site's own format. |
| **url** | Direct link to the posting. Click it to apply or read the full description. |

The bot guarantees no two rows in the same CSV share a `job_id` — the
scraper de-duplicates by ID and the `validate_output` tool double-checks.

---

## Supported companies

The bot currently knows about these eight Workday-hosted careers sites:

- Adobe
- Cisco
- JPMorgan Chase
- Netflix
- NVIDIA
- PricewaterhouseCoopers
- Salesforce
- Workday

You don't have to type the canonical name — common aliases work too:

- `pwc`, `pricewaterhousecoopers`, `pwc india` → PwC.
- `jp morgan`, `jpmc`, `chase`, `jpmorgan chase` → JPMorgan Chase.
- `sfdc` → Salesforce.

If the bot can't recognise the company you typed, it'll tell you and list
the supported ones — and it will **ask you which one you meant** rather
than picking for you.

---

## Common questions / troubleshooting

**Q: Why is it asking me for an Anthropic key?**
The single Claude call is powered by Anthropic's API, so the bot needs
to authenticate. Make sure your `.env` file contains
`ANTHROPIC_API_KEY=sk-ant-...` with a valid key, and that you're running
the command from the project folder (so `.env` is in the current
directory).

**Q: Why is no CSV being created?**
A few things to check, in order:
1. Read the summary panel — Claude tells you what happened.
2. If the count is `0`, your keyword + location combination probably has
   zero matches on the careers site. Try a broader query.
3. If you see a network error, the careers site may be temporarily down.
   Try again in a minute.
4. Confirm the `output/` folder exists (the bot creates it automatically
   but restrictive permissions can block this).

**Q: What if my company isn't listed?**
Right now the bot only supports the eight companies above. Adding a new
one is a one-line change in `src/job_chatbot_single_call/companies.py` —
see `docs/SYSTEM-DESIGN.md` for instructions. If you don't write code,
file an issue on the repo with the company name and the URL of their
careers site.

**Q: How is this different from the four sibling repos?**
The other four (`job-chatbot-anthropic-sdk`, `job-chatbot-langchain`,
`job-chatbot-crewai`, `job-chatbot-vteam-hybrid`) coordinate **four**
specialist AI agents — one per stage. This one uses **one** Claude call
that sees all four tools at once. Same input, same output files. The
single-call version is usually cheaper and faster; the multi-agent
versions are easier to extend stage-by-stage.

**Q: How do I stop it?**
Type `quit` and press Enter, or press **Ctrl+C** / **Ctrl+D** at the
prompt.

**Q: How fresh is the data?**
Every query hits the company's live careers site in real time — there's
no caching. What you see is what the company is showing on its public
careers page at that moment.

**Q: Can I run it without internet?**
No. The bot needs to talk to both the Anthropic API and the company's
careers website.

---

## Privacy & cost

**Cost.** Each query is one Claude conversation. Because there's no
agent-to-agent prompt overhead, a single-call run typically costs **1/3
to 1/2 what a 4-agent run costs**. With Claude Haiku the total is still
a small fraction of a US cent per query. Exact usage shows up under
*Usage* on console.anthropic.com.

**Privacy.** Job listings are downloaded from public careers sites to
your local machine. Nothing about you (your name, your CV, your search
history) is sent anywhere — the bot doesn't have or need any personal
information. The only data sent to Anthropic is the literal text of your
query plus the tool-call responses Claude needs to do its job; no scraped
postings ever leave your computer except by your own choice.
