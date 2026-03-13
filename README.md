# nf-core-bot

A Slack bot for the nf-core community, starting with hackathon registration management.

> [!INFO]
> This is a work-in-process repository. Nothing functional yet.

Built with [Slack Bolt for Python](https://slack.dev/bolt-python/), hosted on AWS (ECS Fargate + DynamoDB).

## Features

### Hackathon Registration

- **In-Slack registration** via slash commands and modal forms
- **GitHub validation** — checks Slack profile for GitHub username, verifies nf-core org membership
- **Multi-step forms** with conditional logic (online vs in-person, site selection)
- **Form definitions in YAML** — one file per hackathon, version controlled
- **Self-service** — users can edit or cancel their own registrations
- **Hackathon lifecycle** — create, open, close, archive events
- **Site management** — add/remove local sites per hackathon
- **Organiser access** — site organisers can pull attendee lists for their site
- **Permission model** — admin commands restricted to `@core-team` Slack user group

<!-- Community health features (not yet implemented):
### Future Work
- /nf-core-bot community audit — scan all Slack users for GitHub profile field
- Check nf-core org membership across the community
- Check public org membership visibility
- Scheduled reports / nudge DMs for missing info
-->

## Architecture

```
Slack ←→ ECS Fargate (Bolt app, Python)
              ↕
          DynamoDB (single-table design)
              ↕
          GitHub API (org membership checks)
              ↕
          EventBridge (scheduled tasks — nightly organiser reports, reminders)
```

### AWS Services

- **ECS Fargate** — single task, always-on container running the Bolt app in HTTP mode
- **DynamoDB** — single table, on-demand capacity (free tier is plenty)
- **ECR** — container registry for the bot image
- **ALB** — application load balancer for Slack's HTTP requests
- **EventBridge** — scheduled triggers for nightly reports (future)
- **S3** — optional, for form YAML hot-reloading without redeploy
- **CloudWatch** — logs and basic monitoring

### DynamoDB Single-Table Design

Partition key: `PK`, Sort key: `SK`

| Entity       | PK               | SK                                   | Key attributes                                                                                   |
| ------------ | ---------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Hackathon    | `HACKATHON#<id>` | `META`                               | id, title, status (draft/open/closed/archived), channel_id, form_id, created_by, created_at      |
| Site         | `HACKATHON#<id>` | `SITE#<site-id>`                     | site_id, description, created_by                                                                 |
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

# User commands
/nf-core-bot hackathon register
/nf-core-bot hackathon edit
/nf-core-bot hackathon cancel

# Organiser commands (site-scoped)
/nf-core-bot hackathon attendees [site]

# Admin commands (@core-team only)
/nf-core-bot hackathon admin create <id> <title>
/nf-core-bot hackathon admin open <id>
/nf-core-bot hackathon admin close <id>
/nf-core-bot hackathon admin archive <id>
/nf-core-bot hackathon admin list

/nf-core-bot hackathon admin add-site <hackathon-id> <site-id> <description>
/nf-core-bot hackathon admin remove-site <hackathon-id> <site-id>
/nf-core-bot hackathon admin list-sites [hackathon-id]

/nf-core-bot hackathon admin add-organiser <hackathon-id> <site-id> @user
/nf-core-bot hackathon admin remove-organiser <hackathon-id> <site-id> @user

# GitHub commands (@core-team only)
/nf-core-bot github help
/nf-core-bot github add-member                  # In a thread — invites the thread starter
/nf-core-bot github add-member @slack-user       # Invite a specific Slack user
/nf-core-bot github add-member <github-username> # Invite by GitHub username directly
```

**Notes:**

- Slack allows only one slash command per app — `/nf-core-bot` is the entry point, everything else is parsed as subcommands
- `hackathon register` targets the currently open hackathon (error if zero or multiple are open)
- All responses to commands are **ephemeral** (only visible to the caller) unless explicitly posting to a channel
- Exception: `github add-member` posts **visible thread replies** so the original requester can see the outcome
- `help` at each level only shows commands the caller has permission to use

## Form Configuration

Forms are defined in YAML, one per hackathon:

```yaml
# forms/2026-march.yaml
hackathon: 2026-march
steps:
  - id: basics
    title: "Basic Information"
    fields:
      - id: name
        type: text
        label: "Full name"
        required: true
      - id: email
        type: email
        label: "Email address"
        required: true
      - id: attendance
        type: static_select
        label: "How are you joining?"
        options:
          - label: "Online"
            value: online
          - label: "In person"
            value: in-person

  - id: in_person_details
    title: "In-Person Details"
    condition:
      field: attendance
      equals: in-person
    fields:
      - id: site
        type: static_select
        label: "Which site?"
        options_from: sites # dynamically populated from DynamoDB
      - id: dietary
        type: text
        label: "Dietary requirements"
        required: false
      - id: tshirt
        type: static_select
        label: "T-shirt size"
        options:
          - { label: "S", value: s }
          - { label: "M", value: m }
          - { label: "L", value: l }
          - { label: "XL", value: xl }
          - { label: "XXL", value: xxl }

  - id: experience
    title: "About You"
    fields:
      - id: first_hackathon
        type: static_select
        label: "Is this your first nf-core hackathon?"
        options:
          - { label: "Yes", value: "yes" }
          - { label: "No", value: "no" }
      - id: topics
        type: multi_static_select
        label: "What topics interest you?"
        options:
          - { label: "Pipeline development", value: pipelines }
          - { label: "Modules & subworkflows", value: modules }
          - { label: "Documentation", value: docs }
          - { label: "Infrastructure & CI", value: infra }
          - { label: "Testing", value: testing }
```

### Supported field types

These map directly to Slack Block Kit elements:

- `text` → plain_text_input
- `email` → plain_text_input (validated)
- `static_select` → static_select
- `multi_static_select` → multi_static_select
- `checkboxes` → checkboxes
- `radio_buttons` → radio_buttons

### Dynamic options

`options_from: sites` tells the form builder to pull the option list from DynamoDB (sites registered for this hackathon).

### Form → Modal mapping

Each `step` becomes a Slack modal view. The bot uses `views.push` to advance through steps and `views.update` to go back. Conditional steps are skipped if their condition isn't met.

## Registration Flow

```
1. User: /nf-core-bot hackathon register

2. Bot checks Slack profile for GitHub username field
   ├─ Missing → ephemeral: "Please add your GitHub username to your Slack profile"
   └─ Present → continue

3. Bot checks GitHub API: is <username> a member of nf-core org?
   ├─ No → ephemeral: "You need to be a member of the nf-core GitHub org.
   │        Request to join: https://github.com/nf-core"
   └─ Yes → continue

4. Bot checks: is there exactly one hackathon with status=open?
   ├─ None → ephemeral: "No hackathon is currently open for registration"
   ├─ Multiple → ephemeral: "Multiple hackathons open — this shouldn't happen, ping @core-team"
   └─ One → continue

5. Bot checks: does a registration already exist for this user + hackathon?
   ├─ Active → ephemeral: "You're already registered! Use `/nf-core-bot hackathon edit` to update"
   ├─ Cancelled → allow re-registration
   └─ None → continue

6. Bot loads form YAML for this hackathon
7. Bot opens first modal view with step 1 fields
8. User fills in fields, clicks Next
9. Bot evaluates conditions, shows next applicable step (or submits if last)
10. On final submit:
    - Write registration to DynamoDB
    - Add user to hackathon Slack channel
    - Send confirmation DM
    - Post in hackathon channel: "👋 @user just registered!" (optional, configurable)
```

## Project Structure

```sh
nf-core-bot/
├── README.md
├── CLAUDE.md                    # Instructions for Claude Code sessions
├── Dockerfile
├── docker-compose.yml           # Local development
├── pyproject.toml
├── forms/
│   └── 2026-march.yaml          # Form definitions (one per hackathon)
├── infra/
│   ├── template.yaml            # CloudFormation / SAM template
│   └── taskdef.json             # ECS task definition
├── src/
│   └── nf_core_bot/
│       ├── __init__.py
│       ├── app.py               # Bolt app setup, slash command router
│       ├── config.py            # Environment variables, constants
│       ├── commands/
│       │   ├── __init__.py
│       │   ├── router.py        # Parse subcommands, dispatch to handlers
│       │   ├── help.py
│       │   ├── hackathon/
│       │   │   ├── __init__.py
│       │   │   ├── register.py  # register, edit, cancel
│       │   │   ├── attendees.py
│       │   │   └── admin.py     # create, open, close, archive, sites, organisers
│       │   ├── github/
│       │   │   ├── __init__.py
│       │   │   └── add_member.py # invite user to nf-core org + contributors team
│       │   └── community/       # Future: audit commands
│       │       └── __init__.py
│       ├── forms/
│       │   ├── __init__.py
│       │   ├── loader.py        # Load YAML, resolve dynamic options
│       │   ├── builder.py       # YAML → Slack Block Kit modal views
│       │   └── handler.py       # Modal submission / view_push callbacks
│       ├── checks/
│       │   ├── __init__.py
│       │   ├── github.py        # GitHub API: org membership check
│       │   └── slack_profile.py # Read custom profile field for GitHub username
│       ├── db/
│       │   ├── __init__.py
│       │   ├── client.py        # DynamoDB client, table setup
│       │   ├── hackathons.py    # CRUD for hackathon lifecycle
│       │   ├── registrations.py # CRUD for registrations
│       │   └── sites.py         # CRUD for sites + organisers
│       └── permissions/
│           ├── __init__.py
│           └── checks.py        # @core-team check, organiser check
└── tests/
    ├── conftest.py
    ├── test_router.py
    ├── test_forms.py
    ├── test_registrations.py
    └── test_permissions.py
```

## Development

### Prerequisites

- Python 3.12+
- Docker (for local DynamoDB)
- A Slack app configured with:
  - Slash command: `/nf-core-bot`
  - Bot token scopes: `commands`, `chat:write`, `users:read`, `users.profile:read`, `usergroups:read`, `channels:manage`, `groups:write`, `channels:history`, `groups:history`
  - Interactivity enabled (for modals)
  - Request URL pointed at your dev tunnel (ngrok or similar)

### Local Setup

```bash
# Clone and install
git clone <repo-url>
cd nf-core-bot
pip install -e ".[dev]"

# Start local DynamoDB
docker compose up -d dynamodb-local

# Set environment variables
cp .env.example .env
# Edit .env with your Slack app tokens and GitHub token

# Run the bot
python -m nf_core_bot.app
```

### Environment Variables

```sh
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APP_TOKEN=xapp-...  # Only if using socket mode for dev
GITHUB_TOKEN=ghp_...      # For org membership checks + invitations (admin:org)
DYNAMODB_TABLE=nf-core-bot
DYNAMODB_ENDPOINT=http://localhost:8000  # For local dev only
CORE_TEAM_USERGROUP_HANDLE=core-team
GITHUB_ORG=nf-core
AWS_REGION=eu-north-1
```

## Deployment

Build and push to ECR, deploy via ECS. CloudFormation template in `infra/` provisions:

- ECS cluster + Fargate service
- DynamoDB table with GSI
- ALB + target group
- IAM roles
- CloudWatch log group

The Slack app's request URL should point at the ALB endpoint.
