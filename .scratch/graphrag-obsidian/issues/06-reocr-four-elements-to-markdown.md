# 06 — Re-OCR four-elements (39pp) to Markdown

Status: ready-for-agent
Type: wayfinder:task
Map: ../MAP.md
Blocked by: 03

## Question

Nothing to decide — this is the manual work the spike cannot start without.

Transcribe `วิถีแห่งธรรมชาติกับธาตุทั้งสี่` (อนุสรณ์ วรมงคล, 39 PDF pages,
printed pages 12–43) into the Markdown format decided in ticket 03.

Source PDF: the owner's Google Drive, `วิถีธรรมชาติกับธาตุทั้งสี่.pdf`
(39 MB, file id `1qI9ZZ5iY5DvYGpXLFTfv1rs_EhamRfB4`). Fetch a local copy first —
do not depend on Drive at build time.

Prior art to reuse, not repeat: `docs/superpowers/plans/2026-07-30-two-book-corpus-digitization.md`
already describes the working pipeline — render pages to JPEG, fan out transcription
sub-agents, then an **independent verify pass** against the same images. That
verify pass is what made the existing transcription trustworthy; keep it.

Output lands in the vault's `sources/` folder, inside the repo. The corpus is
copyrighted — it must not be written anywhere that syncs off-machine.

Done when: every printed page 12–43 is represented, the ticket 03 validator passes,
and a spot-check against the scan confirms no fabricated or dropped paragraphs.

## Why it matters

The spike (07) has no corpus without it. Also the first real test of whether the
ticket 03 format survives contact with an actual book.

## Comments
