from app.rag.pdf_ocr import PageTranscription, paragraph_records


def test_printed_page_number_wins_over_pdf_page():
    transcription = PageTranscription(
        printed_page_number=42,
        paragraphs=["ย่อหน้าแรก", "ย่อหน้าที่สอง 舌診"],
    )

    records = paragraph_records(
        transcription, book_id="tamra-ttm", book_title="ตำราแพทย์แผนไทย", pdf_page=50
    )

    assert records == [
        {
            "book_id": "tamra-ttm",
            "book_title": "ตำราแพทย์แผนไทย",
            "page": 42,
            "pdf_page": 50,
            "paragraph": 1,
            "text": "ย่อหน้าแรก",
        },
        {
            "book_id": "tamra-ttm",
            "book_title": "ตำราแพทย์แผนไทย",
            "page": 42,
            "pdf_page": 50,
            "paragraph": 2,
            "text": "ย่อหน้าที่สอง 舌診",
        },
    ]


def test_falls_back_to_pdf_page_and_drops_blank_paragraphs():
    transcription = PageTranscription(paragraphs=["  ", "เนื้อหา", ""])

    records = paragraph_records(transcription, book_id="tamra-ttm", book_title="ตำรา", pdf_page=5)

    assert [r["page"] for r in records] == [5]
    assert [r["paragraph"] for r in records] == [1]
    assert records[0]["text"] == "เนื้อหา"
