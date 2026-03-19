# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

nf-core-bot is a Slack bot for the nf-core bioinformatics community. Features
include hackathon registration management, GitHub org invitation tooling, and
on-call rotation scheduling for the core team.

## Tech Stack

- **Language:** Python 3.12+
- **Framework:** Slack Bolt for Python (async adapter)
- **Database:** AWS DynamoDB (single-table design)
- **Hosting:** AWS ECS Fargate
- **External APIs:** GitHub REST API (org membership, invitations)
- **Infrastructure:** CloudFormation / SAM

## Commands to Run

```bash
pip install -e ".[dev]"          # Install dependencies

pytest                           # Run all tests
pytest tests/test_admin.py       # Run one test file
pytest -k test_valid_username    # Run tests matching a name

ruff check src/ tests/           # Lint
ruff format src/ tests/          # Format
mypy src/                        # Type check

# Local development (needs DynamoDB Local + Slack app tokens)
docker compose up -d dynamodb-local
python -m nf_core_bot.app
```

## Architecture

```
Slack ←→ ECS Fargate (Bolt app) ←→ DynamoDB ←→ GitHub API
```

### Three slash-command namespaces share one router

`/nf-core` handles top-level help, GitHub commands, and on-call commands.
`/hackathon` handles all hackathon commands. Both are registered in `app.py` and
delegate to `commands/router.py` which parses subcommands and dispatches to
handlers.

### Multi-step modal flow (the critical cross-file path)

Registration uses a multi-step Slack modal. Understanding this flow requires
reading across four files:

1. **`forms/loader.py`** — Parses hackathon YAML into `FormDefinition` →
   `FormStep` → `FormField` dataclasses. Evaluates conditional steps.
2. **`forms/builder.py`** — Converts a `FormStep` into a Slack Block Kit modal
   view dict. Handles pre-population from existing answers.
3. **`forms/handler.py`** — Orchestrates the flow: `open_registration_modal()`
   opens step 0; `handle_registration_step()` extracts values, merges with
   accumulated answers in `private_metadata`, then either advances (via
   `response_action: "update"`) or finalises (persists to DynamoDB + joins
   channel).
4. **`app.py`** — Registers a regex callback `hackathon_reg_step_\d+` that
   routes all step submissions to the handler.

Answers accumulate in `private_metadata` (JSON, max 3000 chars) across steps.

### YAML-first hackathon lifecycle

Hackathon metadata lives in YAML files in `hackathons/`, not in the database. To
create/open/close/archive a hackathon, edit the YAML `status` field and push.
DynamoDB stores only sites, organisers, and registrations.

### GitHub invite flow

`commands/github/invite_flow.py` contains the shared org-invite + team-add logic
used by both the slash command (`add_member.py`) and the message shortcut
(`add_member_shortcut.py`). Both pass a `reply` callback for message delivery.

### On-call rotation

The on-call system manages a weekly rotation for `@core-team` members. All
on-call commands live under `/nf-core on-call <subcommand>` and are restricted
to `@core-team` members (permission checked centrally in `_route_oncall()`).

Key files:

- **`commands/oncall/`** — Slash-command handlers (`list`, `me`, `switch`,
  `skip`, `unavailable`, `reboot`). The router calls `ack()` once and checks
  `is_core_team()` before dispatching, so individual handlers do **not** receive
  or call `ack`.
- **`db/oncall.py`** — DynamoDB CRUD for roster entries, round-robin state,
  unavailability ranges, and reminder tracking.
- **`scheduler/oncall_jobs.py`** — Background `asyncio` task launched in
  `app.py`'s `_start()`. Runs every 60 seconds. Monday jobs (roster extension,
  cleanup) fire once per week via a `_last_weekly_run` guard. Daily reminders
  respect each user's Slack timezone.
- **`commands/oncall/helpers.py`** — Shared utilities: `monday_of_week`,
  `format_week_range`, `parse_date_arg`.

The round-robin algorithm picks the person who went longest without being on
call, with `queue_front` priority for people who previously skipped. When all
members have been assigned in the current window, it cycles through again.

## Key Design Decisions

- DynamoDB single-table design with composite keys — see key patterns below
- Two-tier permissions: `@core-team` Slack user group = global admin, site
  organisers = scoped to their hackathon site
- All bot responses are ephemeral (only visible to the caller) unless explicitly
  posting to a channel (e.g. `github add` posts visible thread replies)
- Form YAML supports `options_from: sites` for dynamic option lists populated
  from DynamoDB, and `options_from: countries` for type-ahead country search
- GitHub API calls use a fine-grained PAT with `admin:org` scope
- Slack profile GitHub field ID is discovered dynamically via `team.profile.get`
  and cached for the process lifetime
- `@core-team` user group membership is cached and refreshed every 5 minutes

## DynamoDB Key Patterns

- `PK=HACKATHON#<id> SK=SITE#<site-id>` — site info
- `PK=HACKATHON#<id> SK=SITE#<site-id>#ORG#<user-id>` — organiser
- `PK=HACKATHON#<id> SK=REG#<user-id>` — registration
- GSI1: `GSI1PK=HACKATHON#<id>#SITE#<site-id>` — query registrations by site

Note: The `PK=HACKATHON#<id> SK=META` pattern is no longer used. Hackathon
metadata is in YAML files. `db/hackathons.py` no longer exists.

### On-call key patterns

- `PK=ONCALL#<week-start-date> SK=ROSTER` — weekly roster entry (assigned user,
  status)
- `PK=ONCALL_META SK=ROUND_ROBIN` — round-robin state (last-assigned dates,
  queue-front priority list)
- `PK=ONCALL_META SK=REMINDERS#<week-start-date>` — tracks which reminders have
  been sent for a given week
- `PK=ONCALL_UNAVAIL#<user-id> SK=<start-date>#<end-date>` — unavailability
  range

## Auto-populated from Slack profile (not in form YAML)

`email`, `slack_user_id`, `slack_display_name`, `github_username` — read from
Slack profile API at registration time and stored in the registration record
automatically.

## Coding Conventions

- Use `ruff` for linting and formatting (line length 120)
- Type hints throughout (enforce with `mypy --strict`)
- Async everywhere — Bolt's async adapter, `asyncio.to_thread` for boto3 calls
- Keep command handlers thin — business logic in `db/`, `forms/`, `checks/`
- Tests use `moto` for DynamoDB mocking; `pytest-asyncio` with
  `asyncio_mode = "auto"`

## Important Slack Constraints

- Modals have a 100-element limit per view — split forms across multiple steps
- Slack gives 3 seconds to acknowledge interactions — `ack()` immediately, do
  async work after
- `private_metadata` has a 3000-character limit — answers are JSON-compressed
- Modal title max 24 characters — titles are truncated with ellipsis
