---
name: nfcore-proposal-review
description: >-
  Review an nf-core new pipeline proposal and produce a structured verdict with
  a draft GitHub comment. Use whenever given a link, issue number, or
  description from the nf-core/proposals repository, or when asked whether a
  proposed bioinformatics pipeline should be accepted into nf-core. Triggers on
  "review this proposal", "should we accept this", "nf-core/proposals#NNN", any
  github.com/nf-core/proposals link, "is this a good nf-core pipeline?", or any
  mention of evaluating a pipeline proposal against nf-core criteria. Always
  invoke this skill rather than doing an ad-hoc review — it handles the
  research, overlap checking, and structured output.
---

# nf-core New Pipeline Proposal Review

Proposals live at https://github.com/nf-core/proposals/issues (label:
`new-pipeline`). The goal is a structured verdict that helps the maintainer team
reach a decision, posted as a single Slack message. This is not a scientific
peer review — even "I'm not familiar with the area, but looks alright" is a
useful contribution.

The triggering proposal is already provided: its body and every comment are
included in the user message. Start with the overlap research (Step 1) — do not
try to re-fetch the issue.

## Tooling

You have one tool, `run_command`, a read-only command runner. Through it you can
run:

- the bundled scripts in `scripts/` alongside this file. Use the exact
  `<skill-dir>` absolute path given in the prompt:
  - `bash <skill-dir>/scripts/check_tools.sh <tool1> [tool2 ...]`
  - `bash <skill-dir>/scripts/list_pipelines.sh`
  - `bash <skill-dir>/scripts/fetch_proposal.sh [NUMBER]` — only needed to
    cross-reference a *different* proposal; the triggering one is already in the
    user message.
- `gh` (read-only GitHub CLI), `jq`, and the `nf-core` CLI. For module /
  subworkflow overlap you may also use `nf-core modules info <tool>`,
  `nf-core modules list remote`, and `nf-core subworkflows list remote`, which
  query the canonical registry directly.

Write operations and any other binaries are blocked.

## Step 1: Tool inventory, then pipeline overlap

Pull the proposed tool list, purpose, data type, organism scope, and proposer
handle from the provided proposal. Then: check tools → check if they're already
in nf-core → check which pipelines use them → decide.

### Tool inventory

```bash
bash <skill-dir>/scripts/check_tools.sh <tool1> [tool2 ...]
```

For each tool this checks nf-core/modules presence and which pipeline `main.nf`
files reference it. If several proposed tools are already used together in an
existing pipeline, that's a strong overlap signal.

Map the overlap pattern to a verdict hint:

| Tool overlap pattern                                              | What it suggests                                                  |
| ----------------------------------------------------------------- | ----------------------------------------------------------------- |
| All tools in nf-core modules, already used together in a pipeline | Extend that pipeline; don't create a new one                      |
| Tools in nf-core but not combined this way                        | Possibly a subworkflow worth adding to an existing pipeline       |
| Tools not yet in nf-core + genuinely novel combination            | New pipeline more justified                                       |
| Standard tools + one novel algorithm                              | New pipeline only if the novel algorithm is the load-bearing part |

### Check existing pipelines directly

```bash
bash <skill-dir>/scripts/list_pipelines.sh
```

Look specifically for:

- Pipelines handling the same data type or analysis
- Pipelines using overlapping tool sets even if differently framed
- Archived pipelines that cover the space (may be revivable)

## Step 2: Apply the four criteria

Evaluate each and note your evidence — a short phrase is fine, you don't need
prose.

### A. Workflow specificity (primary gate)

The nf-core requirement at
https://nf-co.re/docs/specifications/pipelines/requirements/workflow_specificity:

- One pipeline per data + analysis type
- No organism-specific pipelines unless the tooling genuinely can't generalise
- Prefer extending an existing pipeline over creating a new one

This is the most common rejection reason. The key test: **is this a novel
tooling combination, or is it a different organism/tissue/sample type running
through tools that already exist in nf-core?**

"Field deployment" or "our community needs it" arguments don't make a workflow
distinct. "The biological problem is structurally different and requires
different algorithms" does.

### B. Testability

- Can this run in nf-core CI with open test data?
- Does it require proprietary tools, licensed software, or hardware-bound
  executors (DRAGEN is the canonical example)?
- "Stubs only" doesn't meet the bar — nf-core's Megatests and results comparison
  convention require real execution.

### C. Novelty — what's the genuine gap?

- What does this bring that nothing in nf-core currently covers?
- Is the novel part a whole pipeline's worth, or one or two
  modules/subworkflows?
- Is there a published method being implemented, or is it "standard tools run in
  order"?

The test: if you could achieve 90% of the value by adding a module or
subworkflow to an existing pipeline, that's probably the right path.

### D. Sustainability

- Solo author or a team?
- Does the proposer have existing nf-core experience (check their GitHub for
  merged modules/PRs)?
- Starting from bash scripts vs. existing Nextflow code?
- Niche, solo-authored pipelines are nf-core's main abandonment failure mode.
  This is a risk factor, not a hard reject, but it should prompt a "do you have
  collaborators?" question before approval.

## Step 3: Classify the verdict

| Verdict                  | When to use                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| **Clear Reject**         | Fails workflow specificity with no salvage path, OR untestable in CI                                                |
| **Conditional Accept**   | Novel gap, passes specificity, conditions are not blockers                                                          |
| **Request changes**      | Fails as proposed (usually specificity) but has a genuine novel component worth steering toward a different framing |
| **Borderline**           | Passes hard criteria but has real sustainability or scope risk; needs a conversation before approval                |
| **Needs More Info**      | Can't assess without a specific answer from the proposer; include the question                                      |

## Step 4: Produce the Slack message

Your entire response is rendered verbatim in a Slack Markdown block. Standard
Markdown renders natively: `**bold**`, `-` bullets with two-space nested
indentation, `[text](url)` links, and code blocks.

- **No preamble, no meta-commentary.** Never write "Here is the review", "I have
  enough to…", or similar. Start directly with the verdict line. Do not add
  `---` separators or a top-level heading — the bot adds the title.
- **Be brief.** Keep the whole message (excluding the draft GitHub comment) well
  under ~1500 characters. Short bullets, not paragraphs. Cut anything a
  maintainer doesn't need to decide.
- **Do not wrap the message in a code block.** The only code block in your output
  is the draft GitHub comment at the end.

Emoji key: ✅ pass/accept, ⚠️ partial/borderline, ❌ fail/reject; 🟢/🟡/🔴 =
low/med/high risk.

Follow this structure (these lines are the literal Markdown to emit, minus this
surrounding explanation):

> **Verdict: ✅ Conditional Accept**
>
> - **Novelty:** one line, or "none identified"
> - **Overlap:** most relevant existing pipeline(s), one line
> - **Specificity:** ✅ Pass — ≤8 words
> - **Testability:** ⚠️ Partial — ≤8 words
> - **Sustainability:** 🔴 Low — ≤8 words
>
> **Why**
>
> - 2–3 short bullets: what it does, the gap it fills, the main risk.
>
> **Blockers / conditions** (only if relevant)
>
> - one-line bullets; nest sub-points with two-space indentation if needed.
>   Distinguish blockers (must resolve before `/approve`) from softer conditions
>   and optional suggestions.

Then add the **draft GitHub comment** as the final element, wrapped in a single
triple-backtick code block so a maintainer can copy it. Inside that block:

- Write GitHub-flavoured Markdown, keep it under ~150 words.
- **Do not hard-wrap** — put each paragraph and each bullet on ONE line with a
  blank line between paragraphs. A stray mid-paragraph newline renders as a
  `<br>` on GitHub.
- Use `/approve` or `/reject` per nf-core convention (two `/reject` comments =
  rejection).
- Tone: direct and constructive, not corporate. Match the formality of the
  existing thread.
- If rejecting, offer a concrete path forward where one exists.
- If you're not familiar with the domain, say so — flagging an apparent overlap
  from a non-expert perspective is still valuable.

## Common patterns and pitfalls

**The subworkflow/module test** (most important redirect signal): If the unique
functionality fits within 1-2 new subworkflows added to an existing pipeline,
reviewers will redirect rather than accept. The overlap threshold is low — even
60-70% coverage by an existing pipeline is enough to trigger "merge with
existing." Ask explicitly: could this be a subworkflow PR to an adjacent
pipeline?

**Organism-specific arguments that don't work**: "our community needs this,"
"it's for field deployment," "the audience is different." These are not
workflow-distinctness arguments. The exception is when the biological problem
structurally requires different algorithms (e.g., Plasmodium multiclonal
infection deconvolution has no human analogue).

**SIG consultation as a positive signal**: Proposals that mention having
discussed scope with the relevant nf-core SIG (meta-omics, single-cell, spatial,
etc.) or related pipeline maintainers move much faster. A proposal with no
community consultation mentioned should be flagged — it likely needs a
round-trip to the SIG before a decision can be reached. Suggest it in the
comment.

**Late-stage engagement penalty**: If the proposer has already built a
near-complete pipeline before proposing, the core team treats this as social
friction — the team has sunk costs that make merging harder. This is an explicit
anti-pattern. The right framing is early community co-design, not "here's what
we built, please accept it." Flag it and note the core team has been blunt about
this: "nf-core isn't a pipeline publishing warehouse."

**Crowded domains**: In domains with multiple existing pipelines (spatial
transcriptomics, single-cell, metagenomics), the question is not "does this
cover different tools" but "does the underlying data format or biological
question require a fundamentally different processing approach?" A new assay
type with different segmentation requirements (spatial) justifies a new
pipeline; a different organism processed with the same tools does not.

**The mega-pipeline shape nf-core resists**: "Run pipeline A, then run pipeline
B, then add one novel module." The question becomes: can the novel module stand
alone in an existing pipeline?

**Regulatory/compliance pipelines**: Legitimate but unusual — value is the
execution context (GxP audit trails, Seqera Platform provenance) rather than
novel computational steps. These face higher scrutiny and need more approvers.
Advise proposers to spell out the compliance rationale explicitly; reviewers
will otherwise ask whether a plugin would suffice.

**Name collisions**: A proposed name clashing with a well-known tool (e.g.
"midas" = famous metagenomics database) is a condition to flag, not a blocker.

**Going quiet**: Note if the proposer hasn't responded to the most recent
feedback round. This affects the realistic approval timeline and can justify a
softer close.

**Ping the relevant pipeline leads**: If the proposal overlaps with an existing
pipeline, suggest directly pinging the leads of that pipeline on GitHub and in
the relevant Slack channel. This is often more effective than waiting for them
to find the proposal thread.
