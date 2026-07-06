# Two-model pipeline: config-selected Advisor + separate Vision Describer

The obvious design is one frontier multimodal model (GPT-4o/Claude/Gemini) handling chat, tongue images, and tool calling. We deliberately split it into two independent, config-selected slots: an **Advisor Model** that conducts the Consultation, reasons over the TTM corpus, and calls Health Record read tools; and a separate **Vision Describer** that only converts a cropped tongue photo into a structured **Tongue Description** — it observes, never assesses. Neither slot has a fixed model tied to the architecture — Typhoon, GPT, Claude, and Gemini are all valid choices for either slot, selected via config, not code. The seam between them is a fixed JSON schema derived from the TTM book's tongue-inspection categories, so either slot can be swapped without changing the other.

## Why

- Thai-language quality is the product; keeping the Advisor Model a config choice lets a Thai-specialized model (e.g. Typhoon) be evaluated against frontier general models as a genuine experiment, not a hardcoded assumption.
- The structured schema makes the two stages *separately evaluable* — describer accuracy vs. assessment quality — which answers "where does the error come from?" in the evaluation chapter.
- Both slots are LangChain-abstracted config choices, so swapping either one (e.g. because a chosen Advisor Model proves an unreliable tool-caller) is a config edit, not a rewrite.

## Consequences

- No model is architecturally load-bearing; whichever model is configured as Advisor carries the tool-calling reliability risk for that deployment — mitigated by the config-level escape hatch.
- Every tongue turn costs two model calls (Describer + Advisor) instead of one.
