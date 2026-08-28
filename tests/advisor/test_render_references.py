"""render_references: bare ids in, rendered Thai citation out (ADR 0010's
citation contract). Every note handed to the Advisor is citable via its
`[n]` label; render_references resolves those numbers to book titles
(corpus/books.yaml) and printed page ranges (the filename), grouped by
book, capped at 3, in ascending reference_id order -- and silently drops
any id that does not name a passage the Advisor was actually given.
"""

from pathlib import Path

import app.advisor.citation as citation_module
from app.advisor.citation import render_references
from app.config import Settings


def _settings(corpus_dir: Path) -> Settings:
    return Settings(
        line_channel_secret="test",
        line_channel_access_token="test",
        corpus_dir=str(corpus_dir),
    )


def _write_note(corpus_dir: Path, book_id: str, filename: str) -> None:
    book_dir = corpus_dir / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / f"{filename}.md").write_text("---\nuid: x\n---\nbody\n", encoding="utf-8")


def _write_books_yaml(corpus_dir: Path, books: dict[str, str]) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{book_id}: {title}" for book_id, title in books.items()]
    (corpus_dir / "books.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _patch_settings(monkeypatch, corpus_dir: Path) -> None:
    monkeypatch.setattr(citation_module, "get_settings", lambda: _settings(corpus_dir))


def test_no_citation_line_passes_the_reply_through_unchanged(monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path / "corpus")
    reply = "คำตอบธรรมดา ไม่มีการอ้างอิง"

    assert render_references(reply, []) == reply


def test_single_note_renders_book_title_and_page_range(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-เรื่อง-น.1-4")
    _patch_settings(monkeypatch, corpus_dir)

    passages = ["[1] 001-เรื่อง-น.1-4\nเนื้อหาลิ้น"]
    reply = "คำแนะนำของฉัน\n(อ้างอิง: [1])"

    rendered = render_references(reply, passages)

    assert rendered == "คำแนะนำของฉัน\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4)"


def test_multiple_notes_from_the_same_book_group_their_page_ranges(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _write_note(corpus_dir, "tongue-100", "002-b-น.9-9")
    _patch_settings(monkeypatch, corpus_dir)

    passages = ["[1] 001-a-น.1-4\nA", "[2] 002-b-น.9-9\nB"]
    reply = "คำแนะนำ\n(อ้างอิง: [1] [2])"

    rendered = render_references(reply, passages)

    assert rendered == "คำแนะนำ\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4, 9-9)"


def test_notes_from_different_books_render_as_separate_groups(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(
        corpus_dir,
        {
            "tongue-100": "100 ลักษณะวินิจฉัยลิ้น",
            "four-elements": "วิถีแห่งธรรมชาติกับธาตุทั้งสี่",
        },
    )
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _write_note(corpus_dir, "four-elements", "01-b-น.17-18")
    _patch_settings(monkeypatch, corpus_dir)

    passages = ["[1] 001-a-น.1-4\nA", "[2] 01-b-น.17-18\nB"]
    reply = "คำแนะนำ\n(อ้างอิง: [1] [2])"

    rendered = render_references(reply, passages)

    assert rendered == (
        "คำแนะนำ\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4; "
        "วิถีแห่งธรรมชาติกับธาตุทั้งสี่ หน้า 17-18)"
    )


def test_ordering_follows_ascending_reference_id_not_citation_order(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(
        corpus_dir, {"book-a": "หนังสือ A", "book-b": "หนังสือ B"}
    )
    _write_note(corpus_dir, "book-a", "01-x-น.1-1")
    _write_note(corpus_dir, "book-b", "01-y-น.2-2")
    _patch_settings(monkeypatch, corpus_dir)

    passages = ["[1] 01-x-น.1-1\nA", "[2] 01-y-น.2-2\nB"]
    # The model wrote the higher id first -- rendering must not follow it.
    reply = "คำแนะนำ\n(อ้างอิง: [2] [1])"

    rendered = render_references(reply, passages)

    assert rendered == "คำแนะนำ\n(อ้างอิง: หนังสือ A หน้า 1-1; หนังสือ B หน้า 2-2)"


def test_cap_3_books_drops_the_fourth(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    books = {f"book-{letter}": f"หนังสือ {letter.upper()}" for letter in "abcd"}
    _write_books_yaml(corpus_dir, books)
    passages = []
    for index, letter in enumerate("abcd", start=1):
        filename = f"01-x-น.{index}-{index}"
        _write_note(corpus_dir, f"book-{letter}", filename)
        passages.append(f"[{index}] {filename}\nเนื้อหา {letter}")
    _patch_settings(monkeypatch, corpus_dir)

    reply = "คำแนะนำ\n(อ้างอิง: [1] [2] [3] [4])"

    rendered = render_references(reply, passages)

    assert "หนังสือ A" in rendered
    assert "หนังสือ B" in rendered
    assert "หนังสือ C" in rendered
    assert "หนังสือ D" not in rendered


def test_invented_id_is_dropped_but_real_ids_still_render(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _patch_settings(monkeypatch, corpus_dir)

    # Only note [1] was ever handed to the Advisor -- [9] is invented.
    passages = ["[1] 001-a-น.1-4\nA"]
    reply = "คำแนะนำ\n(อ้างอิง: [1] [9])"

    rendered = render_references(reply, passages)

    assert rendered == "คำแนะนำ\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4)"
    assert "9" not in rendered.split("(อ้างอิง:")[1]


def test_when_every_cited_id_is_invented_the_citation_line_is_dropped(monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path / "corpus")
    passages: list[str] = []
    reply = "คำแนะนำของฉัน\n(อ้างอิง: [9])"

    rendered = render_references(reply, passages)

    assert rendered == "คำแนะนำของฉัน"


def test_the_graph_context_block_has_no_label_and_is_never_citable(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _patch_settings(monkeypatch, corpus_dir)

    passages = [
        "[1] 001-a-น.1-4\nA",
        "[บริบทจากกราฟความรู้ -- หลักฐานประกอบ ไม่มีเลขอ้างอิง]\nเอนทิตี: ...",
    ]
    # The model correctly never cites the graph block (it has no number),
    # but even a malformed attempt must not resolve to anything.
    reply = "คำแนะนำ\n(อ้างอิง: [1])"

    rendered = render_references(reply, passages)

    assert rendered == "คำแนะนำ\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4)"


def test_citation_before_a_topic_menu_block_is_still_found_and_rendered(monkeypatch, tmp_path):
    """The raw Advisor reply may still carry its `[หัวข้อ]` block (ADR 0006)
    when render_references runs, since it is called before the Working
    Buffer write -- ahead of the transport-only topic-menu split."""
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _patch_settings(monkeypatch, corpus_dir)

    passages = ["[1] 001-a-น.1-4\nA"]
    reply = "คำแนะนำ\n(อ้างอิง: [1])\n[หัวข้อ]\n- หัวข้อหนึ่ง\n- หัวข้อสอง"

    rendered = render_references(reply, passages)

    assert rendered == (
        "คำแนะนำ\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4)\n"
        "[หัวข้อ]\n- หัวข้อหนึ่ง\n- หัวข้อสอง"
    )


def test_rendered_output_still_parses_through_split_citation(monkeypatch, tmp_path):
    """ADR 0009's parser must consume the rendered line unchanged -- same
    `(อ้างอิง: ...)` format, just resolved content."""
    from app.advisor.citation import split_citation

    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _patch_settings(monkeypatch, corpus_dir)

    passages = ["[1] 001-a-น.1-4\nA"]
    reply = "คำแนะนำ\n(อ้างอิง: [1])"

    rendered = render_references(reply, passages)
    body, citation = split_citation(rendered)

    assert body == "คำแนะนำ"
    assert citation == "100 ลักษณะวินิจฉัยลิ้น หน้า 1-4"


def test_invariant_every_handed_note_is_citable_and_every_citation_names_a_handed_note(
    monkeypatch, tmp_path
):
    """The tested invariant from the brief: every note handed to the
    Advisor is citable (real ids [1] and [2] both resolve), and every
    rendered citation names a note that was handed to the Advisor (no
    trace of the invented id [9], and nothing renders for a book that was
    never in `passages`)."""
    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(
        corpus_dir,
        {
            "tongue-100": "100 ลักษณะวินิจฉัยลิ้น",
            "four-elements": "วิถีแห่งธรรมชาติกับธาตุทั้งสี่",
        },
    )
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _write_note(corpus_dir, "four-elements", "01-b-น.17-18")
    _patch_settings(monkeypatch, corpus_dir)

    passages = ["[1] 001-a-น.1-4\nA", "[2] 01-b-น.17-18\nB"]
    reply = "คำแนะนำ\n(อ้างอิง: [1] [2] [9])"

    rendered = render_references(reply, passages)
    citation_text = rendered.split("(อ้างอิง: ", 1)[1].rstrip(")")

    # Every note handed to the Advisor is citable.
    assert "100 ลักษณะวินิจฉัยลิ้น หน้า 1-4" in citation_text
    assert "วิถีแห่งธรรมชาติกับธาตุทั้งสี่ หน้า 17-18" in citation_text
    # Every rendered citation names a handed note -- nothing else leaks in.
    groups = citation_text.split("; ")
    assert len(groups) == 2


def test_corpus_drift_missing_file_logs_warning_but_drops_citation(monkeypatch, tmp_path, caplog):
    """A cited id whose passage label names a file that doesn't exist in the
    corpus tree (corpus drift, missing book folder, renamed file) is dropped
    from the rendered line AND a warning is logged, distinguishing this from
    an invented id."""
    import logging

    corpus_dir = tmp_path / "corpus"
    _write_books_yaml(corpus_dir, {"tongue-100": "100 ลักษณะวินิจฉัยลิ้น"})
    # Note [1] exists in the corpus; [2] is in passages but the file is missing.
    _write_note(corpus_dir, "tongue-100", "001-a-น.1-4")
    _patch_settings(monkeypatch, corpus_dir)

    passages = [
        "[1] 001-a-น.1-4\nA",
        "[2] 999-missing-file-น.5-6\nB",  # This file doesn't exist
    ]
    reply = "คำแนะนำ\n(อ้างอิง: [1] [2])"

    with caplog.at_level(logging.WARNING):
        rendered = render_references(reply, passages)

    # Id [2] is dropped from the rendered output (like invented ids).
    assert rendered == "คำแนะนำ\n(อ้างอิง: 100 ลักษณะวินิจฉัยลิ้น หน้า 1-4)"
    # But a warning is logged (unlike invented ids, which stay silent).
    assert any(
        "Failed to resolve citation id=2" in record.message and record.levelname == "WARNING"
        for record in caplog.records
    )
