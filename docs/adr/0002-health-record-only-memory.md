# Health-Record-only memory: lazy gap-close summarization, no LLM write tools

The original plan was "save conversation history in MongoDB and give the LLM CRUD tools." We decided instead that the **Health Record** (doctor's-notes-style structured entries, one per clinically relevant Consultation) is the *only* persistent memory — raw transcripts are never stored long-term. Raw turns live in a working buffer; a Consultation closes lazily when the user's next message arrives after a >6-hour inactivity gap; at close, a summarization call applies the **Relevance Gate** (memes/greetings/off-topic → discarded, no entry) and writes the structured entry (chief complaint, symptoms, Tongue Assessment, advice, conversation summary). The Advisor gets the last ~3 entries **auto-injected** at Consultation start plus two **read-only** tools (`search_health_records`, `get_health_record_by_date`). It has no write/update/delete tools.

## Why

- Mirrors how a doctor actually works: structured chart notes consulted at the next visit, not verbatim transcripts stuffed into context (which degrades and doesn't scale).
- Lazy gap-close needs no cron/scheduler — everything happens inside webhook handling — and naturally handles users who leave mid-conversation (the buffer is summarized whenever they return; if they never return, an unsummarized buffer is harmless).
- Deterministic writes: record integrity never depends on the LLM remembering to call `save()`. This matters doubly because the Advisor (Typhoon) is the weakest tool-caller in the stack.
- Auto-injection guarantees continuity even on turns where the model calls no tools; the read tools cover reaching beyond the recent entries.

## Consequences

- The memory design (auto-inject + structured record vs. raw transcript) is the thesis's memory-ablation experiment — changing it invalidates that evaluation.
- Word-for-word recall of old conversations is impossible by design; only what the summarizer captured survives.
- Consultation boundary constants (6-hour gap) and injection count (last 3 entries) are tunable config, not architecture.
