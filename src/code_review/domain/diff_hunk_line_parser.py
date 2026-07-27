import re
from dataclasses import dataclass
from typing import List

from code_review.domain.diff_sections import FileDiffSectionParser


@dataclass(frozen=True)
class DiffLineEvidence:
    file_path: str
    line: int
    kind: str
    content: str


class DiffHunkLineParser:
    """Extract new-file line numbers from unified diff hunks."""

    HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    def __init__(self, section_parser: FileDiffSectionParser = None) -> None:
        self._section_parser = section_parser or FileDiffSectionParser()

    def parse(self, diff_text: str) -> List[DiffLineEvidence]:
        evidence: List[DiffLineEvidence] = []
        for section in self._section_parser.parse(diff_text):
            evidence.extend(self._parse_section(section.display_path, section.diff_text))
        return evidence

    def render_for_prompt(self, diff_text: str, max_lines: int = 120) -> str:
        lines = []
        for item in self.parse(diff_text)[:max_lines]:
            prefix = "+" if item.kind == "added" else " "
            lines.append(f"{item.file_path}:{item.line} {prefix} {item.content}")
        if not lines:
            return "未解析到可定位的新文件行号。"
        return "\n".join(lines)

    def _parse_section(self, file_path: str, section_text: str) -> List[DiffLineEvidence]:
        evidence: List[DiffLineEvidence] = []
        new_line = None
        for raw_line in section_text.splitlines():
            match = self.HUNK_HEADER.match(raw_line)
            if match:
                new_line = int(match.group(1))
                continue
            if new_line is None:
                continue
            if raw_line.startswith("+") and not raw_line.startswith("+++"):
                evidence.append(
                    DiffLineEvidence(
                        file_path=file_path,
                        line=new_line,
                        kind="added",
                        content=raw_line[1:],
                    )
                )
                new_line += 1
            elif raw_line.startswith("-") and not raw_line.startswith("---"):
                continue
            else:
                if raw_line.startswith(" "):
                    evidence.append(
                        DiffLineEvidence(
                            file_path=file_path,
                            line=new_line,
                            kind="context",
                            content=raw_line[1:],
                        )
                    )
                new_line += 1
        return evidence
