# Block Kit & message formatting reference

Slack has two formatting systems. Picking the wrong one is the usual cause of
"the bullet character shows literally" or "my list won't indent". Read this when
building or debugging message layout.

## mrkdwn (Slack's lightweight markup)

Used in the message `text` field and in `section`/`context` block text. It is
**not** standard Markdown:

- **bold**: `*bold*` (single asterisks)
- **italic**: `_italic_`
- **strikethrough**: `~strike~`
- **inline code**: `` `code` `` ; **code block**: triple backticks
- **link**: `<https://example.com|label>`
- **user mention**: `<@U012ABC>`
- **user-group mention**: `<!subteam^S012ABC>` (optionally
  `<!subteam^S012ABC|@handle>`)
- **@here / @channel**: `<!here>` / `<!channel>`
- **emoji**: `:tada:`
- **blockquote**: leading `>`

**mrkdwn has no real lists.** A leading `-`, `*`, or `•` renders literally and
nothing nests. For lists, use a `markdown` or `rich_text` block (below).

## Block types you'll use

Build messages as a list of blocks and pass them to `chat_postMessage(blocks=…)`
/ `respond(blocks=…)` along with a short plain-text `text=` fallback (used for
notifications and accessibility).

- **`section`** — mrkdwn text (and optional `fields`, `accessory` like a
  button). The right place for `<!subteam^ID>` mentions and `<url|label>` links,
  since mentions reliably notify here. Limit: 3000 chars in `text`.
- **`markdown`** — a single standard-Markdown string. Renders real bullets,
  bold, links, code blocks, blockquotes, tables. Cumulative limit **12,000
  chars** across all markdown blocks in a payload. Best for LLM-generated
  bodies. Caveat: Slack-style mention tokens (`<!subteam^…>`) are not guaranteed
  to notify from inside a markdown block — keep pings in a `section`.
- **`rich_text`** — the structured format the Slack client itself composes.
  `rich_text_list` with `style: "bullet"|"ordered"` and an `indent` integer is
  the **only way to guarantee nested/indented bullets**. More verbose to build
  (nested JSON) but precise.
- **`context`** — small, muted text (`elements`), good for footers/disclaimers.
- **`divider`**, **`header`** (plain_text), **`actions`** (buttons/selects).

### Choosing

- Simple one-liner, or you need a mention/link/button → **section** (mrkdwn).
- A body with bullets/bold/code, especially model-generated Markdown →
  **markdown** block (let Slack render standard Markdown).
- You specifically need reliably nested/indented bullets → **rich_text** with
  `rich_text_list` + `indent`.
- Footer/byline → **context**.

## One message, multiple blocks

A single message can carry many blocks (overall message cap ~40,000 chars;
section text 3000; markdown 12,000 cumulative). Prefer **one `chat_postMessage`
with several blocks** over posting multiple messages or chunked thread replies —
it reads as a single coherent post. Only split into multiple markdown blocks if
a body exceeds 12,000 chars.

## The repo's review message (working example)

`proposals/slack_utils.py::build_review_blocks` assembles, in one message:

1. a `section` (mrkdwn) header — the linked title + the `<!subteam^ID>` mention
   (so it notifies);
2. one or more `markdown` blocks — the model's Markdown review (bullets,
   nesting, bold, fenced code all render);
3. a `context` footer — the automated-review disclaimer.

That split exists precisely so the mention notifies (section) while the body
gets proper Markdown rendering (markdown block).

## Nested bullets via rich_text (when markdown nesting isn't enough)

```json
{
  "type": "rich_text",
  "elements": [
    {
      "type": "rich_text_list",
      "style": "bullet",
      "indent": 0,
      "elements": [
        {
          "type": "rich_text_section",
          "elements": [{ "type": "text", "text": "Top-level item" }]
        }
      ]
    },
    {
      "type": "rich_text_list",
      "style": "bullet",
      "indent": 1,
      "elements": [
        {
          "type": "rich_text_section",
          "elements": [{ "type": "text", "text": "Nested item" }]
        }
      ]
    }
  ]
}
```

Each indent level is a separate `rich_text_list` with `indent` incremented.
Inline styling lives on `text` elements (`"style": {"bold": true}`), and
mentions are their own element types (`{"type":"user","user_id":"U…"}`,
`{"type":"usergroup","usergroup_id":"S…"}`) — which is also how to get a mention
to notify from inside rich_text.

## mrkdwn vs Markdown in one place

When a string is destined for a **section** block, write **mrkdwn** (`*bold*`,
`<url|label>`). When it's destined for a **markdown** block, write **standard
Markdown** (`**bold**`, `[label](url)`, `-` lists). Don't send standard Markdown
into a section (asterisks/links won't render) or mrkdwn into a markdown block.

## Don't let prettier reformat Slack text templates

Prettier rewrites `*bold*` → `_italic_` and reflows lines — both silently break
Slack rendering, and they collapse a template's intentional line structure. Any
file holding Slack mrkdwn (e.g. message templates) belongs in `.prettierignore`.
GitHub-rendered docs like this reference are fine to let prettier format.
