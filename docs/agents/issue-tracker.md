# Issue tracker: GitHub issues

Issues, PRDs, and wayfinder maps for this repo live as **GitHub issues** on
`bright-arparwut/TTMAgent`.

> **Note.** This file previously described a local-markdown tracker under `.scratch/`.
> That was scaffolding from the repo's first commit and never reflected practice: no
> `.scratch/` directory has ever existed, and both wayfinder maps live on GitHub
> issues, with [ADR 0010](../adr/0010-graphrag-lightrag-corpus.md) citing their issue
> URLs as the place each decision's reasoning is recorded.

## Conventions

- One issue per unit of work. The issue **title is its name** — refer to issues by
  name in prose, never by a bare number.
- Triage state is a **label**. See [`triage-labels.md`](./triage-labels.md) for the
  vocabulary.
- Conversation and resolutions are **issue comments**. An issue's body is the
  question; its comments are how it was answered.
- Work is linked back by referencing the issue number in the branch name, commit
  message, or PR body.

## When a skill says "publish to the issue tracker"

Create a GitHub issue on `bright-arparwut/TTMAgent`.

## When a skill says "fetch the relevant ticket"

Read the GitHub issue. The user will normally pass the issue number or URL directly.

## Wayfinding operations

The [wayfinder](https://github.com/mattpocock/skills) skill charts an effort as a map
plus decision tickets. Here is how each of its concepts is expressed on this tracker.

| Wayfinder concept | How it lives here |
| --- | --- |
| **The map** | An issue labelled `wayfinder:map`. |
| **Tickets** | **Sub-issues** of the map issue (GitHub's native parent/child relationship). |
| **Ticket type** | A `wayfinder:<type>` label: `research`, `prototype`, `grilling`, `task`. |
| **Claiming** | **Assign the issue to yourself before any work.** An open, unassigned ticket is unclaimed. |
| **Blocking** | A `**Blocked by:** #NN, #NN` line as the **first line of the ticket body**. |
| **The frontier** | Open sub-issues of the map that are unassigned and whose `Blocked by` issues are all closed. |
| **Resolution** | Post the answer as a comment, close the issue as `completed`, then append a one-line gist plus link to the map's **Decisions so far**. |
| **Assets** | Linked from the ticket, never pasted into it. |

GitHub's native issue-dependency feature is not used: it is not reachable from the
tooling agent sessions have here, so the `Blocked by` body convention is authoritative.
Keep it on the first line so it is visible in previews.

### Finding the frontier

There is no single query for it — check the map's sub-issue list and read the
`Blocked by` line on each open one. In practice the map's own **Not yet specified**
and **Decisions so far** sections tell you where the effort stands faster than the
issue list does.

### Existing maps

- [GraphRAG for TTMAgent, via an Obsidian vault](https://github.com/bright-arparwut/TTMAgent/issues/9)
  — complete (21/21). Produced [ADR 0010](../adr/0010-graphrag-lightrag-corpus.md).
- [Herbal remedies in the TTM Corpus: แนวทางการใช้ยาสมุนไพร as book three](https://github.com/bright-arparwut/TTMAgent/issues/45)
  — open.
