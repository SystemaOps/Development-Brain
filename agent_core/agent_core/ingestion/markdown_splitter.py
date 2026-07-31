from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MarkdownChunk:
    title: str
    heading_path: list[str]
    content: str
    token_estimate: int


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def split_markdown_by_headings(text: str, max_tokens: int = 1200) -> list[MarkdownChunk]:
    lines = text.splitlines()
    chunks: list[MarkdownChunk] = []
    current_path: list[str] = []
    current_title = "Introduction"
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        content = "\n".join(current_lines).strip()
        if content:
            chunks.append(MarkdownChunk(current_title, current_path.copy(), content, estimate_tokens(content)))
        current_lines = []

    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            current_path[:] = current_path[: level - 1]
            current_path.append(title)
            current_title = title
        current_lines.append(line)
    flush()

    output: list[MarkdownChunk] = []
    for chunk in chunks:
        if chunk.token_estimate <= max_tokens:
            output.append(chunk)
            continue
        paragraphs = chunk.content.split("\n\n")
        buf: list[str] = []
        part = 1
        for para in paragraphs:
            candidate = "\n\n".join([*buf, para])
            if estimate_tokens(candidate) > max_tokens and buf:
                content = "\n\n".join(buf)
                output.append(MarkdownChunk(f"{chunk.title} part {part}", chunk.heading_path, content, estimate_tokens(content)))
                part += 1
                buf = [para]
            else:
                buf.append(para)
        if buf:
            content = "\n\n".join(buf)
            output.append(MarkdownChunk(f"{chunk.title} part {part}" if part > 1 else chunk.title, chunk.heading_path, content, estimate_tokens(content)))
    return output
