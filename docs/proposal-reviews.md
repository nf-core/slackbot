# Automated pipeline-proposal reviews

When someone opens a `new-pipeline` proposal in
[`nf-core/proposals`](https://github.com/nf-core/proposals/issues), the
GitHub→Slack integration posts an announcement in **#new-pipelines**. The bot
watches for that post and automatically runs a structured review of the proposal
using Claude (on AWS Bedrock) driving the `nfcore-proposal-review` skill, then
replies in the thread tagging `@core-team`.

## How it works

```
GitHub issue (new-pipeline)
        │  GitHub→Slack integration
        ▼
#new-pipelines post ──► message listener ──► claim (DynamoDB dedup)
        │                                          │
        │                              fetch issue + all comments (GitHub API)
        │                                          │
        │                          Claude on Bedrock + read-only `run_command` tool
        │                          (runs the bundled skill scripts: gh / nf-core / jq)
        ▼                                          │
threaded reply tagging @core-team ◄────────── rendered review (Slack mrkdwn)
```

The Claude review runs the skill's research itself: it calls a single read-only
tool that can run the **bundled scripts** (`fetch_proposal.sh`,
`check_tools.sh`, `list_pipelines.sh`) plus `gh`, `nf-core` and `jq`. Write
operations and any other binaries are blocked by an allowlist (see
`src/nf_core_bot/proposals/tools.py`).

## Triggers

| Trigger                                                                   | Where the review is posted                                                                                                |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Automatic** — the GitHub→Slack post lands in #new-pipelines             | threaded reply under that post, tagging `@core-team`                                                                      |
| **Message shortcut** — right-click a message → _Review pipeline proposal_ | threaded reply under that message, tagging `@core-team`                                                                   |
| **Slash command** — `/nf-core proposals review <N> [preview]`             | in the conversation where you ran it (channel or DM); never cross-posted to #new-pipelines, and does not tag `@core-team` |

The slash command is restricted to `@core-team` and `@maintainers-team`. Run it
in a **DM** (or add `preview`) to get a private result you can dogfood before
rollout — these runs don't write the dedup record, so the automatic trigger
still fires later.

## Configuration (env vars)

| Var                            | Default                        | Notes                                                                            |
| ------------------------------ | ------------------------------ | -------------------------------------------------------------------------------- |
| `PROPOSALS_CHANNEL`            | `new-pipelines`                | Channel the listener watches                                                     |
| `PROPOSALS_REVIEW_ENABLED`     | `true`                         | Set `false` to disable the auto-trigger                                          |
| `BEDROCK_MODEL_ID`             | `eu.anthropic.claude-opus-4-8` | Bedrock inference-profile ID (note the `eu.` prefix in eu-west-1)                |
| `BEDROCK_REGION`               | —                              | Defaults to `AWS_REGION`                                                         |
| `BEDROCK_THINKING`             | `adaptive`                     | `adaptive` or `off`                                                              |
| `BEDROCK_MAX_TOKENS`           | `12000`                        | Max tokens per model turn                                                        |
| `MAINTAINERS_USERGROUP_HANDLE` | `maintainers-team`             | Slack user-group handle                                                          |
| `PROPOSALS_GITHUB_TOKEN`       | —                              | Optional read-only token for the `gh`/scripts tool; falls back to `GITHUB_TOKEN` |

## One-time setup

These are the parts that aren't handled by the deploy pipeline.

### Slack app (manifest / admin — manual)

1. **Event subscription**: add the `message.channels` bot event.
2. **Scopes**: add `channels:history` (read messages in public channels). The
   bot already has `chat:write`, `usergroups:read`, `conversations.*` from
   existing features.
3. **Interactivity → Shortcuts**: add a _message_ shortcut:
   - Name: `Review pipeline proposal`
   - Callback ID: `review_pipeline_proposal`
4. **Invite the bot to #new-pipelines** (`/invite @nf-core-bot`) — it only
   receives messages from channels it is a member of.

### AWS (handled in CDK / already enabled)

- Bedrock model access for Claude is already enabled in `eu-west-1`
  (`eu.anthropic.claude-opus-4-8` is active).
- The ECS task role is granted `bedrock:InvokeModel*` for Claude inference
  profiles + foundation models in `infra/stacks/bot_stack.py`.
- `gh`, `jq` and the `nf-core` CLI are installed in the container image
  (`Dockerfile`).

## Tweaking the review

- **The skill** lives at
  `src/nf_core_bot/proposals/skills/nfcore-proposal-review/` (SKILL.md +
  scripts) — edit it to change the review methodology.
- **The Slack message wrapper** is
  `src/nf_core_bot/proposals/templates/review.md`.
