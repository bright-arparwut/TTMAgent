# Message-Flow Visualization — Design

**Date:** 2026-07-06
**Status:** Approved

## Purpose

Explain, visually, how the TTM advisor handles each kind of incoming LINE
message (greeting, symptom description, tongue photo) and how decisions are
made along the way — distinguishing *deterministic* decisions (code) from
*agentic* decisions (the Advisor Model's LLM tool loop).

The visualization depicts the system **as built** (accurate to
`app/pipeline/dispatcher.py`, `app/advisor/tools.py`, and ADRs 0001/0002),
not a proposed redesign. In particular:

- Tongue detection/classification is a **deterministic pipeline step**
  (`TongueDetector` → `VisionDescriber`) that runs *before* the agent —
  it is not an agent tool.
- There is **no save-record tool**. Health Record writes happen once,
  deterministically, at Consultation close via the Relevance Gate
  (`docs/adr/0002-health-record-only-memory.md`).
- The agent's only tools are read-only: `search_health_records`,
  `get_health_record_by_date`.

## Scope

Full lifecycle: per-message handling **plus** Consultation close
(stale-buffer check → Relevance Gate → conditional Health Record write).

## Content: the unified decision map

One flowchart shared by both deliverables. Nodes and edges must match the
code exactly — no invented nodes.

**Entry — LINE webhook, routed by event type:**

| Branch | Path |
|---|---|
| `follow` | One-time Thai welcome + disclaimer → end |
| `text` | Per-user lock → Consultation Turn |
| `image` | Loading indicator → download → TongueDetector → *(tongue found?)* — **no**: retake guidance → end (not recorded); **yes**: crop → VisionDescriber → Tongue Description injected as text turn → Consultation Turn |

**Consultation Turn (shared spine, `_run_consultation_turn`):**

1. Stale Working Buffer? → **Relevance Gate** *(health content?)* —
   **yes**: write Health Record entry; **no**: discard
2. Append user turn to Working Buffer
3. Retrieve context: recent Health Record summaries + RAG passages (TTM corpus)
4. **Advisor agent** — LangGraph ReAct loop *(answer directly, or call a
   read-only record tool?)*
5. Reply in Thai → append advisor turn to Working Buffer

**Three decision diamonds**, visually coded by who decides:

| Decision | Decider | Kind |
|---|---|---|
| Tongue found? | `TongueDetector` | Deterministic |
| Health content? (gate) | Relevance Gate at close | Deterministic trigger, LLM-scored |
| Need past records? | Advisor Model in ReAct loop | Agentic |

## Scenario walkthroughs (HTML artifact only)

Five clickable scenarios; selecting one highlights its path on the map and
shows step-by-step notes:

| Scenario | Path highlight | Teaching point |
|---|---|---|
| 👋 Says "hello" | text → spine → agent replies directly | No tool call; gate later discards non-health chat |
| 🤒 Describes feelings | text → spine → agent may call record tools | RAG + record context shape the reply |
| 👅 Tongue photo | image → detect ✓ → describe → spine | Vision describes, agent assesses (two-model split) |
| 📷 Photo, no tongue | image → detect ✗ → retake guidance | Never assess what wasn't detected |
| ⏰ Returns after gap | stale close → gate → maybe record write | The only write path in the system |

## Deliverable A — repo doc

- **File:** `docs/message-flow.md`
- Unified map as a **Mermaid flowchart** + short prose per branch
- Cross-links to `CONTEXT.md` terms and ADRs 0001/0002
- Linked from `CLAUDE.md`

## Deliverable B — HTML artifact

- Self-contained page: inline SVG map + vanilla JS scenario picker
  (no CDN/external resources, per artifact CSP)
- Layout: scenario buttons on top, map center, step-notes panel beside it
- English labels; actual Thai bot messages (welcome, retake guidance)
  shown inside step notes
- Built after loading the `artifact-design` skill; published via the
  Artifact tool

## Execution

Two ecc agents dispatched in parallel (per implementation plan):
one writes `docs/message-flow.md`, one builds the HTML file
(main session publishes it via Artifact).

## Verification

- Every edge in both diagrams checked against `app/pipeline/dispatcher.py`,
  `app/advisor/tools.py`, `app/advisor/graph.py`,
  `app/memory/relevance_gate.py`
- Mermaid syntax render-checked before commit
- Artifact opens, all five scenario paths highlight correctly, no
  horizontal page scroll

## Out of scope

- Any change to runtime code or architecture
- Thesis-paper figure export (can be derived later from either deliverable)
- Agent-internal prompt details beyond the tool-loop decision
