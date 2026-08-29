# TTMAgent

API endpoint for a LINE application (LINE chatbot), built in Python.

## Agent skills

### Issue tracker

Issues are tracked as GitHub Issues on `bright-arparwut/TTMAgent` (private), via the `gh` CLI. Wayfinder maps are issues labelled `wayfinder:map`, with their tickets as sub-issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Message flow

The unified decision map for how each LINE message type is handled (and who decides what): `docs/message-flow.md`.
