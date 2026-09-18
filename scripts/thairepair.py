"""Repair Thai text extracted from born-digital PDFs that double their combining marks.

Ticket #60 (map #45), implementing the route #46 established and measured.

`แนวทางการใช้ยาสมุนไพรในการดูแลอาการเจ็บป่วยเบื้องต้น` (book three) is InDesign
output whose text layer is intact but *encoded* in a way poppler renders with two
mechanical, fully deterministic defects:

1. Every Thai above/below vowel, tone mark and SARA AM is emitted **twice**.
   Never tripled -- always exactly two.
2. A stacked vowel+tone pair emits one extra positioning glyph with no `ToUnicode`
   entry. Poppler spells it `U+FFFD`; PyMuPDF spells it `U+02E0`/`U+02E3`. It is
   typographic furniture, not a character.

Nothing was ever lost -- it was doubled -- so the damage is a pure function of the
text and therefore invertible. That is why this is regex rather than an OCR or
vision pass: #46 priced the vision route at $21.46 / 196 pages and measured this one
at 0.9 s and $0.00 for the whole book, with the decisive advantage that a pure
function can be re-run in CI and diffed, which no vision pass can.

`repair()` is the whole contract. `validate()` exists so a caller can assert the
repair landed rather than trusting it: on book three it takes illegal above-mark
pairs from 39,292 to 0 and residual doubled marks from 45,837 to 0.

Usage:

    python scripts/thairepair.py book3.pdf --report -o repaired.txt
    pdftotext -raw book3.pdf - | python scripts/thairepair.py -
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Above/below vowels, tone marks and SARA AM -- every mark the encoding doubles.
DOUBLED = (
    "ัำิีึืฺุู"  # ั ำ ิ ี ึ ื ฺ ุ ู
    "็่้๊๋์ํ๎"  # ็ ่ ้ ๊ ๋ ์ ํ ๎
)

# The same un-mapped stacking glyph, as poppler and as PyMuPDF spell it. Written as
# escapes on purpose: a literal U+FFFD in source is unreadable and easily mangled.
STACK_GLYPHS = "\ufffd\u02e0\u02e3"

_STACK_RE = re.compile(f"([{DOUBLED}])\\1(\\s*)[{STACK_GLYPHS}]")
_DOUBLED_RE = re.compile(f"([{DOUBLED}])\\1")

# Above-mark classes, for validate(). Thai forbids two consecutive above-marks
# except the one legal stack: an above-vowel carrying a tone mark.
_ABOVE_VOWELS = set("ัิีึื็ํ")
_TONES = set("่้๊๋")
_THANTHAKHAT = set("์")
_ABOVE = _ABOVE_VOWELS | _TONES | _THANTHAKHAT

_CONSONANTS = {chr(c) for c in range(0x0E01, 0x0E2F)}
_LEADING_VOWELS = set("เแโใไ")
_MARKS = set(DOUBLED)


def repair(text: str) -> str:
    """Collapse the doubled marks and drop the un-mapped stacking glyph.

    Order matters. The stacking glyph is identified by the doubled mark in
    front of it, so it must go *before* the doubles are collapsed. Dropping
    `U+FFFD` unconditionally is wrong: exactly 3 in book three are genuine
    characters the font failed to map (see `unmapped()`), and a blind
    `.replace("\ufffd", "")` would silently corrupt three words.
    """
    text = _STACK_RE.sub(r"\1\1\2", text)
    return _DOUBLED_RE.sub(r"\1", text)


def unmapped(text: str) -> list[int]:
    """Offsets of `U+FFFD` surviving `repair()` -- real characters the font lost.

    These are for a human to adjudicate by eye, never to strip. In book three
    there are exactly 3, and all three are unambiguous from context
    (`ค้นหา`, `กรัม`, `ร้อนใน`).
    """
    return [m.start() for m in re.finditer("\ufffd", text)]


def _illegal_above_pairs(text: str) -> int:
    n = 0
    for a, b in zip(text, text[1:], strict=False):  # pairs; the tail has no successor
        if a in _ABOVE and b in _ABOVE:
            if a in _ABOVE_VOWELS and (b in _TONES or b in _THANTHAKHAT):
                continue  # the one legal stack
            n += 1
    return n


def _orphan_marks(text: str) -> int:
    n = 0
    for i, ch in enumerate(text):
        if ch not in _MARKS:
            continue
        prev = text[i - 1] if i else ""
        if prev not in _CONSONANTS and prev not in _MARKS and prev not in _LEADING_VOWELS:
            n += 1
    return n


def validate(text: str) -> dict[str, int]:
    """Structural metrics for asserting a repair landed. All should be 0 after
    `repair()`, except `chars` and `unmapped`, which is the count to eyeball."""
    return {
        "chars": len(text),
        "doubled": len(_DOUBLED_RE.findall(text)),
        "illegal_above_pairs": _illegal_above_pairs(text),
        "orphan_marks": _orphan_marks(text),
        "unmapped": len(unmapped(text)),
    }


def extract(pdf: Path) -> str:
    """`pdftotext -raw` -- the only one of the three extractors #46 tested whose
    damage is recoverable. pdfplumber/pdfminer *substitutes* wrong characters, and
    PyMuPDF additionally drops leading characters."""
    out = subprocess.run(["pdftotext", "-raw", str(pdf), "-"], check=True, capture_output=True)
    return out.stdout.decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="a .pdf to extract, or - to read text on stdin")
    parser.add_argument("-o", "--out", type=Path, help="write repaired text here")
    parser.add_argument("--report", action="store_true", help="print metrics to stderr")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.source == "-" else extract(Path(args.source))
    repaired = repair(raw)

    if args.report:
        before, after = validate(raw), validate(repaired)
        for key in before:
            print(f"{key:>20}: {before[key]:>8} -> {after[key]}", file=sys.stderr)
        for offset in unmapped(repaired):
            print(f"  unmapped @{offset}: {repaired[offset - 25 : offset + 15]!r}", file=sys.stderr)

    if args.out:
        args.out.write_text(repaired, encoding="utf-8")
    else:
        sys.stdout.write(repaired)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
