# Local Development

This guide walks you through running the nf-core Slack bot on your local machine for **testing and development**. For production use, see [Deployment](deployment.md).

## Prerequisites

- **Python 3.12+**
- **Docker** (only needed if you want to test hackathon commands — not required for GitHub commands)
- A configured **Slack app** in your workspace (see [Slack App Setup](slack-app-setup.md))
- A **GitHub fine-grained Personal Access Token** with `admin:org` scope on the nf-core organisation

## Quick Start

### 1. Install dependencies

```bash
pip install -e ".[dev]"
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

| Variable | Required | Where to get it |
|----------|----------|-----------------|
| `SLACK_BOT_TOKEN` | Yes | Slack app > OAuth & Permissions > Bot User OAuth Token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Yes | Slack app > Basic Information > Signing Secret |
| `SLACK_APP_TOKEN` | Yes | Slack app > Basic Information > App-Level Tokens (`xapp-...`) |
| `GITHUB_TOKEN` | Yes | GitHub > Settings > Developer settings > Fine-grained PATs |
| `GITHUB_ORG` | No | Defaults to `nf-core` |
| `DYNAMODB_TABLE` | No | Defaults to `nf-core-bot` |
| `DYNAMODB_ENDPOINT` | No | Defaults to `http://localhost:8000` for local DynamoDB |
| `AWS_REGION` | No | Defaults to `eu-west-1` |
| `CORE_TEAM_USERGROUP_HANDLE` | No | Defaults to `core-team` |

### 3. Run the bot

```bash
python -m nf_core_bot
```

The bot connects via **Socket Mode**, so no ngrok or tunnel is needed.
It will log a warning if DynamoDB is unavailable, but GitHub commands work without it.

### 4. Test in Slack

Try these commands in your Slack workspace:

```
/nf-core-bot help
/nf-core-bot github help
/nf-core-bot github add-member <github-username>
```

## Optional: Local DynamoDB

Only needed if you want to test hackathon registration commands (not yet implemented).

```bash
docker compose up -d
```

This starts DynamoDB Local on port 8000. The bot auto-creates its table on startup.

## Running Tests

```bash
pytest
```

Tests use mocked Slack clients and httpx responses — no live services needed.

## Linting and Type Checking

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

## Permissions

The `github add-member` command requires the caller to be a member of the `@core-team` user group in Slack. If you're testing in a workspace where that group doesn't exist or you're not a member, the command will return a "restricted to core-team" error.

## Next Steps

When you're ready to run the bot permanently, see [Deployment](deployment.md) for deploying to AWS ECS Fargate.
