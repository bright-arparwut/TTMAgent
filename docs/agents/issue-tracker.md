# Issue tracker: GitHub Issues

Issues for this repo live on GitHub: **`bright-arparwut/TTMAgent`** (private).
Use the `gh` CLI.

Superseded the previous local-markdown convention (issues as files under
`.scratch/<feature-slug>/`). Nothing lives in `.scratch/` any more; the last
markdown-era map was migrated to issues #9–#18 and the directory removed. The old
files remain in git history at commit `7ebbb6d` if a body ever needs recovering.

## Conventions

- Triage state is a **label** (see `triage-labels.md`), not a `Status:` line.
- Conversation is issue comments.
- Work is claimed by **assigning the issue to yourself**, before starting.

## When a skill says "publish to the issue tracker"

```bash
gh issue create --title "<title>" --label "<label>" --body-file <path>
```

## When a skill says "fetch the relevant ticket"

```bash
gh issue view <number> --comments
```

## Wayfinding operations

How this repo expresses the [wayfinder](https://github.com/mattpocock) skill's concepts.

| Concept | Here |
|---|---|
| The map | An issue labelled `wayfinder:map` |
| Tickets | **Sub-issues** of the map issue |
| Ticket type | Label `wayfinder:research` / `:grilling` / `:prototype` / `:task` |
| Claim | Assign the issue to yourself — an open, unassigned ticket is unclaimed |
| Blocking | GitHub's **native** issue dependencies, not a body convention |
| Frontier | Open sub-issues that are unassigned and have no open blocker |
| Resolution | A comment holding the answer, then close the issue |

Current map: **#9 — GraphRAG for TTMAgent, via an Obsidian vault**

### List the tickets of a map

```bash
gh api /repos/bright-arparwut/TTMAgent/issues/9/sub_issues \
  --jq '.[] | "\(.number)\t\(.state)\t\(.assignee.login // "-")\t\(.title)"'
```

### Show what blocks a ticket

```bash
gh api /repos/bright-arparwut/TTMAgent/issues/<number>/dependencies/blocked_by \
  --jq '.[] | "\(.number)\t\(.state)\t\(.title)"'
```

### Add a ticket to a map

Create the issue, then link and wire it (both take the issue's **id**, not its number):

```bash
gh api -X POST /repos/bright-arparwut/TTMAgent/issues/9/sub_issues \
  -F sub_issue_id=$(gh api /repos/bright-arparwut/TTMAgent/issues/<new>  --jq .id)

gh api -X POST /repos/bright-arparwut/TTMAgent/issues/<new>/dependencies/blocked_by \
  -F issue_id=$(gh api /repos/bright-arparwut/TTMAgent/issues/<blocker> --jq .id)
```

### Claim, resolve, close

```bash
gh issue edit <number> --add-assignee @me
gh issue comment <number> --body-file resolution.md
gh issue close <number> --reason completed
```
