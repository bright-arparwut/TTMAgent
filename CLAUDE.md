# TTMAgent

API endpoint for a LINE application (LINE chatbot), built in Python.

## Agent skills

### Issue tracker

Issues are tracked as local markdown files under `.scratch/<feature>/` in this repo (no remote tracker; external PRs are not a triage surface). See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Message flow

The unified decision map for how each LINE message type is handled (and who decides what): `docs/message-flow.md`.
