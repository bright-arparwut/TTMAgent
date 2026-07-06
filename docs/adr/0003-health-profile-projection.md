# Health Profile: a deterministic projection of Health Record entries

We added a per-user **Health Profile** — a current-state face sheet (TTM identity, clinical background, lifestyle habits, Ongoing Complaints) sitting above the episodic Health Record the way a chart's face sheet sits above visit notes. The original idea was "give the agent a profile-update tool"; we decided instead that the profile has **no agent tools at all**. It is written by a **Profile Updater** that runs deterministically at Consultation close, only when the Relevance Gate passes, consuming exactly *(current profile + the Health Record entry just written)* and emitting item-level patches against stable item IDs. The whole profile is auto-injected into every Advisor turn.

## Why

- Consultation close is lazy (stale-buffer check when the *next* message arrives — ADR 0002), so no agent is running at the moment of close: an "agent updates the profile before close" tool is mechanically impossible. The deterministic close step is the only honest home for the write, and it reuses the Relevance Gate's pattern — LLM-scored, code-triggered. ADR 0002's no-write-tools stance is preserved, not reversed.
- Making the updater consume the **entry** (not the raw transcript) turns the profile into a pure projection of the Health Record: close-time update and historical backfill are the same code path, and the profile is rebuildable at any time by replaying a user's entries — a bad patch is recoverable. Invariant: nothing reaches the Profile that isn't in the Record; if a detail matters enough for the profile, enrich the entry schema rather than bypass it.
- **Patches with stable item IDs** beat whole-document rewrites: facts the updater doesn't mention survive by construction (no silently vanished allergy), and a patch referencing an unknown ID fails loudly instead of matching fuzzily.
- ธาตุเจ้าเรือน is **code-derived from birth date** via the corpus's month→element mapping; the patchable fact is the birth date. Computable facts stay out of the model, consistent with the deterministic-where-computable architecture (ADR 0001).
- Applied patches are logged with timestamps and source-entry provenance (per-item `noted_at`), giving chart-style auditability and material for thesis analysis.

## Considered options

- **Agent write tool (`update_patient_profile`)** — rejected: reverses ADR 0002, depends on the stack's weakest tool-caller remembering to save, and doesn't match the close timing anyway.
- **Whole-document rewrite at close** — rejected: a single forgetful rewrite silently drops safety-critical facts (allergies, chronic conditions).
- **Updater reads raw transcript at close** — rejected: higher fidelity, but the profile stops being rebuildable and backfill becomes a second, degraded path.

## Consequences

- The memory-ablation experiment gains an arm — (a) no memory, (b) Health Record only, (c) Record + Profile — instead of being invalidated. The profile must be config-switchable (skip updater + skip injection) from day one.
- Cold start is handled by prompting, not machinery: injected context lists which face-sheet fields are missing, and the Advisor weaves in one intake question when natural (e.g. birth date before an element-based Assessment).
- Profile quality is bounded by entry quality: anything the close-time summarizer drops can never reach the profile.
