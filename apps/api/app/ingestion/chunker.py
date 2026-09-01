import re
from dataclasses import dataclass, field

CHUNK_SIZE_CHARS = 900
CHUNK_OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 40
PARENT_CONTEXT_CHARS = 200

HEADING_RE = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)
BULLET_RE = re.compile(r"^[\-\*]\s+", re.MULTILINE)


@dataclass
class ChunkData:
    content: str
    page: int
    section: str | None
    heading: str | None
    position: int
    parent_context: str = ""
    chunk_type: str = "text"
    metadata: dict = field(default_factory=dict)


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
        section_start = match.match.start() if hasattr(match, 'match') else match.start()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
        sections.append((heading, page_text[section_start:section_end]))
    return sections


def _extract_list_items(text: str) -> list[str]:
    items = []
    for line in text.split("\n"):
        if BULLET_RE.match(line.strip()):
            items.append(line.strip())
    return items


def _build_parent_context(heading: str | None, section_text: str) -> str:
    parts = []
    if heading:
        parts.append(f"Section: {heading}")
    preview = section_text[:PARENT_CONTEXT_CHARS].replace("\n", " ").strip()
    if preview:
        parts.append(preview)
    return " | ".join(parts)


def chunk_document(pages: list[dict]) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    position = 0
    for page in pages:
        page_number = page.get("number", 1)
        headings = page.get("headings") or []
        for heading, section_text in _extract_sections(page.get("text", "")):
            effective_heading = heading or (headings[0] if headings else None)
            parent_ctx = _build_parent_context(effective_heading, section_text)

            list_items = _extract_list_items(section_text)
            if list_items and len(list_items) <= 10:
                list_text = "\n".join(list_items)
                if len(list_text) >= MIN_CHUNK_CHARS:
                    chunks.append(
                        ChunkData(
                            content=list_text,
                            page=page_number,
                            section=effective_heading,
                            heading=effective_heading,
                            position=position,
                            parent_context=parent_ctx,
                            chunk_type="list",
                            metadata={"item_count": len(list_items)},
                        )
                    )
                    position += 1
                remaining = section_text
                for item in list_items:
                    remaining = remaining.replace(item, "", 1)
                section_text = remaining.strip()

            for piece in _split_long_text(section_text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS):
                if len(piece) < MIN_CHUNK_CHARS:
                    continue
                chunks.append(
                    ChunkData(
                        content=piece,
                        page=page_number,
                        section=effective_heading,
                        heading=effective_heading,
                        position=position,
                        parent_context=parent_ctx,
                        chunk_type="text",
                    )
                )
                position += 1
    return chunks


def chunk_markdown_text(text: str, source_page: int = 1) -> list[ChunkData]:
    return chunk_document([{"number": source_page, "text": text}])
