# Citations rendered as a Flex footer, via a second delimiter contract

The Advisor's trailing `(อ้างอิง: ...)` line (ADR 0008) is no longer sent as plain text. The LINE transport parses it out (`app/advisor/citation.py`) and re-renders the reply as a **Flex Message**: the answer in the bubble body, then a separator, then the citation in small grey type with a 📖 prefix (`build_citation_message`). Replies without a citation stay plain `TextMessage`s. The Topic Menu Quick Reply attaches to the Flex bubble exactly as it did to the text message.

## Why

- **LINE plain text has no styling** — no markdown, no small/grey type. A Flex bubble is the only way to make the source read as a footnote instead of part of the answer.
- **Same mechanism as ADR 0006, deliberately.** The citation line is a prompt-taught text convention parsed at the transport boundary, not structured output — it works on any Advisor Model slot, degrades to inline text when absent or malformed, and the Working Buffer keeps the raw reply (citation inline) so the Advisor sees its own citations in history.
- **Prompt orders the line before the `[หัวข้อ]` block**, so the topic-menu split leaves the citation at the tail of `visible_text` where `split_citation` finds it. Defense in depth: `_parse_topics` skips citation-shaped lines, so a model that misorders them cannot turn its citation into a truncated Quick Reply button.
- **The degrade chain sheds styling, never the source.** `reply_or_push` extends the ADR 0007 ladder: reply [flex, image+topics] → push [flex, image+topics] → push [flex+topics] → push plain text **with the citation folded back inline** (`inline_citation`). A Flex payload LINE rejects costs the footer, not the provenance.
- **altText is the text body** (truncated to LINE's 400-char cap): notifications and the chat list can't render Flex, and the answer — not the citation — is what belongs in a preview.

## Consequences

- Two delimiter contracts now ride on the same reply: `(อ้างอิง: ...)` then `[หัวข้อ]`. Each has a prompt-side contract test (`test_prompt_citation_contract.py`, `test_prompt_topic_menu_contract.py`); changing a prompt format without its parser breaks that footer/menu silently.
- Flex bubbles are not copyable as one long-press in some LINE clients the way plain text is; accepted for the styling gain (the altText and degrade path keep the plain-text form reachable).
- `scripts/chat.py` and any non-LINE transport see the citation inline in the reply text — correct and unstyled by design.
