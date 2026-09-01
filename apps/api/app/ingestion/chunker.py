import re
from dataclasses import dataclass

CHUNK_SIZE_CHARS = 900
CHUNK_OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 40

HEADING_RE = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)


@dataclass
class ChunkData:
    content: str
    page: int
    section: str | None
    heading: str | None
    position: int


def _split_long_text(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text] if text.strip() else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end]
        if len(piece) > overlap and end < len(text):
            last_space = piece.rfind(" ")
            if last_space > size // 2:
                piece = piece[:last_space]
                end = start + last_space
        if piece.strip():
            parts.append(piece.strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return parts


def _extract_sections(page_text: str) -> list[tuple[str | None, str]]:
    matches = list(HEADING_RE.finditer(page_text))
    if not matches:
        return [(None, page_text)]
    sections: list[tuple[str | None, str]] = []
    if matches[0].start() > 0:
        preamble = page_text[: matches[0].start()]
        if preamble.strip():
            sections.append((None, preamble))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        section_start = match.start()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
        sections.append((heading, page_text[section_start:section_end]))
    return sections


def chunk_document(pages: list[dict]) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    position = 0
    for page in pages:
        page_number = page.get("number", 1)
        for heading, section_text in _extract_sections(page.get("text", "")):
            for piece in _split_long_text(section_text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS):
                if len(piece) < MIN_CHUNK_CHARS:
                    continue
                chunks.append(
                    ChunkData(
                        content=piece,
                        page=page_number,
                        section=heading,
                        heading=heading,
                        position=position,
                    )
                )
                position += 1
    return chunks


def chunk_markdown_text(text: str, source_page: int = 1) -> list[ChunkData]:
    return chunk_document([{"number": source_page, "text": text}])
