# Topic Menu via delimiter block in the reply text, not structured output

Advisor replies were unbounded prose — a full element or tongue explanation in one message — which on a phone means heavy scrolling and no natural opening for the user to steer. We decided every reply is capped to one screen (one main point, 4–5 short sentences) and leftover content is offered as a **Topic Menu**: follow-up topics rendered as LINE Quick Reply buttons. The Advisor emits the menu by **ending its plain-text reply with a marked delimiter block** (a `[หัวข้อ]` section listing topics) that the pipeline parses out and converts to Quick Reply items — rather than forcing the final answer through LangGraph's `response_format` structured output.

## Why

- The Advisor Model is a **swappable slot** (CONTEXT.md): any sufficiently Thai-capable model may fill it, and structured-output reliability varies sharply across candidates (Typhoon vs Gemini vs Claude). A text convention works on anything that can follow a prompt.
- `response_format` on the prebuilt ReAct agent adds an extra LLM call after the tool loop — latency and cost on **every** turn, paid even when there is no menu.
- The delimiter degrades safely: if the parser finds no block, the whole text is sent as before. A malformed structured response would instead need error handling on every turn.
- Parsing is forgiving by design (accepts `-`, `•`, numbered items), and hard limits live in code, not the prompt: at most 5 topics, labels ≤ 20 characters (LINE's Quick Reply cap is 13 items / 20-char labels).

## Consequences

- The delimiter format is a **contract between the system prompt and the parser**; changing either side alone breaks the menu (silently — replies fall back to full text). Prompt and parser must be tested together.
- Topics stay in the advisor turn stored in the Working Buffer, so the Advisor understands "ข้อสอง" even after LINE has hidden the buttons (they disappear on the next message).
- Intake items from the Health Profile's missing-information list may appear as menu buttons, making that intake user-initiated; the in-body rule stays at one woven intake question. Red-flag escalations carry no menu and are exempt from the length cap.
- If a future Advisor Model proves reliably structured-output-capable and the slot stops being an experiment, revisiting `response_format` is cheap: only the parser boundary moves.
