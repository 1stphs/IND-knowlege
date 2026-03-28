import hashlib
import re
from dataclasses import dataclass


def _stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    return cleaned


@dataclass
class MarkdownSection:
    title: str
    level: int
    path: list[str]
    content: str
    start_line: int
    end_line: int


@dataclass
class MarkdownChunk:
    document_id: str
    source_md: str
    section_id: str
    chunk_id: str
    evidence_id: str
    chunk_index: int
    section_path: list[str]
    source_location: str
    content: str
    snippet: str
    chunk_hash: str
    start_line: int
    end_line: int

    def to_metadata(self) -> dict:
        return {
            "document_id": self.document_id,
            "section_id": self.section_id,
            "chunk_id": self.chunk_id,
            "evidence_id": self.evidence_id,
            "source_md": self.source_md,
            "source_location": self.source_location,
            "snippet": self.snippet,
            "chunk_hash": self.chunk_hash,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


class MarkdownTreeParser:
    @staticmethod
    def parse_to_tree(content: str):
        lines = content.split("\n")
        root = {"title": "Root", "content": "", "children": [], "level": 0}
        stack = [root]
        current_text: list[str] = []
        header_regex = re.compile(r"^(#{1,6})\s+(.*)$")

        for line in lines:
            match = header_regex.match(line)
            if match:
                if current_text:
                    stack[-1]["content"] = "\n".join(current_text).strip()
                    current_text = []

                level = len(match.group(1))
                title = match.group(2).strip()
                new_node = {"title": title, "content": "", "children": [], "level": level}

                while len(stack) > 1 and stack[-1]["level"] >= level:
                    stack.pop()

                stack[-1]["children"].append(new_node)
                stack.append(new_node)
            else:
                current_text.append(line)

        if current_text and stack:
            stack[-1]["content"] = "\n".join(current_text).strip()

        return root["children"]

    @staticmethod
    def document_id_for(source_md: str) -> str:
        return f"doc_{_stable_hash(source_md, 16)}"

    @staticmethod
    def parse_sections(content: str) -> list[MarkdownSection]:
        lines = content.splitlines()
        header_regex = re.compile(r"^(#{1,6})\s+(.*)$")
        sections: list[MarkdownSection] = []
        path_stack: list[str] = []
        current_title = "Document Root"
        current_level = 1
        current_start = 1
        current_content: list[str] = []

        def flush(end_line: int):
            text = "\n".join(current_content).strip()
            if not text:
                return
            section_path = (path_stack or [current_title]).copy()
            sections.append(
                MarkdownSection(
                    title=current_title,
                    level=current_level,
                    path=section_path,
                    content=text,
                    start_line=current_start,
                    end_line=end_line,
                )
            )

        for index, line in enumerate(lines, start=1):
            match = header_regex.match(line)
            if match:
                flush(index - 1)
                current_content = []
                current_level = len(match.group(1))
                current_title = _normalize_text(match.group(2))
                path_stack = path_stack[: current_level - 1]
                path_stack.append(current_title)
                current_start = index
            else:
                current_content.append(line)

        flush(len(lines))
        if not sections:
            whole_text = _normalize_text(content)
            if whole_text:
                sections.append(
                    MarkdownSection(
                        title="Document Root",
                        level=1,
                        path=["Document Root"],
                        content=whole_text,
                        start_line=1,
                        end_line=max(len(lines), 1),
                    )
                )
        return sections

    @staticmethod
    def build_chunks(
        content: str,
        source_md: str,
        max_chars: int = 1200,
        overlap_chars: int = 120,
    ) -> list[MarkdownChunk]:
        document_id = MarkdownTreeParser.document_id_for(source_md)
        sections = MarkdownTreeParser.parse_sections(content)
        chunks: list[MarkdownChunk] = []

        for section in sections:
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section.content) if p.strip()]
            if not paragraphs:
                continue

            buffer = ""
            section_index = 0
            section_path_text = " > ".join(section.path)
            section_id = f"sec_{_stable_hash(f'{document_id}:{section_path_text}', 16)}"

            for paragraph in paragraphs:
                candidate = paragraph if not buffer else f"{buffer}\n\n{paragraph}"
                if buffer and len(candidate) > max_chars:
                    snippet = _normalize_text(buffer)[:220]
                    chunk_hash = _stable_hash(buffer, 20)
                    chunk_id = f"{section_id}_chunk_{section_index}"
                    chunks.append(
                        MarkdownChunk(
                            document_id=document_id,
                            source_md=source_md,
                            section_id=section_id,
                            chunk_id=chunk_id,
                            evidence_id=f"ev_{chunk_id}",
                            chunk_index=section_index,
                            section_path=section.path,
                            source_location=f"{section_path_text} [chunk {section_index + 1}]",
                            content=buffer.strip(),
                            snippet=snippet,
                            chunk_hash=chunk_hash,
                            start_line=section.start_line,
                            end_line=section.end_line,
                        )
                    )
                    section_index += 1
                    overlap = buffer[-overlap_chars:] if overlap_chars > 0 else ""
                    buffer = f"{overlap}\n\n{paragraph}".strip()
                else:
                    buffer = candidate

            if buffer.strip():
                snippet = _normalize_text(buffer)[:220]
                chunk_hash = _stable_hash(buffer, 20)
                chunk_id = f"{section_id}_chunk_{section_index}"
                chunks.append(
                    MarkdownChunk(
                        document_id=document_id,
                        source_md=source_md,
                        section_id=section_id,
                        chunk_id=chunk_id,
                        evidence_id=f"ev_{chunk_id}",
                        chunk_index=section_index,
                        section_path=section.path,
                        source_location=f"{section_path_text} [chunk {section_index + 1}]",
                        content=buffer.strip(),
                        snippet=snippet,
                        chunk_hash=chunk_hash,
                        start_line=section.start_line,
                        end_line=section.end_line,
                    )
                )

        return chunks
