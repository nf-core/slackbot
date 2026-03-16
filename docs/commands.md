# Command Reference

All commands use the `/nf-core-bot` slash command with subcommand routing. Slack only allows one slash command per app, so everything is parsed as subcommands.

All responses are **ephemeral** (only visible to the caller) unless noted otherwise.

## General

### `help`

```
/nf-core-bot help
```

Show available commands, filtered by your permissions. Admin commands are only shown to `@core-team` members.

---

## Hackathon Commands

### `hackathon help`

```
/nf-core-bot hackathon help
```

Show hackathon-specific commands available to you.

### `hackathon list`

```
/nf-core-bot hackathon list
```

List all non-archived hackathons with their status, dates, and event URL. If you have an active registration for any listed hackathon, your registration status is shown.

**Permissions:** All users.

### `hackathon register`

```
/nf-core-bot hackathon register
```

Register for the currently open hackathon. Opens a multi-step modal form.

The bot will:
1. Find the active (open) hackathon — errors if none or multiple are open
2. Check if you're already registered — directs you to `hackathon edit` if so
3. Load the form YAML and open a multi-step modal
4. Auto-fill email, Slack display name, and GitHub username from your Slack profile
5. On submit: save registration to DynamoDB and join you to the hackathon Slack channel

**Permissions:** All users.

### `hackathon edit`

```
/nf-core-bot hackathon edit
```

Edit your existing registration. Re-opens the modal form pre-filled with your current answers.

**Permissions:** All users (must have an active registration).

### `hackathon cancel`

```
/nf-core-bot hackathon cancel
```

Cancel your registration for the active hackathon. Sets your registration status to `cancelled`.

**Permissions:** All users (must have an active registration).

### `hackathon attendees`

```
/nf-core-bot hackathon attendees [hackathon-id]
```

List registered attendees. If `hackathon-id` is omitted, defaults to the active hackathon.

**Permissions:**
- **Site organisers** — see attendees for their site(s) only
- **`@core-team`** — see all attendees across all sites

**Examples:**

```
/nf-core-bot hackathon attendees
/nf-core-bot hackathon attendees 2026-march
```

---

## Hackathon Admin Commands

All admin commands require `@core-team` Slack user group membership.

> **Note:** Hackathon lifecycle (create, open, close, archive) is managed by editing YAML files in `forms/`, not via slash commands. See [Managing Hackathon Lifecycle](#managing-hackathon-lifecycle) below.

### `hackathon admin list`

```
/nf-core-bot hackathon admin list
```

List all hackathons including draft and archived ones, with their current status, dates, and event URL. This shows hackathons from all YAML files in `forms/`.

### `hackathon admin preview`

```
/nf-core-bot hackathon admin preview <hackathon-id>
```

Open the registration form for a hackathon in preview mode. The modal opens and can be stepped through, but no data is saved to DynamoDB. Useful for testing form YAML changes before opening registration.

**Example:**

```
/nf-core-bot hackathon admin preview 2026-march
```

### `hackathon admin add-site`

```
/nf-core-bot hackathon admin add-site <hackathon-id> <site-id> <name> | <city> | <country>
```

Add a local site to a hackathon. The description uses pipe-separated fields for name, city, and country.

**Example:**

```
/nf-core-bot hackathon admin add-site 2026-march barcelona Barcelona | Barcelona | Spain
```

### `hackathon admin remove-site`

```
/nf-core-bot hackathon admin remove-site <hackathon-id> <site-id>
```

Remove a site from a hackathon.

**Example:**

```
/nf-core-bot hackathon admin remove-site 2026-march barcelona
```

### `hackathon admin list-sites`

```
/nf-core-bot hackathon admin list-sites <hackathon-id>
```

List all sites for a hackathon with their organisers.

**Example:**

```
/nf-core-bot hackathon admin list-sites 2026-march
```

### `hackathon admin add-organiser`

```
/nf-core-bot hackathon admin add-organiser <hackathon-id> <site-id> @user
```

Add a site organiser. Organisers can view attendee lists scoped to their site(s).

**Example:**

```
/nf-core-bot hackathon admin add-organiser 2026-march barcelona @jose
```

### `hackathon admin remove-organiser`

```
/nf-core-bot hackathon admin remove-organiser <hackathon-id> <site-id> @user
```

Remove a site organiser.

**Example:**

```
/nf-core-bot hackathon admin remove-organiser 2026-march barcelona @jose
```

---

## Managing Hackathon Lifecycle

Hackathon creation and status changes are managed through YAML files in the `forms/` directory — not via slash commands. Each YAML file contains both hackathon metadata and the registration form definition.

### YAML form format

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
    title: "Welcome"
    type: statement
    text: |
      Welcome to the hackathon registration!
  # ... more steps
```

The `# yaml-language-server` comment enables VS Code IntelliSense via the [Red Hat YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml). The JSON schema at `schemas/hackathon-form.schema.json` validates required fields and allowed values.

The `channel` field accepts either a Slack channel URL (`https://nfcore.slack.com/archives/C...`) or a raw channel ID (`C...`). To get the URL: right-click the channel in Slack > "Copy" > "Copy link".

### Admin workflow

1. **Create the YAML file** — copy an existing form in `forms/` or start fresh using the JSON schema for guidance. Set `status: draft`.
2. **Commit and push** — the bot auto-deploys and picks up the new hackathon.
3. **Preview the form** — `/nf-core-bot hackathon admin preview 2026-march` (opens the modal in preview mode, no data saved).
4. **Add sites** — `/nf-core-bot hackathon admin add-site 2026-march barcelona Barcelona | Barcelona | Spain`
5. **Add organisers** — `/nf-core-bot hackathon admin add-organiser 2026-march barcelona @jose`
6. **Open registrations** — change `status: open` in the YAML, commit, push.
7. **Monitor** — `/nf-core-bot hackathon attendees`
8. **Close registrations** — change `status: closed` in the YAML, commit, push.
9. **Archive** — change `status: archived` to hide from user-facing `hackathon list`.

### Status values

| Status | Effect |
|--------|--------|
| `draft` | Visible only via `admin list` and `admin preview`. Users cannot register. |
| `open` | Users can register. Shown in `hackathon list`. Only one hackathon should be open at a time. |
| `closed` | Registrations are closed. Still visible in `hackathon list`. |
| `archived` | Hidden from `hackathon list`. Only visible via `admin list`. |

---

## GitHub Commands

These commands manage nf-core GitHub organisation membership. All require `@core-team` membership in Slack.

### `github help`

```
/nf-core-bot github help
```

Show GitHub command help.

### `github add-member`

```
/nf-core-bot github add-member <@slack-user|github-username>
```

Invite a user to the nf-core GitHub organisation and add them to the **contributors** team.

**Arguments:**
- `@slack-user` — reads the GitHub username from their Slack profile
- `github-username` — invites the GitHub user directly

**Permissions:** `@core-team` only.

**Examples:**

```
/nf-core-bot github add-member @alice
/nf-core-bot github add-member octocat
```

### Message Shortcut: Add to GitHub org

Right-click any message, select **More actions** > **Add to GitHub org** to invite the message author. This reads their Slack profile for a GitHub username, then sends the org invitation.

This works in threads (unlike slash commands, which Slack does not support in threads).

**Permissions:** `@core-team` only.

### How `add-member` Works

1. **Permission check** — verifies you're in the `@core-team` Slack user group
2. **Target resolution** — determines who to invite:
   - **Slack mention** (`@user`): reads their Slack profile for a GitHub username
   - **Bare username** (`octocat`): validates the format directly
   - **Message shortcut**: reads the message author's Slack profile for a GitHub username
3. **GitHub API calls**:
   - Sends an org membership invitation via `PUT /orgs/nf-core/memberships/{username}`
   - Adds the user to the **contributors** team via `PUT /orgs/nf-core/teams/contributors/memberships/{username}`
4. **Thread reply** — posts a **visible** reply with the result (not ephemeral, so the original requester can see it too)

### Error Handling

- **Invalid username**: if a bare username doesn't match GitHub's format (alphanumeric + hyphens, 1-39 chars), the bot rejects it immediately with an ephemeral message
- **Missing GitHub profile**: if a Slack user doesn't have a GitHub username in their profile, the bot posts a helpful message explaining how to add it
- **API failures**: network errors and GitHub API errors are caught and reported in the thread with actionable messages
- **Partial failures**: if the org invite succeeds but the team addition fails, the bot reports exactly what worked and what didn't

---

## Permission Model

| Level | Who | Access |
|-------|-----|--------|
| **User** | Everyone | `help`, `hackathon list`, `hackathon register/edit/cancel` |
| **Site organiser** | Per-hackathon, per-site (stored in DynamoDB) | `hackathon attendees` (scoped to their sites) |
| **Admin** | `@core-team` Slack user group members | All commands including `hackathon admin *`, `github *`, full `hackathon attendees` |

Admin membership is checked via `usergroups.users.list` and cached for 5 minutes.
