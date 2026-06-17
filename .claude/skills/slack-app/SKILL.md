---
name: slack-app
description: >-
  How to build and modify Slack-app features in this repo (a Python async
  slack-bolt bot running in Socket Mode). Use this whenever you are touching
  anything Slack-facing — adding or editing slash commands, events, actions,
  shortcuts, modals/views, or option providers; formatting or posting messages
  (Block Kit, mrkdwn, bullets, mentions, threads, ephemeral vs public);
  resolving why a message won't post or render correctly; or changing the Slack
  app's scopes/events/manifest. Reach for it even when the user doesn't say
  "Slack" but is editing files under src/nf_core_bot/ that call `client.*`,
  `respond`, `ack`, `say`, or `@app.*`, since the formatting and delivery rules
  here are easy to get subtly wrong.
---

# Working on Slack-app features in this repo

This bot uses **Slack Bolt for Python (async)** in **Socket Mode**. The fastest
way to get something right is usually to copy an existing, working pattern from
the codebase — this skill points you at those and explains the non-obvious rules
behind them.

## Architecture (where things live)

- **`src/nf_core_bot/app.py`** — the `AsyncApp`, all `@app.*` registrations, and
  `_start()` which launches `AsyncSocketModeHandler` + background tasks.
- **`src/nf_core_bot/commands/router.py`** — parses `/nf-core <sub> …` and
  dispatches to handlers; central place for `ack()` + permission gating.
- **`src/nf_core_bot/permissions/checks.py`** — cached user-group membership
  (`is_core_team`, `is_core_team_or_maintainers`) and `get_usergroup_id` (the
  subteam ID used to build `@group` mentions).
- **`src/nf_core_bot/proposals/slack_utils.py`** — channel resolution, mention
  building, and Block Kit message posting. Good reference for formatting.
- **`src/nf_core_bot/forms/`** — the multi-step modal flow (views).
- **`docs/slack-app-setup.md`** — the manifest: scopes, events, shortcuts.

**Socket Mode matters:** the bot holds an outbound WebSocket; there is no
inbound HTTP server. "Request URL" fields in the Slack app config are ignored.
You receive interactions as events over the socket and reply via the Web API
(`app.client`) or the interaction's `respond`/`ack`.

**Async everywhere:** handlers are `async`. Blocking SDK calls (boto3, etc.) go
through `asyncio.to_thread`. Don't call blocking I/O directly in a handler.

## The 3-second rule (the most common footgun)

Slack expects an acknowledgement within ~3 seconds or it shows the user an error
and may retry the event. So: **`ack()` immediately, then do slow work in the
background.** Never run a multi-second task (GitHub fetch, Bedrock call, etc.)
before acking.

The repo's pattern: the router acks once, and slow handlers spawn a tracked
background task instead of awaiting inline — see
`proposals/__init__.py::spawn()` and its use in `app.py::on_message`,
`commands/proposals/review.py`, and `commands/proposals/shortcut.py`. Use that
helper (it keeps a strong reference so the task isn't garbage-collected and logs
exceptions). For events, Bolt auto-acks; still keep the handler body cheap and
offload work to `spawn()`.

## Registering interactions

| Decorator                    | Fires on                                                               | Example in repo                                |
| ---------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------- |
| `@app.command("/nf-core")`   | slash command                                                          | `app.py` → `dispatch`                          |
| `@app.event("message")`      | channel messages (needs `message.channels` event + `channels:history`) | `app.py::on_message` → `proposals/listener.py` |
| `@app.action(action_id)`     | button / interactive component                                         | `app.py` admin button                          |
| `@app.view(callback_id)`     | modal submission (`callback_id` can be a regex)                        | `app.py` registration steps                    |
| `@app.shortcut(callback_id)` | global/message shortcut                                                | `app.py::shortcut_*`                           |
| `@app.options(action_id)`    | external-select type-ahead                                             | `app.py::on_country_suggestions`               |

A handler receives Bolt-injected args by name (`ack`, `respond`, `client`,
`command`, `body`, `event`, `view`, `shortcut`, `say`). Take only what you need.

## Posting messages: pick the right delivery method

This is subtle and the source of real bugs. Choose based on _where_ the message
must appear and _who_ should see it:

| Method                                       | Use when                                     | Visibility                                                             | Caveat                                                                                                                                                                         |
| -------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `respond(...)` (slash/action response URL)   | replying to a slash command / action         | `response_type` `"in_channel"` (everyone) or `"ephemeral"` (just them) | Works in **any** conversation the command was run in — including a user's self-DM — with no bot membership needed. Valid ~30 min / 5 calls. **Prefer this for slash replies.** |
| `client.chat_postMessage(channel=…)`         | posting into a channel/thread                | public                                                                 | The bot must be a **member** of `channel`, or you get `channel_not_found`. Use `thread_ts` to reply in-thread.                                                                 |
| `client.chat_postEphemeral(channel, user=…)` | a note only one user should see in a channel | ephemeral                                                              | Needs the channel context; the user must be in it.                                                                                                                             |
| `client.chat_postMessage(channel=<user_id>)` | DM a user from the bot                       | private DM                                                             | Needs `im:write`. Opens the bot↔user DM.                                                                                                                                       |

**The self-DM trap:** a slash command run in a user's own "Jot to self" DM has a
`channel_id` the bot is _not_ in, so `chat_postMessage` 404s with
`channel_not_found`. That's exactly why slash replies use `respond` (response
URL) here — see `commands/proposals/review.py`. If you ever post a slash result
with `chat_postMessage(channel=command["channel_id"])`, you've reintroduced this
bug.

## Formatting messages

Two formatting systems, and mixing them up is the usual cause of "it shows the
literal `-` / `*` characters" or "the bullets don't nest":

- **mrkdwn** (the `text` field, and `section`/`context` blocks): `*bold*`,
  `_italic_`, `` `code` ``, `<url|label>` links, `<@U…>` / `<!subteam^ID>`
  mentions, `:emoji:`. **mrkdwn does not render `-`/`*`/`•` as real bullet lists
  and has no nesting** — a leading `-` or `•` shows up literally.
- **Block Kit**: structured blocks. For lists/rich content use a **`markdown`
  block** (renders standard Markdown — real bullets, bold, code) or a
  **`rich_text`** block (the only way to guarantee nested/indented bullets).

For anything with bullets, headings, or nesting, build Block Kit, don't send
mrkdwn text. See `proposals/slack_utils.py::build_review_blocks` for the working
pattern (a `section` header carrying the mention + a `markdown` body block + a
`context` footer, posted as one message). **Read `references/block-kit.md`** for
the full block reference, char limits, the rich_text nesting recipe, and the
mention-rendering caveat.

## Modals (views)

Open a modal with `client.views_open(trigger_id=…, view=…)` — the `trigger_id`
expires in ~3s, so open it right after `ack()`. Handle submission with
`@app.view(callback_id)`. Carry state across steps in `view["private_metadata"]`
(max 3000 chars; JSON-compress). The multi-step registration flow in `forms/`
(`loader.py` → `builder.py` → `handler.py`) is the reference implementation.

## Web API, scopes, and the manifest

Call the Web API via `app.client` / the injected `client` (an `AsyncWebClient`).
Common calls and the scope each needs are summarised in
**`references/web-api.md`** (also: pagination with `cursor`, and the
process-lifetime caching patterns this repo uses for channel IDs and group
membership).

Adding an interaction often means a manifest change (a new scope, event
subscription, or shortcut). Those are **not** code — they're done in the Slack
app config and require reinstalling the app. Document and follow
`docs/slack-app-setup.md`, and remember: after changing scopes/events you must
reinstall (the bot token does not rotate).

## Gotchas worth internalising

- **Nested bullets need a `markdown` or `rich_text` block.** A `•`/`-` in mrkdwn
  text is literal. (This caused a real formatting bug here.)
- **Keep group mentions in a `section` (mrkdwn) block.** `<!subteam^ID>`
  reliably notifies there; in a `markdown` block it may render but not ping.
  That's why `build_review_blocks` puts the mention in the header section, not
  the body.
- **Use `respond` for slash replies**, not `chat_postMessage` to the invocation
  channel (self-DM `channel_not_found`, above).
- **Don't let prettier touch Slack mrkdwn templates.** Prettier rewrites
  `*bold*` → `_italic_` and reflows line structure, both of which break Slack
  rendering. Slack text templates and bundled skills live under paths listed in
  `.prettierignore` for this reason — keep new ones there too.
- **`@app.event("message")` fires on every message** in subscribed channels.
  Filter cheaply and ignore the bot's own posts (resolve identity via
  `auth_test`) to avoid loops — see `proposals/listener.py::should_consider` and
  `_own_message`.
- **Resolving a public channel by name needs `channels:read`** (private:
  `groups:read`); the bot must also be invited to the channel to read/post.

## Testing

Handlers are tested by injecting `AsyncMock()` for `client`/`ack`/`respond` and
asserting on the calls (e.g. `respond.await_args.kwargs["response_type"]`, or
that `client.chat_postMessage` was awaited with the expected blocks). DynamoDB
is mocked with `moto`; shared env defaults live in `tests/conftest.py`. See
`tests/test_proposals_command.py` and `tests/test_proposals_listener.py` for
patterns to copy.

## External references

- Block Kit blocks: https://docs.slack.dev/reference/block-kit/blocks/
- `markdown` block:
  https://docs.slack.dev/reference/block-kit/blocks/markdown-block/
- Formatting with rich text:
  https://docs.slack.dev/block-kit/formatting-with-rich-text/
- Web API methods: https://docs.slack.dev/reference/methods/
- Bolt for Python: https://tools.slack.dev/bolt-python/

(There is a comprehensive community skill, `vercel-labs/slack-agent-skill`, but
it targets TypeScript/Bolt-for-JS — its Block Kit and Web API concepts transfer,
its framework idioms do not. Prefer the Python patterns in this repo.)
