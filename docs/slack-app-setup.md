# Slack App Setup

This guide covers creating and configuring the Slack app needed to run the nf-core bot.

## Create the App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** > **From scratch**
2. Name it (e.g. `nf-core-bot`) and select your workspace
3. Click **Create App**

## Enable Socket Mode

Socket Mode lets the bot receive events over a WebSocket instead of requiring a public URL.

1. Go to **Settings** > **Socket Mode** (left sidebar)
2. Toggle **Enable Socket Mode** on
3. When prompted, create an **App-Level Token** with the `connections:write` scope
4. Name it (e.g. `socket-token`) and click **Generate**
5. Copy the token — this is your `SLACK_APP_TOKEN` (starts with `xapp-`)

## Add Bot Scopes

1. Go to **Features** > **OAuth & Permissions** (left sidebar)
2. Scroll to **Scopes** > **Bot Token Scopes** and add:

| Scope | Purpose |
|-------|---------|
| `commands` | Register and receive slash commands |
| `chat:write` | Post messages and thread replies |
| `users:read` | Look up user info |
| `users.profile:read` | Read GitHub username from Slack profile custom fields |
| `usergroups:read` | Check `@core-team` membership for permission gating |

## Register the Slash Command

1. Go to **Features** > **Slash Commands** (left sidebar)
2. Click **Create New Command**
3. Fill in:
   - **Command:** `/nf-core-bot`
   - **Request URL:** `https://example.com/slack/events` (Socket Mode ignores this, but Slack requires a value)
   - **Short Description:** `nf-core community bot`
   - **Usage Hint:** `[help | github add-member | hackathon register]`
   - **Escape channels, users, and links sent to your app:** check this box
4. Click **Save**

## Add the Message Shortcut

The "Add to GitHub org" message shortcut lets core-team members right-click any message and invite its author to the nf-core GitHub org. This works everywhere including threads (unlike slash commands).

1. Go to **Features** > **Interactivity & Shortcuts** (left sidebar)
2. Ensure **Interactivity** is toggled on (Socket Mode handles the request URL)
3. Under **Shortcuts**, click **Create New Shortcut**
4. Select **On messages** (message shortcut, not global)
5. Fill in:
   - **Name:** `Add to GitHub org`
   - **Short Description:** `Invite this message's author to the nf-core GitHub org`
   - **Callback ID:** `add_to_github_org`
6. Click **Create**

## Install the App

1. Go to **Settings** > **Install App** (left sidebar)
2. Click **Install to Workspace** and authorize
3. Copy the **Bot User OAuth Token** — this is your `SLACK_BOT_TOKEN` (starts with `xoxb-`)

## Get the Signing Secret

1. Go to **Settings** > **Basic Information** (left sidebar)
2. Under **App Credentials**, find the **Signing Secret**
3. Copy it — this is your `SLACK_SIGNING_SECRET`

## Summary of Tokens

After setup you should have three credentials:

| Variable | Starts with | Where |
|----------|-------------|-------|
| `SLACK_BOT_TOKEN` | `xoxb-` | OAuth & Permissions > Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | (hex string) | Basic Information > App Credentials |
| `SLACK_APP_TOKEN` | `xapp-` | Basic Information > App-Level Tokens |

Put these in your `.env` file as described in [Local Development](local-development.md).

## GitHub Profile Field

The bot reads GitHub usernames from a **custom profile field** in Slack. Most nf-core workspaces already have this configured. If your workspace doesn't:

1. Go to your Slack workspace **Settings & Administration** > **Profile**
2. Add a custom text field with a label containing the word "GitHub" (e.g. "GitHub Username")
3. Members can then fill in their GitHub username in their Slack profile

The bot discovers this field automatically by searching for a profile field with "github" in the label.
