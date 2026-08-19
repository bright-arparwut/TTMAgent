# Spike results — LightRAG `naive` vs `mix` on `four-elements`

Ticket #16 · map #9 · branch `spike/lightrag-naive-vs-mix`

## 1. The graph

- **Entities**: 288
- **Relations**: 403
- **Relations per entity**: 1.4
- **Isolated (degree 0)**: 14

| Entity type | Count |
| --- | ---: |
| concept | 149 |
| naturalobject | 37 |
| method | 21 |
| person | 20 |
| location | 19 |
| artifact | 19 |
| event | 8 |
| creature | 6 |
| content | 5 |
| other | 2 |
| data | 1 |
| organization | 1 |

**Most connected entities**

| Entity | Type | Degree |
| --- | --- | ---: |
| ธาตุทั้งสี่ | concept | 26 |
| โหราศาสตร์ | concept | 26 |
| การบำบัดด้วยธาตุทั้งสี่ | method | 22 |
| ธรรมชาติ | concept | 22 |
| ดวงชะตากำเนิด | concept | 15 |
| ราศีสิงห์ | concept | 14 |
| สิบสองราศี | concept | 14 |
| วิธีการให้น้ำหนัก | method | 12 |
| ดวงดาว | naturalobject | 11 |
| ดวงอาทิตย์ | naturalobject | 11 |
| โรคในปัจจุบัน | concept | 11 |
| ธาตุดิน | concept | 10 |
| ธาตุไฟ | concept | 10 |
| พลังชีวิต | concept | 10 |
| คุณภาพของชีวิต | concept | 9 |

## 2. Thai entity consistency

22 pair(s) above the 0.82 character-similarity threshold. **Most are false positives** — Thai compounds that share a prefix but mean opposite things. See caveat 4 before reading this as fragmentation:

| Similarity | A | B |
| ---: | --- | --- |
| 0.909 | Macrocosmos | Microcosmos |
| 0.897 | สังคมปัจจุบัน | สังคมโลกปัจจุบัน |
| 0.875 | ธาตุดินที่อ่อนไป | ธาตุน้ำที่อ่อนไป |
| 0.87 | นักโหราศาสตร์ | โหราศาสตร์ |
| 0.867 | ธาตุดินที่มากไป | ธาตุน้ำที่มากไป |
| 0.867 | ธาตุลมที่อ่อนไป | ธาตุไฟที่อ่อนไป |
| 0.857 | จรราศี | จักรราศี |
| 0.857 | ชาวตะวันตก | ชาวตะวันออก |
| 0.857 | ธาตุดินที่พอดี | ธาตุน้ำที่พอดี |
| 0.857 | ธาตุลมที่มากไป | ธาตุไฟที่มากไป |
| 0.857 | โลกตะวันตก | โลกตะวันออก |
| 0.846 | ธาตุลมที่พอดี | ธาตุไฟที่พอดี |
| 0.839 | ธาตุดินที่อ่อนไป | ธาตุลมที่อ่อนไป |
| 0.839 | ธาตุดินที่อ่อนไป | ธาตุไฟที่อ่อนไป |
| 0.839 | ธาตุน้ำที่อ่อนไป | ธาตุลมที่อ่อนไป |
| 0.839 | ธาตุน้ำที่อ่อนไป | ธาตุไฟที่อ่อนไป |
| 0.828 | ธาตุดินที่มากไป | ธาตุลมที่มากไป |
| 0.828 | ธาตุดินที่มากไป | ธาตุไฟที่มากไป |
| 0.828 | ธาตุน้ำที่มากไป | ธาตุลมที่มากไป |
| 0.828 | ธาตุน้ำที่มากไป | ธาตุไฟที่มากไป |
| 0.824 | ดวงอาทิตย์ | อาทิตย์ |
| 0.824 | อาทิตย์ | แสงอาทิตย์ |

## 3. `naive` vs `mix` — section recall

> **Read this metric with care.** The whole corpus is **28 chunks**, and `naive` returns **20** of them on every question — 71% of the book. Section recall is therefore close to saturated for both modes, and the near-tie below is a property of a 39-page corpus, not evidence that the graph adds nothing. See Caveats.

| Question set | `naive` | `mix` |
| --- | --- | --- |
| All 10 | ██████████ 97% | ██████████ 100% |
| Multi-hop only | █████████░ 92% | ██████████ 100% |

- `mix` better on: Q06
- `naive` better on: —
- Tied: Q01, Q02, Q03, Q04, Q05, Q07, Q08, Q09, Q10

### Per question

| Q | hops | needs | `naive` found | `mix` found | winner |
| --- | ---: | --- | --- | --- | --- |
| Q01 | 1 | 04 | 04 (100%) | 04 (100%) | = |
| Q02 | 1 | 18 | 18 (100%) | 18 (100%) | = |
| Q03 | 1 | 18 | 18 (100%) | 18 (100%) | = |
| Q04 | 1 | 15 | 15 (100%) | 15 (100%) | = |
| Q05 | 1 | 16 | 16 (100%) | 16 (100%) | = |
| Q06 | 3 | 15,16,18 | 16,18 (67%) | 15,16,18 (100%) | mix |
| Q07 | 2 | 16,18 | 16,18 (100%) | 16,18 (100%) | = |
| Q08 | 2 | 16,17 | 16,17 (100%) | 16,17 (100%) | = |
| Q09 | 1 | 04 | 04 (100%) | 04 (100%) | = |
| Q10 | 2 | 15,18 | 15,18 (100%) | 15,18 (100%) | = |

### Where the winning evidence came from

For each multi-hop question: which sections arrived as **chunks** (flat retrieval could find these) versus as **relations** (only the graph supplies these).

| Q | mode | via chunks | via relations | recall |
| --- | --- | ---: | ---: | ---: |
| Q06 | `naive` | 15 | 0 | 67% |
| Q06 | `mix` | 11 | 17 | 100% |
| Q07 | `naive` | 14 | 0 | 100% |
| Q07 | `mix` | 14 | 14 | 100% |
| Q08 | `naive` | 15 | 0 | 100% |
| Q08 | `mix` | 13 | 16 | 100% |
| Q10 | `naive` | 14 | 0 | 100% |
| Q10 | `mix` | 13 | 16 | 100% |

## 4. Provenance

Can the `(อ้างอิง: …)` footer be built from what came back? Via `aquery_data`, yes:

| mode | questions with a resolving reference list | mean references |
| --- | ---: | ---: |
| `naive` | 10/10 | 14.4 |
| `mix` | 10/10 | 12.4 |

Every reference carries a `file_path`, and ticket #12 made that filename the citation — so the footer is buildable. But **only through `aquery_data`**; see caveat 5.

## 5. Caveats — read before quoting any number above

1. **The corpus is too small for this comparison to discriminate.** 28 chunks total; `naive` top-k returns 20 of them. Flat retrieval is handing over most of the book on every question, so both modes score near 100% and the headline near-tie is an artifact of corpus size. This answers the map's open question *'whether 42.5k tokens is enough graph to differentiate the two modes'* — **it is not.** A defensible thesis comparison needs book two, or a top-k tuned well below corpus size.
2. **The decisive result is n=1.** Only Q06 separated the modes. It separated them in exactly the predicted way, but one question is an illustration, not evidence.
3. **This measures retrieval, not answers.** No generation, no judge, no gold answers. `mix` finding the right section does not prove the Advisor writes a better reply from it. That is the map's *Thesis evaluation design* fog, still unresolved.
4. **The near-duplicate detector over-reports.** Of the pairs in section 2, most are semantically *opposite* concepts that share a Thai prefix — `ธาตุดินที่มากไป` vs `ธาตุน้ำที่มากไป` are different elements, not spelling variants. Character-similarity is the wrong tool for Thai compounds. Genuine duplicates were few: `จรราศี`/`จักรราศี` and `สังคมปัจจุบัน`/`สังคมโลกปัจจุบัน`.
5. **`only_need_context=True` does not carry provenance.** It returns bare `reference_id`s with no id→file_path map, and `include_references=True` does not change that. `aquery_data` does return the map. Ticket #13's design stands, but the seam must call **`aquery_data`**, not `aquery(only_need_context=True)`.
6. **LightRAG basenames `file_path`.** The directory does not survive indexing. Ticket #12's *'the filename IS the citation'* holds; nothing may depend on the path around it.

## 6. EXTRACT backend cost (Claude Code headless)

| Metric | Value |
| --- | ---: |
| calls | 50 |
| failures | 0 |
| cost_usd | 4.2671 |
| wall_seconds_summed | 1400.8 |
| cache_creation_tokens | 319643 |
| cache_read_tokens | 1084547 |
| output_tokens | 134907 |
