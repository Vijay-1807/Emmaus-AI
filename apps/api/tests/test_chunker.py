from app.ingestion.chunker import chunk_document, chunk_markdown_text


def test_basic_chunking_with_headings():
    pages = [
        {
            "number": 1,
            "text": "# Introduction\nThis is the intro paragraph with enough text to form a chunk on its own merits.\n\n## Methods\nWe used three methods to evaluate the system across many documents and datasets.",
        }
    ]
    chunks = chunk_document(pages)
    assert len(chunks) >= 2
    sections = {c.section for c in chunks}
    assert "Introduction" in sections
    assert "Methods" in sections
    assert all(len(c.content) >= 40 for c in chunks)


def test_long_text_split_overlap():
    text = "word " * 2000
    chunks = chunk_markdown_text(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content) <= 1200


def test_min_length_filter():
    chunks = chunk_markdown_text("tiny")
    assert chunks == []


def test_page_numbers_preserved():
    chunks = chunk_document(
        [
            {"number": 3, "text": "# Section A\n" + "content " * 60},
            {"number": 4, "text": "# Section B\n" + "content " * 60},
        ]
    )
    assert {c.page for c in chunks} == {3, 4}
