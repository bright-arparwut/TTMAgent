# Working Buffer replay for within-Consultation memory, no LangGraph checkpointer

The Advisor was originally invoked statelessly — one `HumanMessage` per turn — which meant it could not follow the conversation it was itself having ("I have a headache" → "how long will it heal?" drew a blank). We decided the deterministic spine **replays the open Consultation's Working Buffer turns to the Advisor as structured message history** (user → `HumanMessage`, advisor → `AIMessage`, capped at the last N turns by config), rather than adopting LangGraph checkpointing (e.g. `MongoDBSaver`).

## Why

- The Working Buffer **already holds exactly these turns** for the Relevance Gate; a checkpointer would duplicate the same conversation in a second store with its own lifecycle.
- Checkpointer threads don't match Consultation semantics: the buffer is *deleted* at lazy gap-close (ADR 0002), and there is no natural checkpointer analogue of "summarize then discard."
- Replay is code-driven: the spine reads the buffer and hands history to the Advisor. The Advisor gains no new tool and no say — the agentic surface is unchanged.
- The retrieved context block (Health Profile + record summaries + RAG passages) is attached to the **current message only**, so exactly one authoritative context render exists per call; replayed turns are raw stored text.

## Consequences

- Tool-call traces are not replayed across turns (the buffer stores only user/advisor text). Fine for read-only record tools; would need revisiting if tools ever became stateful.
- History is loaded *before* the incoming turn is appended, so a turn whose Advisor call fails is still replayed on the user's next message.
- The history cap is tunable config beside `consultation_gap_hours`, not architecture.
