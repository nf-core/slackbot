# Slack App Setup

This guide covers creating and configuring the Slack app needed to run the
nf-core bot.

## Create the App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New
   App** > **From scratch**
2. Name it (e.g. `nf-core-bot`) and select your workspace
3. Click **Create App**

## Enable Socket Mode

Socket Mode lets the bot receive events over a WebSocket instead of requiring a
public URL.

1. Go to **Settings** > **Socket Mode** (left sidebar)
2. Toggle **Enable Socket Mode** on
3. When prompted, create an **App-Level Token** with the `connections:write`
   scope
4. Name it (e.g. `socket-token`) and click **Generate**
5. Copy the token — this is your `SLACK_APP_TOKEN` (starts with `xapp-`)

## Add Bot Scopes

1. Go to **Features** > **OAuth & Permissions** (left sidebar)
2. Scroll to **Scopes** > **Bot Token Scopes** and add:

| Scope                | Purpose                                                                       |
| -------------------- | ----------------------------------------------------------------------------- |
| `commands`           | Register and receive slash commands                                           |
| `chat:write`         | Post messages and thread replies                                              |
| `users:read`         | Look up user info                                                             |
| `users:read.email`   | Read the user's email for Seqera workspace access                             |
| `users.profile:read` | Read GitHub username from Slack profile custom fields                         |
| `usergroups:read`    | Check `@core-team` membership for permission gating                           |
| `im:write`           | Open DMs to send confirmations, reminders, and registration messages          |
| `files:write`        | Upload CSV exports (site organiser downloads)                                 |
| `groups:read`        | Resolve the on-call `#core` private channel by name for announcements + topic |
| `groups:write.topic` | Set the `#core` channel topic to reflect the current on-call assignee         |
| `channels:history`   | Read #new-pipelines messages to auto-trigger pipeline-proposal reviews        |

After changing scopes you must **reinstall the app to the workspace** for the
new scopes to take effect (see [Install the App](#install-the-app) below). The
bot token (`xoxb-…`) does not rotate on reinstall, so no environment-variable
change is needed.

### Optional: user token for profile write-back

To have the bot populate a member's GitHub handle into their Slack profile after
an org invite, the app also needs a **user token** (`xoxp-…`) — a bot token
cannot edit another member's profile. This also requires the dedicated
`GitHub (auto)` profile field described in
[GitHub Profile Fields](#github-profile-fields) below.

1. On the same **OAuth & Permissions** page, scroll to **Scopes** > **User Token
   Scopes** (the section _below_ Bot Token Scopes) and add:

   | Scope                 | Purpose                                               |
   | --------------------- | ----------------------------------------------------- |
   | `users.profile:write` | Write members' GitHub handles into the `(auto)` field |

2. **Reinstall the app as a Workspace Admin or Owner.** The user token inherits
   the installing person's role, and Slack only lets an Admin/Owner-generated
   token edit other members' profiles (and only members ranked _below_ the
   installer — writes targeting fellow admins/owners will fail, which the bot
   tolerates gracefully). The workspace must be on a **paid plan**.

3. After authorising, the **User OAuth Token** (`xoxp-…`) appears at the top of
   the OAuth & Permissions page, above the bot token. Set it as
   `SLACK_ADMIN_USER_TOKEN`.

This token is optional — leave `SLACK_ADMIN_USER_TOKEN` unset and the write-back
silently no-ops; everything else works unchanged.

If `#core` is a public channel in your workspace, swap `groups:read` →
`channels:read` and `groups:write.topic` → `channels:manage` (or the granular
`channels:write.topic`).

## Register the Slash Command

1. Go to **Features** > **Slash Commands** (left sidebar)
2. Click **Create New Command**
3. Fill in:
   - **Command:** `/nf-core`
   - **Request URL:** `https://example.com/slack/events` (Socket Mode ignores
     this, but Slack requires a value)
   - **Short Description:** `nf-core community bot`
   - **Usage Hint:** `[help | github add | hackathon register]`
   - **Escape channels, users, and links sent to your app:** check this box
4. Click **Save**

## Enable Event Subscriptions

The bot listens for messages in #new-pipelines to auto-trigger proposal reviews.

1. Go to **Features** > **Event Subscriptions** (left sidebar)
2. Toggle **Enable Events** on (Socket Mode handles the request URL)
3. Under **Subscribe to bot events**, add `message.channels`
4. Save, then **reinstall the app** for the change to take effect
5. **Invite the bot to #new-pipelines** (`/invite @nf-core-bot`) — it only
   receives messages from channels it is a member of

## Add the Message Shortcuts

Message shortcuts let members right-click a message to act on it. These work
everywhere, including threads (unlike slash commands).

1. Go to **Features** > **Interactivity & Shortcuts** (left sidebar)
2. Ensure **Interactivity** is toggled on (Socket Mode handles the request URL)
3. Under **Shortcuts**, click **Create New Shortcut** and select **On messages**

Create two shortcuts:

| Name                       | Callback ID                | Purpose                                                             |
| -------------------------- | -------------------------- | ------------------------------------------------------------------- |
| `Add to GitHub org`        | `add_to_github_org`        | Invite this message's author to the nf-core GitHub org              |
| `Review pipeline proposal` | `review_pipeline_proposal` | Review the proposal linked in this message (posts a threaded reply) |

## Install the App

1. Go to **Settings** > **Install App** (left sidebar)
2. Click **Install to Workspace** and authorize
3. Copy the **Bot User OAuth Token** — this is your `SLACK_BOT_TOKEN` (starts
   with `xoxb-`)

## Get the Signing Secret

1. Go to **Settings** > **Basic Information** (left sidebar)
2. Under **App Credentials**, find the **Signing Secret**
3. Copy it — this is your `SLACK_SIGNING_SECRET`

## Summary of Tokens

After setup you should have three credentials:

| Variable               | Starts with  | Where                                      |
| ---------------------- | ------------ | ------------------------------------------ |
| `SLACK_BOT_TOKEN`      | `xoxb-`      | OAuth & Permissions > Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | (hex string) | Basic Information > App Credentials        |
| `SLACK_APP_TOKEN`      | `xapp-`      | Basic Information > App-Level Tokens       |

Plus one optional credential for GitHub profile write-back (see
[Optional: user token for profile write-back](#optional-user-token-for-profile-write-back)):

| Variable                 | Starts with | Where                                  |
| ------------------------ | ----------- | -------------------------------------- |
| `SLACK_ADMIN_USER_TOKEN` | `xoxp-`     | OAuth & Permissions > User OAuth Token |

Put these in your `.env` file (see `.env.example` in the repo root) or in SSM
Parameter Store for production (see [Deployment](deployment.md)).

## GitHub Profile Fields

The bot uses **two** custom profile fields, both discovered automatically from
`team.profile.get` by their labels:

| Field         | Label contains       | Data source      | Used for                                                        |
| ------------- | -------------------- | ---------------- | --------------------------------------------------------------- |
| Member GitHub | `github` (no "auto") | Members can edit | The bot **reads** this to look up a member's handle             |
| Auto GitHub   | `github` + `auto`    | **API**          | The bot **writes** invited handles here, as a link, for display |

If your workspace doesn't have these:

1. Go to your Slack workspace **Settings & Administration** > **Configure
   profiles** (or **Profile** on non-Enterprise plans).
2. Add a text/link field labelled e.g. **"GitHub"** for members to self-fill.
3. Add a **link** field labelled **"GitHub (auto)"** and set its **Data source**
   to **API**. This is mandatory for the write-back: with any other data source,
   `users.profile.set` returns `ok` but **silently discards the write**. Setting
   the data source to API also makes the field read-only for members (the bot
   owns it).

The write-back stores the GitHub URL as the field value and `@handle` as the
display text, and only writes when the auto field is empty (idempotent).
