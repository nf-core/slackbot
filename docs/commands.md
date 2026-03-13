# Command Reference

All commands use the `/nf-core-bot` slash command with subcommand routing.

## General

| Command | Description |
|---------|-------------|
| `/nf-core-bot help` | Show available commands (filtered by your permissions) |

## GitHub Commands

These commands manage nf-core GitHub organisation membership. All require `@core-team` membership in Slack.

| Command / Action | Description |
|---------|-------------|
| `/nf-core-bot github help` | Show GitHub command help |
| `/nf-core-bot github add-member <username>` | Invite a GitHub user to the nf-core org |
| `/nf-core-bot github add-member @slack-user` | Invite a Slack user (reads their GitHub username from their Slack profile) |
| **Message shortcut:** *Add to GitHub org* | Right-click a message → *More actions* → *Add to GitHub org* to invite the message author |

### How `add-member` Works

1. **Permission check** — verifies you're in the `@core-team` Slack user group
2. **Target resolution** — determines who to invite:
   - **Slack mention** (`@user`): reads their Slack profile for a GitHub username
   - **Bare username** (`octocat`): validates the format directly
   - **Message shortcut**: reads the message author's Slack profile for a GitHub username
3. **GitHub API calls**:
   - Sends an org membership invitation via `PUT /orgs/nf-core/memberships/{username}`
   - Adds the user to the **contributors** team via `PUT /orgs/nf-core/teams/contributors/memberships/{username}`
4. **Thread reply** — posts a visible reply with the result (not ephemeral, so the original requester can see it too)

> **Note:** Slack does not support custom slash commands in threads. Use the message shortcut to invite someone based on a message they posted.

### Error Handling

- **Invalid username**: if a bare username doesn't match GitHub's format (alphanumeric + hyphens, 1-39 chars), the bot rejects it immediately with an ephemeral message
- **Missing GitHub profile**: if a Slack user doesn't have a GitHub username in their profile, the bot posts a helpful message explaining how to add it
- **API failures**: network errors and GitHub API errors are caught and reported in the thread with actionable messages
- **Partial failures**: if the org invite succeeds but the team addition fails, the bot reports exactly what worked and what didn't

## Hackathon Commands (Not Yet Implemented)

These commands are scaffolded but not yet functional:

| Command | Description | Requires |
|---------|-------------|----------|
| `/nf-core-bot hackathon register` | Register for the current hackathon | All users |
| `/nf-core-bot hackathon edit` | Edit your registration | All users |
| `/nf-core-bot hackathon cancel` | Cancel your registration | All users |
| `/nf-core-bot hackathon attendees` | List attendees | Organisers |
| `/nf-core-bot hackathon admin create <id>` | Create a new hackathon | Core team |
| `/nf-core-bot hackathon admin open <id>` | Open registration | Core team |
| `/nf-core-bot hackathon admin close <id>` | Close registration | Core team |
| `/nf-core-bot hackathon admin archive <id>` | Archive a hackathon | Core team |
| `/nf-core-bot hackathon admin list` | List all hackathons | Core team |
| `/nf-core-bot hackathon admin add-site <id> <name>` | Add a local site | Core team |
| `/nf-core-bot hackathon admin remove-site <id> <site>` | Remove a local site | Core team |
| `/nf-core-bot hackathon admin list-sites <id>` | List sites | Core team |
| `/nf-core-bot hackathon admin add-organiser <id> <site> @user` | Add a site organiser | Core team |
| `/nf-core-bot hackathon admin remove-organiser <id> <site> @user` | Remove a site organiser | Core team |
