# nf-core-bot

A Slack bot for the nf-core community — hackathon registration and GitHub
organisation tooling.

Built with [Slack Bolt for Python](https://slack.dev/bolt-python/), hosted on
AWS ECS Fargate + DynamoDB.

## Commands

Two slash commands:

```bash
/nf-core help                          # General help
/nf-core github add-member @user       # Invite to nf-core GitHub org
/nf-core github add-member <username>  # Invite by GitHub username

/hackathon help                        # Hackathon help
/hackathon list                        # List hackathons
/hackathon register                    # Register for the active hackathon
/hackathon edit                        # Edit your registration
/hackathon cancel                      # Cancel your registration
/hackathon sites                       # Sites, organisers, registration counts
/hackathon export                      # Export registrations as CSV (organiser+)
/hackathon admin list                  # All hackathons incl. draft/archived (admin)
/hackathon admin preview               # Preview the registration form (admin)
/hackathon admin add-site              # Add a site (admin, opens modal)
/hackathon admin edit-site             # Edit a site (admin, opens modal)
```

You can also right-click any message → **More actions** → **Add to GitHub org**
to invite the message author.

All responses are **ephemeral** (only visible to you), except
`github add-member` which posts visible thread replies.

See [docs/commands.md](docs/commands.md) for the full command reference.

## Hackathon Form Configuration

Each hackathon has a YAML file in `hackathons/` containing metadata and form
steps. A JSON schema at `schemas/hackathon-form.schema.json` provides validation
and VS Code IntelliSense via the
[Red Hat YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml).

See `hackathons/2026-march.yaml` for a full working example.

### Metadata fields

| Field        | Description                                                                |
| ------------ | -------------------------------------------------------------------------- |
| `hackathon`  | Unique ID (e.g. `2026-march`). Must match filename: `hackathons/<id>.yaml` |
| `title`      | Display title shown in modals and listings                                 |
| `status`     | `draft` / `open` / `closed` / `archived`                                   |
| `channel`    | Slack channel URL or ID. Users are auto-joined on registration             |
| `url`        | Event page URL                                                             |
| `date_start` | Start date (`YYYY-MM-DD`)                                                  |
| `date_end`   | End date (`YYYY-MM-DD`)                                                    |
| `steps`      | List of form steps                                                         |

### Field types

- `text` — plain text input (`multiline: true` for multi-line)
- `static_select` — dropdown with inline options
- `external_select` — dropdown with type-ahead search (used for large option
  sets like countries via `options_from: countries`)
- `checkboxes` — checkbox group
- `type: statement` on a step — informational screen (no input fields), uses
  `text:` for the message

### Dynamic options

- `options_from: sites` — populates from DynamoDB (sites for this hackathon)
- `options_from: countries` — type-ahead country search (requires
  `external_select`)

### Conditional steps

Steps can have a `condition` field to show/hide based on a previous answer:

```yaml
- id: local_site_selection
  title: "Local Site"
  condition:
    field: attend_local_site
    equals: "yes"
```

### Hackathon modes

The mode is determined by how you author the YAML — no special field needed:

| Mode                            | How to configure                                                                                                             |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Hybrid** (sites + online)     | Add an `attend_local_site` yes/no field with conditional steps for site selection and online details. See `2026-march.yaml`. |
| **In-person only** (multi-site) | Include a `local_site` field with `options_from: sites`, no attendance mode question.                                        |
| **Online only**                 | No `local_site` field, no site selection step.                                                                               |
| **Single-location in-person**   | Same as online only — no site selection. Describe the venue in the welcome text.                                             |

## Admin Workflow

Hackathon lifecycle is managed through YAML files and git — no slash commands
needed for creation or status changes.

1. **Create YAML** — copy `hackathons/2026-march.yaml`, set `status: draft`
2. **Push to `main`** — auto-deploys, bot picks up the new file
3. **Preview** — `/hackathon admin preview` opens the form in preview mode (no
   data saved)
4. **Add sites** — `/hackathon admin add-site` (modal form with organisers)
5. **Open** — change `status: open`, commit, push
6. **Monitor** — `/hackathon sites` for counts, `/hackathon export` for CSV
7. **Close** — change `status: closed`, commit, push
8. **Archive** — change `status: archived` to hide from `/hackathon list`

### Permissions

- **`@core-team`** Slack user group — full admin access to all commands
- **Site organisers** — can view attendees and export data for their site(s)

## Development

```bash
pip install -e ".[dev]"        # Install dependencies
docker compose up -d dynamodb-local  # Local DynamoDB
python -m nf_core_bot          # Run the bot (Socket Mode, no tunnel needed)
pytest                         # Run tests
ruff check src/ tests/         # Lint
mypy src/                      # Type check
```

See also: [Slack App Setup](docs/slack-app-setup.md) ·
[Command Reference](docs/commands.md) · [Deployment](docs/deployment.md)
