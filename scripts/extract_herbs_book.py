"""Extract book three to repaired page text plus a structural index.

Ticket #60 (map #45). Produces two files, both reproducible from the PDF:

- `corpus/herbs-50.jsonl` -- the repaired text, one record per page, in the same
  shape as `corpus/four-elements.jsonl`.
- `corpus/herbs-50-structure.json` -- the 50 monographs and 34 symptom sections,
  with page spans, name fields and which safety fields each monograph carries.

**This is the extraction stage only.** It does not decide note grain (#50), does
not cut source notes, and does not ingest. Two consequences of that scope:

- *One record per page, not per paragraph.* `pdftotext -raw` hard-wraps lines and
  exposes almost no paragraph structure (12 of 206 pages carry a blank-line break),
  so any finer split would be a grain decision wearing an extraction costume. The
  page is the smallest unit the source actually gives us.
- *Page furniture is kept.* The running title, folio and the `N. <herb>` header are
  left in the text. Dropping them is a transcription decision; `structure.json`
  records where they are so a later pass can strip them deliberately.

`herbs-50` is #46's proposed `book_id`, not a settled one -- #06/#07 own that. It is
deliberately a root-level `.jsonl` rather than a `corpus/<book_id>/` folder, so it
needs no `books.yaml` entry and binds nothing: `app/preflight.py:check_corpus_books`
covers folders only. Renaming later is a `git mv` plus one line.

Usage:

    python scripts/extract_herbs_book.py book3.pdf
"""

import argparse
import json
import re
from pathlib import Path

from scripts.thairepair import extract, repair, unmapped, validate

BOOK_ID = "herbs-50"
BOOK_TITLE = "แนวทางการใช้ยาสมุนไพรในการดูแลอาการเจ็บป่วยเบื้องต้น"

# printed folio = pdf page - PAGE_OFFSET. Printed p.1 = pdf p.9 (#46).
PAGE_OFFSET = 8
# The last page of book content; 205-206 are back matter.
LAST_CONTENT_PDF_PAGE = 204
# The symptom index's compact "N.M <symptom> ได้แก่ <herbs>" overview.
INDEX_PDF_PAGES = (9, 10)

RUNNING_TITLE = "แนวทางการใช้ยาสมุนไพร"
RUNNING_SUBTITLE = "ในการดูแลอาการเจ็บป่วยเบื้องต้น"

# The running title, its second line, a bare folio, and the two chapter headings.
# The last section on a page runs straight into these, so an unstripped herb list
# ends `[..., 'แนวทางการใช้ยาสมุนไพร', 'ในการดูแลอาการเจ็บป่วยเบื้องต้น', '2']`,
# and 3.1's ends with the chapter heading `บทนำ`.
CHAPTERS = ("บทนำ", "รายการพืชสมุนไพร")
FURNITURE_LINE_RE = re.compile(
    "^(?:" + "|".join((RUNNING_TITLE, RUNNING_SUBTITLE, *CHAPTERS, r"\d{1,3}")) + r")\s*$",
    re.M,
)

# Monograph boundaries are detected on this literal, never on a page count: the
# 3-page stride holds for 36 of 49 gaps and breaks at the very first boundary,
# so arithmetic desynchronises at herb 2 and never recovers (#46).
MONOGRAPH_RE = re.compile(r"1\.\s*ชื่อวิทยาศาสตร์\s*:?\s*(.*)")

# The herb's own name, from the page furniture: "11. ขลู่" immediately above the
# running title. Anchoring on the running title is what keeps this from matching
# the numbered field labels ("2. ส่วนที่ใช้", "3. วิธีใช้").
FURNITURE_RE = re.compile(rf"^(\d{{1,2}})\.[ \t]*(.+)\n{RUNNING_TITLE}", re.M)

PROHIBITED, WARNING, CAUTION = "ข้อห้ามใช้", "คำเตือน", "ข้อควรระวัง"

_NAME_FIELDS = {
    "synonym": "ชื่อพ้อง",
    "family": "ชื่อวงศ์",
    "common": "ชื่อสามัญ",
    "local": "ชื่อท้องถิ่น",
}


def split_pages(text: str) -> list[str]:
    """Form feeds, trimmed to the 206 real pages."""
    return text.split("\f")[:206]


def find_monograph_starts(pages: list[str]) -> list[int]:
    """1-based PDF page numbers where a monograph begins."""
    return [n for n, page in enumerate(pages, start=1) if MONOGRAPH_RE.search(page)]


def _field(text: str, label: str) -> str | None:
    match = re.search(re.escape(label) + r"\s*:\s*(.*)", text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def parse_monograph(text: str, ordinal: int, pdf_start: int, pdf_end: int) -> dict:
    name = None
    for found_ordinal, found_name in FURNITURE_RE.findall(text):
        if int(found_ordinal) == ordinal:
            name = found_name.strip()
            break
    latin = MONOGRAPH_RE.search(text)
    return {
        "ordinal": ordinal,
        "name": name,
        "latin": (latin.group(1).strip() or None) if latin else None,
        **{key: _field(text, label) for key, label in _NAME_FIELDS.items()},
        "pages": [pdf_start - PAGE_OFFSET, pdf_end - PAGE_OFFSET],
        "pdf_pages": [pdf_start, pdf_end],
        "has_prohibited": PROHIBITED in text,
        "has_warning": WARNING in text,
        "has_caution": CAUTION in text,
    }


def parse_monographs(pages: list[str]) -> list[dict]:
    starts = find_monograph_starts(pages)
    out = []
    for index, pdf_start in enumerate(starts):
        pdf_end = starts[index + 1] - 1 if index + 1 < len(starts) else LAST_CONTENT_PDF_PAGE
        body = "\f".join(pages[pdf_start - 1 : pdf_end])
        out.append(parse_monograph(body, index + 1, pdf_start, pdf_end))
    return out


def parse_symptom_index(pages: list[str], span: tuple[int, int] | None = None) -> list[dict]:
    """The compact overview on printed pp.1-2: six body-system groups, each with
    numbered symptom sections naming the herbs that treat it.

    Herbs recur across symptoms -- กระชาย appears under 1.1, 1.2 and 1.10 -- which
    is why the map calls the book natively graph-shaped. This is the raw material
    for that relation layer.

    `span` is an inclusive 1-based PDF page range, defaulting to the book's.
    """
    first, last = span or INDEX_PDF_PAGES
    text = FURNITURE_LINE_RE.sub("", "\n".join(pages[first - 1 : last]))
    groups: dict[int, str] = {}
    for number, title in re.findall(r"^(\d)\.[ \t]+(\S.*)$", text, re.M):
        groups.setdefault(int(number), title.strip())

    # A section runs until the next "N.M" or group heading; herb lists wrap lines.
    chunks = re.split(r"^(\d)\.(\d+)[ \t]+", text, flags=re.M)[1:]
    sections = []
    # re.split with two groups yields exact triples; strict= catches a malformed split.
    for group, number, body in zip(chunks[0::3], chunks[1::3], chunks[2::3], strict=True):
        body = re.split(r"^\d\.[ \t]+\S", body, flags=re.M)[0]
        body = " ".join(body.split())
        title, _, herbs = body.partition("ได้แก่")
        sections.append(
            {
                "group": int(group),
                "group_title": groups.get(int(group)),
                "number": f"{group}.{number}",
                "title": title.strip(),
                "herbs": [h for h in herbs.split() if h],
            }
        )
    return sections


def page_records(pages: list[str]) -> list[dict]:
    records = []
    for pdf_page, text in enumerate(pages, start=1):
        text = text.strip("\n")
        if not text.strip():
            continue
        records.append(
            {
                "book_id": BOOK_ID,
                "book_title": BOOK_TITLE,
                "page": pdf_page - PAGE_OFFSET,
                "pdf_page": pdf_page,
                "paragraph": 1,
                "text": text,
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path, help="the book PDF")
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    args = parser.parse_args(argv)

    raw = extract(args.pdf)
    text = repair(raw)
    pages = split_pages(text)

    monographs = parse_monographs(pages)
    sections = parse_symptom_index(pages)
    metrics = validate(text)

    records = page_records(pages)
    jsonl = args.corpus / f"{BOOK_ID}.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    structure = args.corpus / f"{BOOK_ID}-structure.json"
    structure.write_text(
        json.dumps(
            {
                "book_id": BOOK_ID,
                "book_title": BOOK_TITLE,
                "page_offset": PAGE_OFFSET,
                "validation": metrics,
                "unmapped_context": [text[offset - 25 : offset + 15] for offset in unmapped(text)],
                "monographs": monographs,
                "symptom_sections": sections,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    missing = [m for m in monographs if not m["has_prohibited"]]
    print(f"{jsonl}: {len(records)} page records")
    print(f"{structure}: {len(monographs)} monographs, {len(sections)} symptom sections")
    print(f"validation: {metrics}")
    print(f"monographs with no {PROHIBITED}: {[(m['ordinal'], m['name']) for m in missing]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
