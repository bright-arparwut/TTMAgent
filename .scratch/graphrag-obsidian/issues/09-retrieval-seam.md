# 09 — The retrieval seam: mode, query, and where it fires

Status: ready-for-human
Type: wayfinder:grilling
Map: ../MAP.md
Blocked by: 07

## Question

How GraphRAG plugs into the turn, behind `app/pipeline/dispatcher.py:237`.

- **Query mode** — `mix` was the map's default, but the spike gives real evidence.
  Fixed mode, or chosen per turn (cheap `naive` for chit-chat, `mix` for a real TTM
  question)?
- **The query text.** Today retrieval fires on the **raw incoming user message**.
  That is the weakest link: LINE users write "ลิ้นเป็นฝ้าขาว นอนไม่หลับ ทำไงดี",
  which is not a good graph query. Does the query get rewritten or entity-extracted
  first, and by what?
- **Pre-fetch or tool?** Retrieval currently runs unconditionally every turn, before
  the Advisor sees anything. With a graph, letting the Advisor *call* retrieval as a
  LangGraph tool (it already has a tool loop in `app/advisor/graph.py`) would allow
  multi-hop follow-up queries — the thing graphs are for. Big change; worth it?
- **How much comes back.** `rag_top_k = 5` today. `mix` returns entities, relations
  and chunks — what is the budget, and how is it split?
- **Failure behaviour.** `retrieve_passages` currently returns `[]` when the store is
  missing, and the Advisor answers ungrounded. Is that still acceptable when the
  graph is the whole grounding story, or should a graph failure be a visible error?
- **Query-time LLM cost and latency (new).** The current system makes **zero** LLM
  calls to retrieve — dense similarity only. LightRAG fires `KEYWORDS` on every
  query and `QUERY` to write the answer. Even if the Advisor keeps writing the reply
  (so `QUERY` is unused), `KEYWORDS` adds an LLM round-trip before the Advisor
  starts, on every LINE message. Is that latency acceptable on a chat bot, and which
  model slot serves it? Note it cannot be Claude Code — a webhook cannot shell out
  to a CLI per request (see ticket 02).
- **Health Profile as a query input.** The user's ธาตุเจ้าเรือน is already known
  every turn. Does it enter the graph query, or stay prompt-only?

## Why it matters

Decides whether GraphRAG's multi-hop capability is actually reachable. A graph
queried once per turn with raw user text will underperform its potential, and the
thesis comparison would understate the result.

## Comments
