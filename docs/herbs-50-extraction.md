# Extracting book three to repaired text

How `แนวทางการใช้ยาสมุนไพรในการดูแลอาการเจ็บป่วยเบื้องต้น` (book three) is read off its
PDF, and what the extraction found. Ticket
[#60](https://github.com/bright-arparwut/TTMAgent/issues/60) on map
[#45](https://github.com/bright-arparwut/TTMAgent/issues/45), implementing the route
[#46](https://github.com/bright-arparwut/TTMAgent/issues/46) established.

**This is the extraction stage only.** It does not decide note grain
([#50](https://github.com/bright-arparwut/TTMAgent/issues/50)), does not cut source
notes, and does not ingest. The deliverable is repaired text plus a structural index.

## Reproducing it

`pdftotext` comes from poppler (`apt-get install poppler-utils`; measured on 24.02.0).

```
uv run python -m scripts.extract_herbs_book book3.pdf
```

Whole book, 206 pages: **0.9 s, $0.00, zero LLM calls.** It is a pure function of the
PDF, so it can be re-run in CI and diffed — re-running it twice gives byte-identical
output. That reviewability is the reason the text route beats vision here even where
vision is free (#19's `claude -p` backend), quite apart from #46's $21.46 API pricing.

## The defect, and why it is repairable

The PDF is born-digital (`Adobe InDesign 20.4 (Macintosh)`, 2025-07-14) with an intact
text layer. Two mechanical, fully deterministic encoding defects:

1. Every Thai above/below vowel, tone mark and SARA AM is emitted **twice** — never
   tripled.
2. A stacked vowel+tone pair emits one extra positioning glyph with no `ToUnicode`
   entry (poppler spells it `U+FFFD`, PyMuPDF `U+02E0`/`U+02E3`).

Nothing was lost; it was doubled. `scripts/thairepair.py` inverts both. Order matters:
the stacking glyph is identified by the doubled mark in front of it, so it must be
dropped *before* the doubles are collapsed.

**Never strip `U+FFFD` blindly.** Exactly 3 in the whole book are real characters the
font failed to map, and they are left standing for a human to adjudicate:

| as extracted | reads | where |
| --- | --- | --- |
| `1. ค�นหาสาเหตุ` | `ค้นหาสาเหตุ` | symptom index |
| `รวม 5 กร�ม` | `กรัม` | symptom index |
| `แก้ไอ แก้ร�อนใน` | `แก้ร้อนใน` | symptom index |

## Validation

`scripts/thairepair.py --report`, whole book:

| check | raw | repaired |
| --- | --- | --- |
| characters | 450,777 | 396,331 |
| residual doubled marks | 45,837 | **0** |
| illegal above-mark pairs | 39,292 | **0** |
| orphan combining marks | — | **1** in 396k |
| `U+FFFD` | 8,612 | **3** (flagged, not deleted) |

"Illegal above-mark pair" means two consecutive above-marks other than the one legal
stack (an above-vowel carrying a tone mark). The single orphan is a line-break artifact
(`ช\nุมนุมสหกรณ์` in a bibliography entry), not a decoding failure.

Independent corroboration of the same text is in #46: PyThaiNLP in-dictionary rate
**58.18% → 96.63%**, and a Tesseract `tha` cross-read agreeing 86–90% on prose pages.

## What is produced

### `corpus/herbs-50.jsonl`

ADR 0008's record format, so it sits alongside `corpus/four-elements.jsonl`:

```json
{"book_id": "herbs-50",
 "book_title": "แนวทางการใช้ยาสมุนไพรในการดูแลอาการเจ็บป่วยเบื้องต้น",
 "page": 37, "pdf_page": 45, "paragraph": 1,
 "text": "1. ชื่อวิทยาศาสตร์ : Boesenbergia rotunda (L.) Mansf. …"}
```

202 records (4 blank pages skipped). Printed folio = `pdf_page − 8`.

Two deliberate deviations, both because this is extraction and not transcription:

- **`paragraph` is always `1` — this is page-granular, not paragraph-granular.**
  `pdftotext -raw` hard-wraps lines and exposes almost no paragraph structure (12 of
  206 pages carry a blank-line break), so any finer split would be a grain decision
  wearing an extraction costume. The page is the smallest unit the source gives us.
- **Page furniture is kept** — running title, folio and the `N. <herb>` header stay in
  the text. Dropping them is a transcription decision.

`herbs-50` is #46's *proposed* `book_id`, not a settled one. It is deliberately a
root-level `.jsonl` rather than a `corpus/<book_id>/` folder, so it needs no
`books.yaml` entry and binds nothing: `app/preflight.py:check_corpus_books` covers
folders only. Renaming later is a `git mv` plus one line.

### `corpus/herbs-50-structure.json`

The structural index later tickets need: `validation`, `unmapped_context`, plus

- `monographs[]` — 50 entries: `ordinal`, `name`, `latin`, `synonym`, `family`,
  `common`, `local`, `pages`, `pdf_pages`, `has_prohibited`, `has_warning`,
  `has_caution`.
- `symptom_sections[]` — 34 entries: `group`, `group_title`, `number`, `title`,
  `herbs[]`.

## What the extraction found

**Confirming #46:** 50 monographs, printed pp.34–196 (PDF 42–204); 34 symptom sections
over printed pp.1–31 in the 11/4/1/11/3/4 split across six body systems; all nine
numbered fields appearing exactly 50 times; monograph spans of 2–8 pages with the
histogram 3×36, 4×6, 2×4, 5×3, 8×1. Boundaries are detected on the literal
`1. ชื่อวิทยาศาสตร์`, never on a page count — the 3-page stride breaks at the very first
boundary (herb 2 is 4 pages) and arithmetic never recovers.

### Three monographs lack `ข้อห้ามใช้`, not two — and one has no safety block at all

#46 inferred "two" from the book-wide count of 48 against 50 monographs. Segmenting the
book shows the count is 47 *inside* monographs; the 48th occurrence is on PDF p.4, in
the คำนำ's list of the book's own field structure. The same holds for the other two
labels, which reconciles all three counts exactly:

| label | in monographs | in คำนำ | book-wide |
| --- | --- | --- | --- |
| `ข้อห้ามใช้` | 47 | 1 | 48 |
| `คำเตือน` | 49 | 1 | 50 |
| `ข้อควรระวัง` | 50 | 1 | 51 |

The monographs with no `ข้อห้ามใช้` line:

| # | herb | scientific name | printed pp. | `ข้อห้ามใช้` | `คำเตือน` | `ข้อควรระวัง` |
| --- | --- | --- | --- | --- | --- | --- |
| 11 | ขลู่ | *Pluchea indica* (L.) Less. | 69–71 | **✗** | **✗** | **✗** |
| 12 | ข่อย | *Streblus asper* Lour. | 72–73 | **✗** | ✓ | ✓ |
| 13 | ข่า | *Alpinia galanga* (L.) Willd. | 74–78 | **✗** | ✓ | ✓ |

**ขลู่ carries no safety field whatsoever.** Its field 3 (`วิธีใช้`) gives a dose —
40–50 g fresh or 15–20 g dried, boiled, three times daily before meals — and then runs
straight into `4. ลักษณะพืช`. A Remedy Gate that assumes the fields are present fails
open on these three, and hardest on ขลู่, where there is nothing to load at all.

One monograph carries a duplicate: #45 มังคุด has two `ข้อควรระวัง` lines.

### ฟักทอง is unreachable from the symptom index

The 34 sections name 49 distinct herbs, and every one resolves to a monograph. The
50th, **#35 ฟักทอง**, is named nowhere in the symptom index — it appears in the
table of contents (PDF p.7) but has no symptom edge. Any retrieval path that reaches
herbs only through symptoms will never reach it.

### The symptom index is given twice

Printed pp.1–2 carry a compact `N.M <symptom> ได้แก่ <herbs>` overview; printed pp.3–31
expand each section with prose plus a `ลำดับ / ชื่อสมุนไพร / หน้า` table. The two are
independent and cross-validate: the table's page numbers agree with the monograph spans
detected from `1. ชื่อวิทยาศาสตร์` (e.g. `กระชาย 37` against monograph 2 at printed
37–40). Only the compact form is parsed into `symptom_sections[]`.

Herbs recur across symptoms — กระชาย appears under 1.1, 1.2 and 1.10 — so this layer is
natively graph-shaped, which is the raw material for the relation layer the map
describes.

### Every monograph carries all five name fields

All 50 have `ชื่อวิทยาศาสตร์`, `ชื่อพ้อง`, `ชื่อวงศ์`, `ชื่อสามัญ` and `ชื่อท้องถิ่น`
present, though `ชื่อพ้อง` is frequently the placeholder `-`. Treat `-` as absent.
