# Slack Web API, scopes & manifest reference

Call the Web API through the injected `client` (an `AsyncWebClient`, also at
`app.client`). Every method returns an awaitable `AsyncSlackResponse`; read
fields with `resp["field"]` / `resp.get("field")`.

## Methods used here and the scope each needs

| Method                                   | Purpose                                      | Bot scope                                                                           |
| ---------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------- |
| `chat_postMessage`                       | post a message / thread reply                | `chat:write`                                                                        |
| `chat_postEphemeral`                     | message only one user sees                   | `chat:write`                                                                        |
| `chat_update` / `chat_delete`            | edit / remove a message                      | `chat:write`                                                                        |
| `conversations_list`                     | find a channel by name (paginated)           | `channels:read` (public), `groups:read` (private)                                   |
| `conversations_info`                     | channel metadata (e.g. topic)                | `channels:read` / `groups:read`                                                     |
| `conversations_setTopic`                 | set channel topic                            | `channels:manage`/`channels:write.topic` (public) or `groups:write.topic` (private) |
| `usergroups_list`                        | resolve a group handle → subteam ID          | `usergroups:read`                                                                   |
| `usergroups_users_list`                  | members of a user group                      | `usergroups:read`                                                                   |
| `users_info`                             | user profile, timezone                       | `users:read`                                                                        |
| `team_profile_get` / `users_profile_get` | custom profile fields (e.g. GitHub username) | `users.profile:read`                                                                |
| `views_open` / `views_update`            | open / update a modal                        | (none beyond app install)                                                           |
| `auth_test`                              | the bot's own user/bot id (loop-avoidance)   | (none)                                                                              |

`message.channels` (and friends) are **event subscriptions**, not scopes — they
must be added in the manifest _and_ paired with the matching read scope
(`channels:history`) for the bot to receive message text.

## Pagination

List endpoints return at most `limit` items plus a cursor. Loop until the cursor
is empty:

```python
cursor = None
while True:
    resp = await client.conversations_list(types="public_channel,private_channel",
                                            exclude_archived=True, limit=200, cursor=cursor)
    for ch in resp.get("channels", []):
        ...
    cursor = (resp.get("response_metadata") or {}).get("next_cursor")
    if not cursor:
        break
```

Reference: `proposals/slack_utils.py::resolve_channel_id`.

## Caching (avoid hammering the API on hot paths)

Slack rate-limits per method, and some lookups (channel-name→ID, group
membership) are needed on frequently-fired events. This repo caches them:

- **Channel IDs** — resolved once and kept for the process lifetime
  (`proposals/slack_utils.py::_channel_cache`,
  `scheduler/oncall_jobs.py::_resolve_channel_id`).
- **User-group membership** — cached per handle with a TTL
  (`permissions/checks.py`, `CACHE_TTL = 300`s) behind an `asyncio.Lock` so
  concurrent handlers don't all refetch.
- **Bot identity** — `auth_test` result cached so the message listener can skip
  its own posts cheaply (`proposals/listener.py::_own_message`).

When you add a new per-event lookup, cache it the same way rather than calling
the API on every event.

## Building mentions

A user-group ("@core-team") mention is `<!subteam^{id}>`, where `{id}` is the
group's `S…` ID. Resolve it via `permissions/checks.py::get_usergroup_id` (which
goes through the cached `usergroups_list`) — see
`proposals/slack_utils.py::core_team_mention`. Mentions reliably notify from a
`section`/mrkdwn block; see `references/block-kit.md` for the rich_text mention
elements if you need a ping inside structured content.

## Manifest changes (scopes / events / shortcuts)

These are configured in the Slack app settings, not in code, and require
reinstalling the app afterwards (the bot token does **not** rotate on reinstall,
so no env/SSM change is needed). The full, current setup — scopes table, event
subscriptions, shortcuts, Socket Mode tokens — lives in
**`docs/slack-app-setup.md`**; update it whenever you add an interaction that
needs a new scope, event, or shortcut, and tell the operator to reinstall.

Adding a feature usually means a coordinated change in three places: the handler
(code), the manifest (scope/event/shortcut), and `docs/slack-app-setup.md`.

## Rate limits

Most methods are tier-limited (per-minute). The SDK surfaces 429s as
`SlackApiError`; for routine bot volume the caching above is enough. Don't add
retry storms — back off on 429 (`Retry-After`).
