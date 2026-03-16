# CLAUDE.md

## Project Overview

nf-core-bot is a Slack bot for the nf-core bioinformatics community. The primary feature is hackathon registration management, with future plans for community health tooling.

## Tech Stack

- **Language:** Python 3.12+
- **Framework:** Slack Bolt for Python
- **Database:** AWS DynamoDB (single-table design)
- **Hosting:** AWS ECS Fargate
- **External APIs:** GitHub REST API (org membership checks)
- **Infrastructure:** CloudFormation / SAM

## Key Design Decisions

- Single slash command `/nf-core-bot` with subcommand routing (Slack only allows one slash command per app)
- YAML-first hackathon lifecycle: metadata (title, status, dates, channel, URL) and form definitions live in YAML files in `forms/`. To create/open/close/archive a hackathon, edit the YAML and push — no admin slash commands needed.
- A JSON schema at `schemas/hackathon-form.schema.json` validates YAML files and provides VS Code IntelliSense
- DynamoDB single-table design with composite keys (see README.md for schema) — stores only sites, organisers, and registrations (not hackathon metadata)
- Two-tier permissions: `@core-team` Slack user group = global admin, site organisers = scoped to their hackathon site
- All bot responses are ephemeral (only visible to the caller) unless explicitly posting to a channel
- GitHub checks happen pre-registration: Slack profile → GitHub username field → GitHub API org membership check

## Architecture

```
Slack ←→ ECS Fargate (Bolt app) ←→ DynamoDB ←→ GitHub API
```

## Commands to Run

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run the bot locally (needs local DynamoDB + ngrok/tunnel)
docker compose up -d dynamodb-local
python -m nf_core_bot.app

# Lint
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/
```

## Auto-populated from Slack profile for Hackathon registration (not in form YAML)

- `email`, `slack_user_id`, `slack_display_name`, `github_username` — read from Slack profile API at registration time and stored in the registration record automatically

## Project Structure

- `src/nf_core_bot/app.py` — Bolt app entrypoint and slash command registration
- `src/nf_core_bot/commands/router.py` — Parses subcommands, dispatches to handlers
- `src/nf_core_bot/commands/help.py` — Permission-aware help
- `src/nf_core_bot/commands/hackathon/admin.py` — Admin command handlers (list, preview, site/organiser management)
- `src/nf_core_bot/commands/hackathon/attendees.py` — Attendee listing (permission-scoped)
- `src/nf_core_bot/commands/hackathon/list_cmd.py` — User-facing hackathon list
- `src/nf_core_bot/commands/hackathon/register.py` — Register, edit, cancel handlers
- `src/nf_core_bot/commands/github/` — GitHub org management commands (add-member, message shortcut)
- `src/nf_core_bot/forms/loader.py` — YAML form parser, metadata functions, validation
- `src/nf_core_bot/forms/builder.py` — Block Kit modal view generator
- `src/nf_core_bot/forms/handler.py` — Modal submission handler, preview mode, channel join
- `src/nf_core_bot/checks/` — GitHub API and Slack profile validation
- `src/nf_core_bot/db/client.py` — DynamoDB singleton client
- `src/nf_core_bot/db/registrations.py` — Registration CRUD with GSI1 support
- `src/nf_core_bot/db/sites.py` — Site and organiser CRUD
- `src/nf_core_bot/permissions/checks.py` — Core-team cache + organiser checks
- `forms/` — YAML form definitions, one per hackathon
- `schemas/` — JSON Schema for YAML validation
- `infra/` — CloudFormation templates for AWS deployment

## Coding Conventions

- Use `ruff` for linting and formatting
- Type hints throughout (enforce with mypy)
- Async where Bolt supports it (Bolt's async adapter)
- Keep command handlers thin — business logic in db/ and forms/ modules
- Tests use moto for DynamoDB mocking and Slack's test fixtures

## DynamoDB Key Patterns

- `PK=HACKATHON#<id> SK=SITE#<site-id>` — site info
- `PK=HACKATHON#<id> SK=SITE#<site-id>#ORG#<user-id>` — organiser
- `PK=HACKATHON#<id> SK=REG#<user-id>` — registration
- GSI1: `GSI1PK=HACKATHON#<id>#SITE#<site-id>` — query registrations by site

Note: The `PK=HACKATHON#<id> SK=META` pattern is no longer used. Hackathon metadata is in YAML files.

## Important Notes

- Slack modals have a 100-element limit per view — split forms across multiple modal steps
- Slack gives 3 seconds to acknowledge interactions — ack immediately, do async work after
- The `@core-team` user group membership is cached and refreshed every 5 minutes
- Form YAML supports `options_from: sites` for dynamic option lists populated from DynamoDB
- GitHub API calls use a fine-grained PAT with `admin:org` scope (needed for org invitations and team management)
- The `github add-member` command posts visible thread replies (not ephemeral) so the original requester can see them
- Slack profile GitHub field ID is discovered dynamically via `team.profile.get` and cached for the process lifetime

Note: `db/hackathons.py` no longer exists. Hackathon metadata comes from YAML files.
