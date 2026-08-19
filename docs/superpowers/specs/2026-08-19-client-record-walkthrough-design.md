# Design: Client Record walkthrough page

**Date:** 2026-08-19
**Status:** Approved by owner (this doc records the design agreed in conversation)

## Goal

A presentation page that shows how this project records a client and their
conditions, by following one client across four consultations and watching the
แฟ้ม (face sheet) fill in.

Built for a live thesis presentation: the presenter steps through the four
consultations while the audience watches the Health Profile change.

Deliverables:

- `docs/client-record-walkthrough.html` — the page
- `scripts/build_client_record_demo.py` — generates the page's data using the
  real `apply_patch()` and `render_profile()`
- `tests/test_client_record_demo.py` — asserts the page is not stale

## Naming note

There is no "Client Record" object in the codebase. The presentation terms map
onto existing domain concepts:

| Presentation term | Code | Defined in |
|---|---|---|
| Client record ("folder") | `HealthProfile` | `app/models/profile.py` |
| Condition record | `ongoing_complaints` + each `HealthRecordEntry` | `app/models/profile.py`, `app/models/schemas.py` |

The "folder" framing is already in the code: `render_profile()` emits
`"ยังไม่มีข้อมูลในแฟ้มผู้ใช้รายนี้"` for an empty profile. The page uses
**แฟ้มผู้รับบริการ · Client Record** as its heading and does not introduce a new
domain term into `CONTEXT.md`.

## Non-goals

- No new ADR. The page *documents* ADR 0003; it decides nothing.
- No new domain vocabulary in `CONTEXT.md`.
- No live Mongo, no LINE traffic, no network calls at view time.
- Not a duplicate of `docs/message-flow.html`: that page answers "who decides
  what"; this one answers "what gets written down, and how it accumulates".

## Language

Thai narrative, English structure. Headings, pane labels, field names, and op
names stay in English (they are code identifiers); explanatory prose, section
labels, and all example client data are in Thai, since that is what the system
actually stores and renders.

## The worked example

Synthetic client `Uc4f9…e21`: หญิง, born 14 มี.ค. 2541 → month 3 → **ธาตุไฟ**
(`app/memory/element.py`), อายุ 28. The arc is นอนไม่หลับ, already the Ongoing
Complaint example in `CONTEXT.md`.

| # | Date | What happens | Ops applied |
|---|---|---|---|
| 1 | 2 พ.ค. 2026 | First contact, แฟ้มว่าง. นอนไม่หลับ 2 สัปดาห์ ตื่นตี 3. Advisor asks วันเกิด/เพศ, prompted by the `ข้อมูลที่ยังขาด` line the renderer emits. Mentions กาแฟ 3 แก้ว/วัน | `set_birth_date` · `set_sex` · `add` habits → **h1** · `add` ongoing_complaints → **o1** |
| 2 | 20 พ.ค. 2026 | Sends a tongue photo. The only entry with `tongue` populated. แพ้กุ้ง surfaces while discussing diet | `add` allergies → **a1** · `update` **o1** |
| 3 | 15 มิ.ย. 2026 | Meme + weather chat. **Relevance Gate fails** → Working Buffer deleted, no entry written, profile untouched | *(none)* |
| 4 | 8 ก.ค. 2026 | หลับได้ตลอดคืนแล้ว. Mentions ไมเกรนตั้งแต่เด็ก and พาราเซตามอลเวลาปวดหัว | `remove` **o1** · `update` **h1** · `add` chronic_conditions → **c1** · `add` medications → **m1** |

Item IDs use the real prefixes from `app/memory/health_profile.py`:
`c` chronic_conditions, `a` allergies, `m` medications, `h` habits,
`o` ongoing_complaints.

### Why these four

- Together they exercise every `ProfileOp` type the code supports:
  `set_sex`, `set_birth_date`, `add`, `update`, `remove`.
- **#3 is load-bearing.** It is the only way to show why the แฟ้ม stays as clean
  as a doctor's chart — one consultation that produces nothing at all. Without
  it the Relevance Gate is just a box on a diagram.
- **#4 proves the ID invariant.** `o1` is removed, but
  `id_counters["ongoing_complaints"]` stays at 1, so the next complaint is `o2`
  — a removed ID is never reused.
- The arc **resolves** rather than staying open, because `remove` is otherwise
  unreachable in a four-step story.
- The tongue photo lands at #2, not #1, so the audience sees the empty แฟ้ม fill
  from text before a second input type arrives.

## Page structure

Each state renders the ADR 0003 invariant literally — the Profile Updater's
input is always *(current profile + one entry)*, never the transcript:

```
[ profile before ]  +  [ record entry ]  →  [ ops ]  →  [ profile after ]
```

Two panes with a ribbon between them, collapsing to one column under 900px
(same breakpoint idiom as `message-flow.html`):

- **Left — "The Consultation".** LINE-style Thai chat bubbles, a divider reading
  `ปิด Consultation (เงียบเกิน 6 ชม.)`, the Relevance Gate verdict badge, then
  the resulting `HealthRecordEntry` as a field-labelled card. Consultation 2's
  card expands the nested `TongueAssessment` → `TongueDescription`.
- **Middle — the ops ribbon.** A narrow vertical strip listing the `ProfileOp`s
  applied at this close, arrow pointing right. Becomes a horizontal band when
  the layout stacks.
- **Right — "แฟ้มผู้รับบริการ · Client Record".** The face sheet in the
  renderer's own section order (`app/memory/profile_render.py`): โรคประจำตัว,
  ประวัติแพ้, ยา/สมุนไพรที่ใช้ประจำ, พฤติกรรม, อาการที่ติดตามอยู่. Each item
  carries its `[id]` chip and `บันทึก <date>`.
- **Bottom strip — "What the Advisor reads next turn".** The literal
  `render_profile()` output in monospace, `ข้อมูลที่ยังขาด` line included. The
  payoff shot: the entire right pane collapses into the few lines that actually
  enter the prompt.

### Marking changes

`message-flow.html` has already spent blue / amber / purple on
deterministic / LLM-scored / agentic. Reusing those hues here would imply a
claim this page is not making, so change-type is carried by **glyph + rule
style** rather than hue:

| Change | Mark |
|---|---|
| added | `+`, solid green left rule |
| updated | `±`, dashed grey left rule |
| removed | `−`, struck through in red, shown one step before disappearing |

Legible on a bad projector and colourblind-safe.

### Interaction

Four buttons — `1 · 2 พ.ค.`, `2 · 20 พ.ค. 📷`, `3 · 15 มิ.ย. ✕`, `4 · 8 ก.ค.` —
plus ← / → arrow keys for presenting. No auto-advance.

Consultation 3 dims the right pane under a `แฟ้มไม่เปลี่ยนแปลง` overlay and
replaces the entry card with the gate's `has_health_content: false`.

Single self-contained file: all state in one inlined JS data array, no fetch, no
external assets, palette tokens copied from `message-flow.html`. Works from
`file://` and stays publishable as an Artifact.

## Data provenance

**The client is synthetic, and the page says so.** A line in the standfirst
reads: ข้อมูลผู้รับบริการในหน้านี้เป็นตัวอย่างสมมติ ไม่ใช่ข้อมูลผู้ใช้จริง.
There are no consented real client records, and a committee should not have to
guess which it is looking at.

**The rendering, however, is real.** `scripts/build_client_record_demo.py`
defines the four entries and their ops in Python, runs the *real*
`apply_patch()` and `render_profile()` over them, and injects the resulting JSON
into the HTML between `<!-- DATA:BEGIN -->` / `<!-- DATA:END -->` markers.

The injected block covers, per state: the profile before and after, the ops
applied, the `HealthRecordEntry`, and the `render_profile()` output. The chat
bubbles are authored narrative — not code output — and ride along in the same
block for convenience. Consultation 3 still emits a state, with a null entry and
an empty op list.

**`today` is pinned, never `date.today()`.** `render_profile()` computes age and
therefore its output depends on the current date; each state renders with
`today` set to that consultation's own date. This is both more truthful — it is
what the Advisor actually read at the time — and deterministic, which the drift
test requires. A generator calling `date.today()` would fail the test on every
birthday boundary.

Chosen over hand-typing the strings because the bottom strip is exactly where
someone will probe — "is that actually what the system produces?" — and the
answer should be yes, that string came out of the function. Hand-authored HTML
around generated data keeps the design tunable without the generator clobbering
it.

Side benefit: the script is a working fixture builder. Pointing it at the
repositories instead of at JSON seeds a real demo client in Mongo, if a live
demo is ever wanted.

The generator drives `apply_patch()` with hand-authored op lists rather than
calling the Profile Updater's LLM, so the page is deterministic and needs no API
key. What is asserted is that the *projection and rendering* are the real code
path; op selection is authored, as it must be for a fixed narrative.

## Files

| File | What |
|---|---|
| `docs/client-record-walkthrough.html` | the page; hand-authored, data injected between markers |
| `scripts/build_client_record_demo.py` | four entries + ops → real `apply_patch`/`render_profile` → JSON |
| `tests/test_client_record_demo.py` | regenerating produces no diff |

No changes to `app/`. No new ADR. No `CONTEXT.md` change.

## Testing

One test: run the generator against the committed HTML and assert the injected
block is byte-identical to what regeneration produces. This fails the moment
`render_profile()`, the section labels, or the ID prefixes change — which is the
only drift that can make the page lie.

The generator itself adds no logic worth testing separately: it composes real
`apply_patch()` and `render_profile()`, both already covered by the existing
suite.
