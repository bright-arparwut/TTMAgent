"""Unit tests for app.rag.source_notes (ticket #12 source-note format validator,
plus the ticket #24 staleness-manifest CLI)."""

import hashlib
import json
import unicodedata

import pytest

from app.rag.source_notes import (
    ManifestDiff,
    compute_manifest,
    diff_manifest,
    format_check_index_report,
    load_manifest,
    main,
    manifest_path_for,
    parse_note,
    save_manifest,
    validate_corpus,
)

VALID_BODY = "ก" * 250


def frontmatter(**overrides: object) -> str:
    fields: dict[str, object] = {
        "uid": "four-elements-01",
        "type": "source-note",
        "book_id": "four-elements",
        "chapter": "บทนำ",
        "section": "บทนำ",
        "pages": "[13, 16]",
        "pdf_pages": "[8, 11]",
    }
    fields.update(overrides)
    lines = "\n".join(f"{k}: {v}" for k, v in fields.items() if v is not None)
    return f"---\n{lines}\n---\n"


def write_book(tmp_path, notes, books_yaml="four-elements: ชื่อหนังสือ\n"):
    """notes: list of (filename, full file text). Returns the corpus root."""
    root = tmp_path / "corpus"
    (root / "four-elements").mkdir(parents=True, exist_ok=True)
    (root / "books.yaml").write_text(books_yaml, encoding="utf-8")
    for name, text in notes:
        path = root / "four-elements" / unicodedata.normalize("NFC", name)
        path.write_text(text, encoding="utf-8")
    return root


def note(name="01-บทนำ-น.13-16.md", body=VALID_BODY, **fm):
    return (name, frontmatter(**fm) + "\n" + body + "\n")


# --- parse_note -------------------------------------------------------------


def test_parse_note_reads_frontmatter_and_body(tmp_path):
    root = write_book(tmp_path, [note()])
    parsed = parse_note(root / "four-elements" / "01-บทนำ-น.13-16.md")
    assert parsed.uid == "four-elements-01"
    assert parsed.book_id == "four-elements"
    assert parsed.pages == (13, 16)
    assert parsed.pdf_pages == (8, 11)
    assert parsed.ordinal == 1
    assert parsed.section == "บทนำ"


def test_parse_note_rejects_file_without_frontmatter(tmp_path):
    root = write_book(tmp_path, [("01-บทนำ-น.13-16.md", "no frontmatter here")])
    with pytest.raises(ValueError):
        parse_note(root / "four-elements" / "01-บทนำ-น.13-16.md")


# --- errors -----------------------------------------------------------------


def test_valid_corpus_has_no_errors(tmp_path):
    root = write_book(tmp_path, [note()])
    errors, _ = validate_corpus(root)
    assert errors == []


def test_validate_corpus_ignores_archive_and_concepts_directories(tmp_path):
    # corpus/archive/ (Phase 5) and corpus/concepts/ (Phase 6, the generated
    # vault) are never book folders and carry a different frontmatter
    # schema entirely -- validate_corpus must not try to parse their
    # contents as source notes.
    root = write_book(tmp_path, [note()])
    (root / "archive").mkdir()
    (root / "archive" / "retired.jsonl").write_text("{}", encoding="utf-8")
    (root / "concepts").mkdir()
    (root / "concepts" / "ธาตุทั้งสี่.md").write_text(
        '---\nentity: "ธาตุทั้งสี่"\ntype: "concept"\ndegree: 1\ngenerated: true\naliases: []\n'
        "---\n\nbody\n",
        encoding="utf-8",
    )
    errors, _ = validate_corpus(root)
    assert errors == []


def test_missing_required_field_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(chapter=None)])
    errors, _ = validate_corpus(root)
    assert any("chapter" in e for e in errors)


def test_duplicate_uid_is_an_error(tmp_path):
    root = write_book(
        tmp_path,
        [
            note(),
            note(
                name="02-ในอดีต-น.18-19.md", section="ในอดีต", pages="[18, 19]", pdf_pages="[13, 14]"
            ),
        ],
    )
    errors, _ = validate_corpus(root)
    assert any("uid" in e and "four-elements-01" in e for e in errors)


def test_book_id_missing_from_books_yaml_is_an_error(tmp_path):
    root = write_book(tmp_path, [note()], books_yaml="other-book: x\n")
    errors, _ = validate_corpus(root)
    assert any("books.yaml" in e for e in errors)


def test_filename_page_range_disagreeing_with_frontmatter_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(name="01-บทนำ-น.13-99.md")])
    errors, _ = validate_corpus(root)
    assert any("filename" in e.lower() for e in errors)


def test_filename_section_disagreeing_with_frontmatter_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(name="01-อื่น-น.13-16.md")])
    errors, _ = validate_corpus(root)
    assert any("filename" in e.lower() for e in errors)


def test_thai_filenames_are_nfc_stable():
    """Thai vowels and tone marks have no canonical decomposition, so NFC == NFD here.

    Ticket #12's NFC rule still guards non-Thai section titles — see the next test.
    """
    name = "01-บทนำ-น.13-16.md"
    assert unicodedata.normalize("NFD", name) == unicodedata.normalize("NFC", name)


def test_nfd_filename_is_an_error(tmp_path):
    root = tmp_path / "corpus"
    (root / "four-elements").mkdir(parents=True)
    (root / "books.yaml").write_text("four-elements: x\n", encoding="utf-8")
    name = unicodedata.normalize("NFD", "01-café-น.13-16.md")
    assert name != unicodedata.normalize("NFC", name)
    body = frontmatter(section="café") + "\n" + VALID_BODY
    (root / "four-elements" / name).write_text(body, encoding="utf-8")
    errors, _ = validate_corpus(root)
    assert any("NFC" in e for e in errors)


def test_three_digit_ordinal_is_accepted(tmp_path):
    """Ticket #28 numbers tongue-100's ~125 notes with a 3-digit running NN."""
    root = write_book(tmp_path, [note(name="001-บทนำ-น.13-16.md")])
    parsed = parse_note(root / "four-elements" / "001-บทนำ-น.13-16.md")
    assert parsed.ordinal == 1
    errors, _ = validate_corpus(root)
    assert errors == []


def test_mixed_ordinal_widths_in_one_book_are_an_error(tmp_path):
    """Notes sort lexically, so a 2-digit 99 would sort after a 3-digit 100.

    Band-allocated parallel transcription (map #9) writes into one book directory
    from several sessions, so a width slip is the collision to catch.
    """
    root = write_book(
        tmp_path,
        [
            note(name="99-บทนำ-น.13-16.md"),
            note(
                name="100-ในอดีต-น.18-19.md",
                uid="four-elements-02",
                section="ในอดีต",
                pages="[18, 19]",
                pdf_pages="[13, 14]",
            ),
        ],
    )
    errors, _ = validate_corpus(root)
    assert any("ordinal width" in e for e in errors)


def test_reversed_page_range_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(name="01-บทนำ-น.16-13.md", pages="[16, 13]")])
    errors, _ = validate_corpus(root)
    assert any("pages" in e for e in errors)


def test_repeated_ordinal_is_an_error(tmp_path):
    root = write_book(
        tmp_path,
        [
            note(),
            note(
                name="01-ในอดีต-น.18-19.md",
                uid="four-elements-02",
                section="ในอดีต",
                pages="[18, 19]",
                pdf_pages="[13, 14]",
            ),
        ],
    )
    errors, _ = validate_corpus(root)
    assert any("ordinals move backwards" in e for e in errors)


def test_page_range_moving_backwards_is_an_error(tmp_path):
    """A later ordinal may share a start page, but must never start earlier."""
    root = write_book(
        tmp_path,
        [
            note(name="01-บทนำ-น.18-19.md", pages="[18, 19]", pdf_pages="[13, 14]"),
            note(name="02-ในอดีต-น.13-16.md", uid="four-elements-02", section="ในอดีต"),
        ],
    )
    errors, _ = validate_corpus(root)
    assert any("page ranges move backwards" in e for e in errors)


def test_overlapping_ranges_are_allowed(tmp_path):
    """ธาตุทั้งสี่ and ราศีและการบำบัด both start on p19 — legitimate (ticket #12)."""
    root = write_book(
        tmp_path,
        [
            note(
                name="01-ธาตุทั้งสี่-น.19-19.md",
                section="ธาตุทั้งสี่",
                pages="[19, 19]",
                pdf_pages="[14, 14]",
            ),
            note(
                name="02-ราศีและการบำบัด-น.19-21.md",
                uid="four-elements-02",
                section="ราศีและการบำบัด",
                pages="[19, 21]",
                pdf_pages="[14, 16]",
            ),
        ],
    )
    errors, _ = validate_corpus(root)
    assert errors == []


def test_page_marker_outside_declared_range_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(body=VALID_BODY + "<!-- p.99 -->more")])
    errors, _ = validate_corpus(root)
    assert any("p.99" in e for e in errors)


def test_page_marker_for_the_start_page_is_an_error(tmp_path):
    """Markers mark transitions only — a note starting on 13 carries no p.13 marker."""
    root = write_book(tmp_path, [note(body=VALID_BODY + "<!-- p.13 -->more")])
    errors, _ = validate_corpus(root)
    assert any("p.13" in e for e in errors)


def test_page_markers_must_strictly_ascend(tmp_path):
    body = VALID_BODY + "<!-- p.15 -->a<!-- p.14 -->b"
    root = write_book(tmp_path, [note(body=body)])
    errors, _ = validate_corpus(root)
    assert any("ascend" in e for e in errors)


def test_h1_in_body_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(body="# หัวข้อ\n\n" + VALID_BODY)])
    errors, _ = validate_corpus(root)
    assert any("H1" in e for e in errors)


def test_table_with_inconsistent_column_count_is_an_error(tmp_path):
    body = VALID_BODY + "\n\n| a | b |\n| --- | --- |\n| 1 | 2 | 3 |\n"
    root = write_book(tmp_path, [note(body=body)])
    errors, _ = validate_corpus(root)
    assert any("column" in e for e in errors)


def test_table_without_separator_row_is_an_error(tmp_path):
    body = VALID_BODY + "\n\n| a | b |\n| 1 | 2 |\n"
    root = write_book(tmp_path, [note(body=body)])
    errors, _ = validate_corpus(root)
    assert any("header" in e for e in errors)


def test_well_formed_table_passes(tmp_path):
    body = VALID_BODY + "\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    root = write_book(tmp_path, [note(body=body)])
    errors, _ = validate_corpus(root)
    assert errors == []


def test_malformed_sic_comment_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(body=VALID_BODY + "<!-- sic: -->")])
    errors, _ = validate_corpus(root)
    assert any("sic" in e for e in errors)


def test_well_formed_sic_comment_passes(tmp_path):
    root = write_book(tmp_path, [note(body=VALID_BODY + "กระเพาะ<!-- sic: กระเพราะ -->")])
    errors, _ = validate_corpus(root)
    assert errors == []


def test_unknown_html_comment_is_an_error(tmp_path):
    root = write_book(tmp_path, [note(body=VALID_BODY + "<!-- p 14 -->")])
    errors, _ = validate_corpus(root)
    assert any("comment" in e for e in errors)


# --- warnings ---------------------------------------------------------------


def test_short_body_is_a_warning(tmp_path):
    root = write_book(tmp_path, [note(body="สั้น")])
    _, warnings = validate_corpus(root)
    assert any("short" in w for w in warnings)


def test_bold_line_above_table_is_reported_as_a_caption(tmp_path):
    body = VALID_BODY + "\n\n**ตารางต่อไปนี้**\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    root = write_book(tmp_path, [note(body=body)])
    _, warnings = validate_corpus(root)
    assert any("caption" in w for w in warnings)


def test_caption_is_detected_even_when_a_page_marker_prefixes_it(tmp_path):
    """A caption that opens a page carries the marker inline; it is still a caption."""
    body = VALID_BODY + "\n\n<!-- p.14 -->**ตารางต่อไปนี้**\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    root = write_book(tmp_path, [note(body=body)])
    errors, warnings = validate_corpus(root)
    assert errors == []
    assert any("caption" in w for w in warnings)


def test_marker_only_line_above_a_table_is_not_read_as_a_caption(tmp_path):
    body = VALID_BODY + "\n\nดังนี้ :\n\n<!-- p.14 -->\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    root = write_book(tmp_path, [note(body=body)])
    _, warnings = validate_corpus(root)
    assert not any("caption" in w for w in warnings)


def test_page_coverage_gap_is_a_warning(tmp_path):
    root = write_book(
        tmp_path,
        [
            note(),
            note(
                name="02-ในอดีต-น.20-21.md",
                uid="four-elements-02",
                section="ในอดีต",
                pages="[20, 21]",
                pdf_pages="[15, 16]",
            ),
        ],
    )
    _, warnings = validate_corpus(root)
    assert any("17" in w and "coverage" in w for w in warnings)


def test_contiguous_coverage_produces_no_gap_warning(tmp_path):
    root = write_book(
        tmp_path,
        [
            note(),
            note(
                name="02-ในอดีต-น.16-18.md",
                uid="four-elements-02",
                section="ในอดีต",
                pages="[16, 18]",
                pdf_pages="[11, 13]",
            ),
        ],
    )
    _, warnings = validate_corpus(root)
    assert not any("coverage" in w for w in warnings)


# --- staleness manifest (ticket #24) -----------------------------------------


def test_compute_manifest_maps_uid_to_sha256_of_the_whole_file(tmp_path):
    root = write_book(tmp_path, [note()])
    path = root / "four-elements" / "01-บทนำ-น.13-16.md"
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert compute_manifest(root) == {"four-elements-01": expected}


def test_compute_manifest_covers_every_note_across_a_book(tmp_path):
    root = write_book(
        tmp_path,
        [
            note(),
            note(
                name="02-ในอดีต-น.18-19.md",
                uid="four-elements-02",
                section="ในอดีต",
                pages="[18, 19]",
                pdf_pages="[13, 14]",
            ),
        ],
    )
    assert set(compute_manifest(root)) == {"four-elements-01", "four-elements-02"}


def test_compute_manifest_ignores_archive_and_concepts_directories(tmp_path):
    root = write_book(tmp_path, [note()])
    (root / "archive").mkdir()
    (root / "archive" / "retired.jsonl").write_text("{}", encoding="utf-8")
    (root / "concepts").mkdir()
    (root / "concepts" / "ธาตุทั้งสี่.md").write_text("not a source note", encoding="utf-8")
    assert set(compute_manifest(root)) == {"four-elements-01"}


def test_compute_manifest_fails_cleanly_on_malformed_note(tmp_path, capsys):
    root = write_book(tmp_path, [("01-บทนำ-น.13-16.md", "no frontmatter here")])
    with pytest.raises(SystemExit) as exc:
        compute_manifest(root)
    assert exc.value.code == 1
    stderr = capsys.readouterr().err
    assert "ERROR" in stderr
    assert "four-elements/01-บทนำ-น.13-16.md" in stderr
    assert "frontmatter" in stderr


def test_manifest_path_is_a_sibling_rag_storage_of_the_corpus_root(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    assert manifest_path_for(root) == tmp_path / "rag_storage" / "index-manifest.json"


def test_save_and_load_manifest_round_trip(tmp_path):
    manifest = {"four-elements-01": "abc123"}
    path = tmp_path / "rag_storage" / "index-manifest.json"
    save_manifest(path, manifest)
    assert load_manifest(path) == manifest
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == manifest


def test_diff_manifest_detects_changed_new_and_removed():
    committed = {"a": "hash-a", "b": "hash-b"}
    current = {"a": "hash-a-CHANGED", "c": "hash-c"}
    diff = diff_manifest(committed, current)
    assert diff == ManifestDiff(
        changed=frozenset({"a"}), new=frozenset({"c"}), removed=frozenset({"b"})
    )
    assert diff.is_fresh is False


def test_diff_manifest_is_fresh_when_identical():
    manifest = {"a": "hash-a"}
    diff = diff_manifest(manifest, dict(manifest))
    assert diff.is_fresh is True


def test_format_check_index_report_first_line_matches_the_preflight_parser():
    diff = ManifestDiff(changed=frozenset({"a"}), new=frozenset({"b", "c"}), removed=frozenset())
    report = format_check_index_report(diff)
    assert report.splitlines()[0] == "stale: 1 changed, 2 new, 0 removed"
    assert "a" in report
    assert "b" in report and "c" in report
    assert "adelete_by_doc_id" in report


def test_write_manifest_writes_current_notes_and_exits_zero(tmp_path, capsys):
    root = write_book(tmp_path, [note()])
    with pytest.raises(SystemExit) as exc:
        main([str(root), "--write-manifest"])
    assert exc.value.code == 0
    manifest = load_manifest(manifest_path_for(root))
    assert set(manifest) == {"four-elements-01"}
    assert "wrote" in capsys.readouterr().out


def test_check_index_passes_when_manifest_matches_current_notes(tmp_path, capsys):
    root = write_book(tmp_path, [note()])
    with pytest.raises(SystemExit):
        main([str(root), "--write-manifest"])
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--check-index"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "fresh"


def test_check_index_fails_naming_the_stale_uid_after_an_edit(tmp_path, capsys):
    root = write_book(tmp_path, [note()])
    with pytest.raises(SystemExit):
        main([str(root), "--write-manifest"])
    capsys.readouterr()

    path = root / "four-elements" / "01-บทนำ-น.13-16.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main([str(root), "--check-index"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "stale: 1 changed, 0 new, 0 removed"
    assert "four-elements-01" in out
    assert "adelete_by_doc_id" in out


def test_check_index_fails_when_no_manifest_is_committed_yet(tmp_path, capsys):
    root = write_book(tmp_path, [note()])
    with pytest.raises(SystemExit) as exc:
        main([str(root), "--check-index"])
    assert exc.value.code == 1
    assert "index-manifest.json" in capsys.readouterr().err
