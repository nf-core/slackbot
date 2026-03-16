# nf-core-bot

A Slack bot for the nf-core community, providing hackathon registration management and GitHub organisation tooling.

Built with [Slack Bolt for Python](https://slack.dev/bolt-python/), hosted on AWS (ECS Fargate + DynamoDB).

## Features

### Hackathon Registration

- **In-Slack registration** via slash commands and multi-step modal forms
- **GitHub validation** — checks Slack profile for GitHub username, verifies nf-core org membership
- **Multi-step forms** with conditional logic (online vs in-person, site selection)
- **Form definitions in YAML** — one file per hackathon, version controlled
- **Dynamic options** — `options_from: sites` populates from DynamoDB, `options_from: countries` from a built-in list
- **Profile auto-population** — email, Slack display name, and GitHub username are read from the Slack profile API
- **Self-service** — users can edit or cancel their own registrations
- **YAML-driven lifecycle** — hackathon metadata and status managed in version-controlled YAML files
- **JSON schema validation** — `schemas/hackathon-form.schema.json` with VS Code IntelliSense support
- **Site management** — add/remove local sites per hackathon
- **Organiser access** — site organisers can pull attendee lists for their site(s)
- **Permission model** — admin commands restricted to `@core-team` Slack user group

### GitHub Organisation Management

- **Slash command** — invite a Slack user or GitHub username to the nf-core org
- **Message shortcut** — right-click any message to invite its author to the org
- **Team membership** — automatically adds invited users to the contributors team

### Future Work

- `/nf-core-bot community audit` — scan all Slack users for GitHub profile field
- Check nf-core org membership across the community
- Check public org membership visibility
- Scheduled reports / nudge DMs for missing info

## Architecture

```
Slack ←→ ECS Fargate (Bolt app, Python)
              ↕                  ↕
          DynamoDB           YAML form files
    (sites, organisers,     (hackathon metadata,
     registrations)          form definitions)
              ↕
          GitHub API (org membership checks + invitations)
```

Hackathon lifecycle (creation, status changes, form definitions) is managed entirely through YAML files in the `forms/` directory. Creating or updating a hackathon means editing a YAML file and pushing to `main` — the bot auto-deploys and picks up the changes. DynamoDB is used only for runtime data: sites, organisers, and registrations.

### AWS Services

- **ECS Fargate** — single task, always-on container running the Bolt app in Socket Mode
- **DynamoDB** — single table, on-demand capacity (free tier is plenty)
- **ECR** — container registry for the bot image
- **SSM Parameter Store** — secrets (Slack tokens, GitHub PAT)
- **CloudWatch** — logs and basic monitoring

### DynamoDB Single-Table Design

DynamoDB stores runtime data only — sites, organisers, and registrations. Hackathon metadata (title, status, dates, channel, URL) lives in YAML files.

Partition key: `PK`, Sort key: `SK`

| Entity       | PK               | SK                                   | Key attributes                                                                                   |
| ------------ | ---------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Site         | `HACKATHON#<id>` | `SITE#<site-id>`                     | site_id, name, city, country, created_by                                                         |
| Organiser    | `HACKATHON#<id>` | `SITE#<site-id>#ORG#<slack-user-id>` | slack_id, added_by, added_at                                                                     |
| Registration | `HACKATHON#<id>` | `REG#<slack-user-id>`                | slack_id, github_username, status (active/cancelled), form_data (map), registered_at, updated_at |

**GSI1** — for querying registrations by site:

- GSI1PK: `HACKATHON#<id>#SITE#<site-id>`, GSI1SK: `REG#<slack-user-id>`

### Permission Model

Two tiers:

1. **@core-team** (Slack user group) — global admin, all commands
2. **Site organiser** (per-hackathon, per-site in DynamoDB) — can view attendees for their site(s)

Admin check: on every admin command, bot calls `usergroups.users.list` for the `@core-team` group (cached, refreshed every 5 min) and checks if the caller is in the list.

## Command Reference

```bash
# Help
/nf-core-bot help
/nf-core-bot hackathon help
/nf-core-bot github help

# User commands
/nf-core-bot hackathon list                      # List hackathons with dates, status, event URL
/nf-core-bot hackathon register                   # Register for the active hackathon
/nf-core-bot hackathon edit                       # Edit your registration
/nf-core-bot hackathon cancel                     # Cancel your registration

# Organiser commands (site-scoped)
/nf-core-bot hackathon attendees [hackathon-id]   # List attendees for your site(s)

# Admin commands (@core-team only)
/nf-core-bot hackathon admin list                  # All hackathons (including draft/archived)
/nf-core-bot hackathon admin preview <hackathon-id> # Preview registration form (no data saved)

/nf-core-bot hackathon admin add-site <hackathon-id> <site-id> <name> | <city> | <country>
/nf-core-bot hackathon admin remove-site <hackathon-id> <site-id>
/nf-core-bot hackathon admin list-sites <hackathon-id>

/nf-core-bot hackathon admin add-organiser <hackathon-id> <site-id> @user
/nf-core-bot hackathon admin remove-organiser <hackathon-id> <site-id> @user

/nf-core-bot hackathon attendees [hackathon-id]   # Admin sees all sites

# GitHub commands (@core-team only)
/nf-core-bot github add-member @slack-user        # Invite a specific Slack user
/nf-core-bot github add-member <github-username>  # Invite by GitHub username directly
# Message shortcut: right-click a message → More actions → "Add to GitHub org"
```

See [docs/commands.md](docs/commands.md) for full command reference with examples.

**Notes:**

- Slack allows only one slash command per app — `/nf-core-bot` is the entry point, everything else is parsed as subcommands
- Slack does not allow custom slash commands in threads — use the "Add to GitHub org" message shortcut instead
- Hackathon lifecycle (create, open, close, archive) is managed by editing YAML files in `forms/` — not via slash commands
- `hackathon register` targets the currently open hackathon (error if zero or multiple are open)
- All responses to commands are **ephemeral** (only visible to the caller) unless explicitly posting to a channel
- Exception: `github add-member` posts **visible thread replies** so the original requester can see the outcome
- `help` at each level only shows commands the caller has permission to use

## Form Configuration

Forms are defined in YAML, one per hackathon. Each file contains both the hackathon metadata (title, status, dates, etc.) and the form step definitions. A JSON schema at `schemas/hackathon-form.schema.json` validates the YAML and provides VS Code IntelliSense via the [Red Hat YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml).

See `forms/2026-march.yaml` for a full example. Abbreviated structure:

```yaml
# forms/2026-march.yaml
# yaml-language-server: $schema=../schemas/hackathon-form.schema.json
hackathon: 2026-march
title: "nf-core Hackathon — March 2026"
status: draft          # draft | open | closed | archived
channel: https://nfcore.slack.com/archives/C0ACF0TPF5E
url: https://nf-co.re/events/2026/hackathon-march-2026
date_start: "2026-03-11"
date_end: "2026-03-13"
steps:
  - id: welcome
    title: "nf-core Hackathon — March 2026"
    type: statement
    text: |
      Please note that the hackathon is not a training event.
      By registering you are agreeing to abide by our Code of Conduct.

  - id: about_you
    title: "About You"
    fields:
      - id: first_name
        type: text
        label: "What is your first name(s)?"
        required: true
      # ... more personal info fields

  - id: community_demographics
    title: "Help Us Understand the nf-core Community"
    fields:
      - id: age_group
        type: static_select
        label: "Which age group do you belong to?"
        options: [...]

  - id: attendance_mode
    title: "How Are You Joining?"
    fields:
      - id: attend_local_site
        type: static_select
        label: "Will you attend a hackathon local site?"
        options:
          - { label: "Yes", value: "yes" }
          - { label: "No — joining online", value: "no" }

  - id: local_site_selection
    title: "Local Site"
    condition:
      field: attend_local_site
      equals: "yes"
    fields:
      - id: local_site
        type: static_select
        label: "Which local site will you be attending?"
        options_from: sites  # dynamically populated from DynamoDB

  - id: online_details
    title: "Online Attendance"
    condition:
      field: attend_local_site
      equals: "no"
    fields:
      - id: timezone
        type: static_select
        label: "Which time zones best align with when you'll be online?"
        options: [...]

  - id: additional
    title: "Anything Else"
    fields:
      - id: code_of_conduct
        type: checkboxes
        label: "Code of Conduct"
        required: true
        options:
          - label: "I have read and agree to the nf-core Code of Conduct"
            value: accepted
```

### Required metadata fields

| Field | Description |
|-------|-------------|
| `hackathon` | Unique identifier (e.g. `2026-march`). Must match the filename: `forms/<id>.yaml` |
| `title` | Display title shown in modals and listings |
| `status` | One of `draft`, `open`, `closed`, `archived` |
| `channel` | Slack channel URL (`https://nfcore.slack.com/archives/C...`) or raw channel ID (`C...`). To get the URL: right-click the channel in Slack > "Copy" > "Copy link" |
| `url` | Event page URL (e.g. `https://nf-co.re/events/2026/hackathon-march-2026`) |
| `date_start` | Start date in `YYYY-MM-DD` format |
| `date_end` | End date in `YYYY-MM-DD` format |
| `steps` | List of form steps (see below) |

### Supported field types

These map directly to Slack Block Kit elements:

- `text` → plain_text_input
- `email` → plain_text_input (validated)
- `static_select` → static_select
- `multi_static_select` → multi_static_select
- `checkboxes` → checkboxes
- `radio_buttons` → radio_buttons

Steps can also have `type: statement` with a `text:` field for informational screens (no input fields).

Fields support `multiline: true` for multi-line text inputs.

### Dynamic options

- `options_from: sites` — populates from DynamoDB (sites registered for this hackathon)
- `options_from: countries` — populates from a built-in countries list

### Form → Modal mapping

Each `step` becomes a Slack modal view. The bot uses `views.push` to advance through steps and `views.update` to go back. Conditional steps are skipped if their condition isn't met.

## Registration Flow

```
1. User: /nf-core-bot hackathon register

2. Bot checks: is there exactly one hackathon YAML with status=open?
   ├─ None → ephemeral: "No hackathon is currently open for registration"
   ├─ Multiple → ephemeral: "Multiple hackathons open — this shouldn't happen, ping @core-team"
   └─ One → continue

3. Bot checks: does a registration already exist for this user + hackathon?
   ├─ Active → ephemeral: "You're already registered! Use `/nf-core-bot hackathon edit` to update"
   ├─ Cancelled → allow re-registration
   └─ None → continue

4. Bot loads form YAML for this hackathon
5. Bot opens first modal view (welcome / CoC statement)
6. User advances through steps:
   - Personal info (partially auto-filled from Slack profile)
   - Demographics
   - Hackathon experience
   - In-person vs online choice
   - Site selection (conditional on in-person) or timezone (conditional on online)
   - Additional info + CoC acceptance
7. Bot evaluates conditions at each step, skipping inapplicable steps
8. On final submit:
   - Reads email, Slack display name, GitHub username from Slack profile API
   - Writes registration to DynamoDB (form data + profile data)
   - Joins user to hackathon Slack channel
   - Sends ephemeral confirmation
```

### Admin Workflow

Hackathon lifecycle is managed entirely through YAML files — no slash commands needed for creation or status changes.

1. **Create the YAML file** — copy an existing form in `forms/` or start from the JSON schema. Set `status: draft`.
2. **Commit and push** — the bot auto-deploys and picks up the new file.
3. **Preview the form** — `/nf-core-bot hackathon admin preview 2026-march` (opens the modal in preview mode, no data saved)
4. **Add sites** — `/nf-core-bot hackathon admin add-site 2026-march barcelona Barcelona | Barcelona | Spain`
5. **Add organisers** — `/nf-core-bot hackathon admin add-organiser 2026-march barcelona @jose`
6. **Open registrations** — change `status: open` in the YAML, commit, push
7. **Monitor** — `/nf-core-bot hackathon attendees`
8. **Close registrations** — change `status: closed` in the YAML, commit, push
9. **Archive** — change `status: archived` to hide from `hackathon list`

## Project Structure

```sh
nf-core-bot/
├── README.md
├── CLAUDE.md                    # Instructions for Claude Code sessions
├── Dockerfile
├── docker-compose.yml           # Local DynamoDB for development
├── pyproject.toml
├── docs/
│   ├── slack-app-setup.md       # Creating the Slack app
│   ├── commands.md              # Full command reference
│   └── deployment.md            # AWS ECS Fargate deployment
├── forms/
│   └── 2026-march.yaml          # Form definitions (one per hackathon)
├── schemas/
│   └── hackathon-form.schema.json # JSON Schema for YAML validation + IntelliSense
├── src/
│   └── nf_core_bot/
│       ├── __init__.py
│       ├── app.py               # Bolt app entrypoint, slash command + modal callback registration
│       ├── config.py            # Environment variables, constants
│       ├── commands/
│       │   ├── __init__.py
│       │   ├── router.py        # Parse subcommands, dispatch to handlers
│       │   ├── help.py          # Permission-aware help text
│       │   ├── hackathon/
│       │   │   ├── __init__.py
│       │   │   ├── admin.py     # Admin command handlers (list, preview, site/organiser management)
│       │   │   ├── attendees.py # Attendee listing (permission-scoped)
│       │   │   ├── list_cmd.py  # User-facing hackathon list with registration status
│       │   │   └── register.py  # Register, edit, cancel handlers
│       │   ├── github/
│       │   │   ├── __init__.py
│       │   │   ├── add_member.py          # Slash command: invite user to nf-core org
│       │   │   └── add_member_shortcut.py # Message shortcut: invite message author
│       │   └── community/       # Future: audit commands
│       │       └── __init__.py
│       ├── forms/
│       │   ├── __init__.py
│       │   ├── loader.py        # YAML form parser, metadata functions, validation
│       │   ├── builder.py       # Block Kit modal view generator
│       │   └── handler.py       # Modal submission handler, preview mode, channel join
│       ├── checks/
│       │   ├── __init__.py
│       │   ├── github.py        # GitHub API: org membership, invitations, team management
│       │   └── slack_profile.py # Slack profile GitHub field discovery
│       ├── db/
│       │   ├── __init__.py
│       │   ├── client.py        # DynamoDB singleton client
│       │   ├── registrations.py # Registration CRUD with GSI1 support
│       │   └── sites.py         # Site and organiser CRUD
│       └── permissions/
│           ├── __init__.py
│           └── checks.py        # Core-team cache + organiser checks
└── tests/
    ├── conftest.py
    ├── test_add_member.py
    ├── test_add_member_shortcut.py
    ├── test_admin.py
    ├── test_attendees.py
    ├── test_db_registrations.py
    ├── test_db_sites.py
    ├── test_form_builder.py
    ├── test_form_handler.py
    ├── test_form_loader.py
    ├── test_github_checks.py
    ├── test_list_cmd.py
    ├── test_permissions.py
    ├── test_register.py
    ├── test_router.py
    └── test_slack_profile.py
```

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your Slack app tokens and GitHub token

# Start local DynamoDB (required for hackathon features)
docker compose up -d dynamodb-local

# Run the bot
python -m nf_core_bot

# Run tests
pytest

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/
```

The bot uses **Socket Mode** — no public URL or tunnel needed.

See also:

- [Slack App Setup](docs/slack-app-setup.md) — creating and configuring the Slack app
- [Command Reference](docs/commands.md) — all available commands
- [Deployment](docs/deployment.md) — deploying to AWS ECS Fargate
