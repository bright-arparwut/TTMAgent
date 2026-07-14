# Message Flow

How the TTM advisor handles each kind of incoming LINE message, and who
makes each decision along the way. Blue diamonds are decided by
deterministic code, the amber diamond is code-triggered but LLM-scored,
and the purple diamond is the Advisor Model's own agentic choice.
The Health Profile write path is defined by [ADR 0003](adr/0003-health-profile-projection.md).

```mermaid
flowchart TD
    WH([LINE webhook]) --> EVT{"Event type?"}

    EVT -->|follow| WEL["One-time Thai welcome + disclaimer"]
    WEL --> END1([End])

    EVT -->|text| LOCK["Acquire per-user lock"]

    EVT -->|image| LOAD["Show loading indicator"]
    LOAD --> DL["Download image bytes"]
    DL --> DET["TongueDetector: detect + crop"]
    DET --> TF{"Tongue found?"}
    TF -->|no| RETAKE["Thai retake guidance<br/>turn not recorded"]
    RETAKE --> END2([End])
    TF -->|crop returned| SAVE["Persist Tongue Photo<br/>(ADR 0007, gate-independent)"]
    SAVE --> PG{"Passed confidence gate?"}
    PG -->|no| RETAKE
    PG -->|yes| VD["VisionDescriber &rarr; Tongue Description<br/>(patched into the saved photo)"]
    VD --> INJECT["Description injected as text turn"]
    INJECT --> LOCK

    subgraph SPINE["Consultation Turn — shared spine"]
        STALE{"Working Buffer stale?<br/>(gap > 6 h)"}
        STALE -->|yes| GATE{"Relevance Gate:<br/>health content?"}
        GATE -->|yes| REC["Write Health Record entry"]
        REC --> PU["Profile Updater:<br/>patch Health Profile<br/>(ADR 0003)"]
        PU --> APPEND["Append user turn to Working Buffer"]
        GATE -->|no| DISCARD["Discard buffer —<br/>Health Profile untouched"]
        DISCARD --> APPEND
        STALE -->|no| APPEND
        APPEND --> CTX["Retrieve context:<br/>Working Buffer replay (message history) +<br/>Health Profile + recent Health Record summaries + RAG passages"]
        CTX --> AGENT{"Advisor ReAct loop:<br/>answer directly or call a record tool?"}
        AGENT -->|call tool| TOOLS["search_health_records /<br/>get_health_record_by_date (read-only)"]
        TOOLS --> AGENT
        AGENT -->|answer| REPLY["Reply in Thai"]
        REPLY --> MENU["Parse Topic Menu block<br/>(ADR 0006): visible text +<br/>Quick Reply topics"]
        MENU --> APPADV["Append RAW advisor turn<br/>(menu block included)<br/>to Working Buffer"]
    end

    LOCK --> STALE
    APPADV --> END3([End])

    classDef deterministic fill:#e6f0fa,stroke:#2b6cb0
    classDef llmscored fill:#fdf3e0,stroke:#b7791f
    classDef agentic fill:#f3e8fd,stroke:#6b46c1
    class TF,PG,STALE,MENU deterministic
    class GATE llmscored
    class AGENT agentic
```

## The three decision diamonds

| Decision | Decider | Kind |
|---|---|---|
| Tongue found? | `TongueDetector` (`app/vision/detector.py`) | Deterministic |
| Health content? | Relevance Gate at Consultation close (`app/memory/relevance_gate.py`) | Deterministic trigger, LLM-scored |
| Need past records? | Advisor Model in the ReAct loop (`app/advisor/graph.py`) | Agentic |

The Profile Updater adds no fourth diamond: it runs if and only if the
gate passes — one boundary guards both long-term memory writes.

## Branch notes

**`follow`** — a one-time Thai welcome and disclaimer is sent
(`app/pipeline/dispatcher.py`); nothing is stored.

**`text`** — the per-user lock serializes turns, then the shared spine
runs: close a stale [Consultation](../CONTEXT.md) if one is waiting,
load the [Working Buffer](../CONTEXT.md)'s prior turns, append the new
turn, retrieve context, run the Advisor with the prior turns replayed as
message history ([ADR 0005](adr/0005-working-buffer-replay.md), capped
by config), reply in Thai. The reply's trailing `[หัวข้อ]` block, if any,
becomes [Topic Menu](../CONTEXT.md) Quick Reply buttons
([ADR 0006](adr/0006-topic-menu-delimiter-protocol.md)); the raw reply --
block included -- is what the Working Buffer stores, so "ข้อสอง" still
resolves after the buttons disappear.

**`image`** — tongue detection is a deterministic pipeline step that runs
*before* the agent ([ADR 0001](adr/0001-two-model-pipeline.md)): the
[Vision Describer](../CONTEXT.md) only describes; the Advisor makes the
[Tongue Assessment](../CONTEXT.md). Detection and crop run server-side in
a Roboflow workflow ([ADR 0004](adr/0004-serverless-workflow-crop.md));
the confidence gate stays in app code.
Every returned crop -- gate-passed or not -- is persisted as a
[Tongue Photo](../CONTEXT.md) in the standalone `tongue_photos` collection
([ADR 0007](adr/0007-tongue-photo-dataset-and-echo.md)), outside the memory
lifecycle. Gate-passed crops are echoed back beside the Assessment as a LINE
ImageMessage (Quick Reply rides on the image); the URL is a self-hosted
capability URL, `GET /tongue-photos/{photo_id}`, and delivery degrades one
rung at a time down to plain text -- the image never costs the user their
Assessment.
No detected tongue → retake
guidance, never an Assessment, and the turn is not recorded. A detector
or describer *failure* (outage, timeout) instead sends a Thai
system-hiccup message — an outage is never presented as a bad photo.

**Consultation close** — lazy, inside webhook handling: when a message
arrives after a >6 h gap (config default), the stale buffer meets the
[Relevance Gate](../CONTEXT.md)
([ADR 0002](adr/0002-health-record-only-memory.md)). Health content →
a [Health Record](../CONTEXT.md) entry is written, then the
[Profile Updater](../CONTEXT.md) folds that entry into the
[Health Profile](../CONTEXT.md) as item-level patches — adding, updating,
or clearing items such as [Ongoing Complaints](../CONTEXT.md)
([ADR 0003](adr/0003-health-profile-projection.md)).
No health content → everything is discarded and the Health Profile is
untouched. This is the only write path to long-term memory. The Advisor
has no write tools — its only tools are the two read-only record tools.
