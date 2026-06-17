---
name: nfcore-proposal-review
description: Review an nf-core new pipeline proposal and produce a structured verdict with a draft GitHub comment. Use whenever given a link, issue number, or description from the nf-core/proposals repository, or when asked whether a proposed bioinformatics pipeline should be accepted into nf-core. Triggers on: "review this proposal", "should we accept this", "nf-core/proposals#NNN", any github.com/nf-core/proposals link, "is this a good nf-core pipeline?", or any mention of evaluating a pipeline proposal against nf-core criteria. Always invoke this skill rather than doing an ad-hoc review — it handles the research, overlap checking, and structured output.
---

# nf-core New Pipeline Proposal Review

Proposals live at https://github.com/nf-core/proposals/issues (label:
`new-pipeline`). The goal is a structured verdict that helps the maintainer team
reach a decision. This is not a scientific peer review — even "I'm not familiar
with the area, but looks alright" is a useful contribution.

Scripts are in `scripts/` alongside this file. `<skill-dir>` = the base
directory shown in the skill header when this skill was loaded.

## Mode: single proposal vs. batch sweep

**Single proposal**: given a number, URL, or name - review that one proposal and
produce a verdict + draft comment.

**Batch sweep**: asked to "review all open proposals" or "give me a summary of
what's in the queue" - fetch all open proposals, review each one, produce the
quick-map table at the end. Takes longer but is the right tool when a maintainer
needs to triage the whole queue. Use the same criteria for each entry, and group
them by verdict category in the output.

## Step 1: Fetch the proposal(s)

Accept issue number, URL, pasted text, or just a name ("review the shallowseq
proposal").

```bash
bash <skill-dir>/scripts/fetch_proposal.sh [NUMBER]
# omit NUMBER to list all open proposals
```

Extract from the proposal:

- Proposed pipeline name
- Stated purpose and analysis type
- Target data type and organism scope (is it organism-specific?)
- Proposed tool list
- Proposer's GitHub handle

## Step 2: Tool inventory first, then pipeline overlap

**check tools → check if they're already in nf-core → check which pipelines use
them → decide**.

### 2a–2b. Tool inventory

```bash
bash <skill-dir>/scripts/check_tools.sh <tool1> [tool2 ...]
```

For each tool this checks nf-core/modules presence and which pipeline `main.nf`
files reference it. If several proposed tools are already used together in an
existing pipeline, that's a strong overlap signal.

### 2c. Map tool overlap to a verdict hint

| Tool overlap pattern                                              | What it suggests                                                  |
| ----------------------------------------------------------------- | ----------------------------------------------------------------- |
| All tools in nf-core modules, already used together in a pipeline | Extend that pipeline; don't create a new one                      |
| Tools in nf-core but not combined this way                        | Possibly a subworkflow worth adding to an existing pipeline       |
| Tools not yet in nf-core + genuinely novel combination            | New pipeline more justified                                       |
| Standard tools + one novel algorithm                              | New pipeline only if the novel algorithm is the load-bearing part |

### 2d. Check existing pipelines directly

```bash
bash <skill-dir>/scripts/list_pipelines.sh
```

Look specifically for:

- Pipelines handling the same data type or analysis
- Pipelines using overlapping tool sets even if differently framed
- Archived pipelines that cover the space (may be revivable)

## Step 3: Apply the four criteria

Evaluate each and note your evidence — a short phrase is fine, you don't need
prose.

### A. Workflow Specificity (primary gate)

The nf-core requirement at
https://nf-co.re/docs/specifications/pipelines/requirements/workflow_specificity:

- One pipeline per data+analysis type
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
- Is the novel part a whole pipeline worth, or one or two modules/subworkflows?
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

## Step 4: Classify the verdict

| Verdict                | When to use                                                                                                         |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **CLEAR_REJECT**       | Fails workflow_specificity with no salvage path, OR untestable in CI                                                |
| **CONDITIONAL_ACCEPT** | Novel gap, passes specificity, conditions are not blockers                                                          |
| **REJECT_SALVAGEABLE** | Fails as proposed (usually specificity) but has a genuine novel component worth steering toward a different framing |
| **BORDERLINE**         | Passes hard criteria but has real sustainability or scope risk; needs a conversation before approval                |
| **NEEDS_MORE_INFO**    | Can't assess without a specific answer from the proposer; include the question                                      |

## Step 5: Produce the review

### Verdict block

```
PROPOSAL: #NNN <pipeline-name>
VERDICT: <CATEGORY>
NOVELTY: <what's genuinely new, or "none identified">
OVERLAP: <most relevant existing pipelines>
SPECIFICITY: PASS / FAIL / PARTIAL — <one line of evidence>
TESTABILITY: PASS / FAIL — <one line of evidence>
SUSTAINABILITY: LOW / MEDIUM / HIGH — <one line of evidence>
```

### Analysis narrative (2-4 paragraphs)

1. What the proposal is actually doing in plain terms (your synthesis, not a
   quote)
2. How it compares to the most relevant existing pipelines
3. The strongest argument for acceptance
4. The strongest argument for rejection or steering

### Conditions / Steering (if CONDITIONAL_ACCEPT or REJECT_SALVAGEABLE)

Distinguish clearly:

- **Blockers** — must resolve before /approve
- **Conditions** — should address, not hard blockers
- **Suggestions** — helpful but optional

### Draft GitHub comment

A ready-to-post comment. Conventions:

- Use `/approve` or `/reject` per nf-core convention (two `/reject` comments =
  rejection)
- Tone: direct and constructive, not corporate. Match the formality level of the
  existing thread.
- If rejecting, offer a concrete path forward where one exists
- Keep it under 300 words — maintainers' time is scarce

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

**When you're not domain-familiar**: Say so explicitly in the comment. A
maintainer who knows the area will weigh in, but flagging "this looks like it
overlaps with sarek's preprocessing based on the tool list" from a non-expert
perspective is still valuable.

**Ping the relevant pipeline leads**: If the proposal overlaps with an existing
pipeline, directly ping the leads of that pipeline on GitHub and in the relevant
Slack channel. This is often more effective than waiting for them to find the
proposal thread.

---

## Runtime addendum (nf-core-bot / Slack + Bedrock)

This section is appended for the automated Slack-bot context and is NOT part of
the upstream skill. It tunes the skill for where the review runs and is posted.

**Tooling.** You have one tool, `run_command`, a read-only command runner.
Through it you can run:

- the bundled scripts above: `bash <skill-dir>/scripts/fetch_proposal.sh`,
  `bash <skill-dir>/scripts/check_tools.sh <tools…>`,
  `bash <skill-dir>/scripts/list_pipelines.sh` (use the exact `<skill-dir>`
  absolute path given in this prompt);
- `gh` (read-only GitHub CLI), `jq`, and the `nf-core` CLI. For module /
  subworkflow overlap you may also use `nf-core modules info <tool>` /
  `nf-core modules list remote` / `nf-core subworkflows list remote`, which
  query the canonical registry directly. Write operations and any other binaries
  are blocked.

**The proposal is already provided.** The triggering issue's body and every
comment are included in the user message, so you can skip Step 1's
`fetch_proposal.sh` for the issue itself and start at Step 2 (tool/pipeline
overlap). Use `fetch_proposal.sh` only if you need to cross-reference another
proposal.

**Output format — Slack mrkdwn, not GitHub Markdown.** The review is posted as a
Slack message, which uses a restricted "mrkdwn" syntax:

- Use `*bold*` (single asterisks), `_italic_`, and `- ` bullets.
- Do NOT use Markdown headings (`#`, `##`) or Markdown tables — they render as
  literal text in Slack. Use `*Bold labels:*` on their own line instead of
  headings.
- Put the Step 5 verdict block and the draft GitHub comment inside
  triple-backtick code fences so they are easy to copy.
- Lead with the verdict, then a short narrative, then the draft comment. The
  maintainer team is the audience — keep it tight.
