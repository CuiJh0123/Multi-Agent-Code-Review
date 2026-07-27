import re
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class FileDiffSection:
    old_path: str
    new_path: str
    diff_text: str

    @property
    def display_path(self) -> str:
        return self.new_path if self.new_path != "/dev/null" else self.old_path


class FileDiffSectionParser:
    """Parse unified git diff text into file-level sections."""

    _DIFF_HEADER = re.compile(r"^diff --git a/(.*?) b/(.*?)$")

    def parse(self, diff_text: str) -> List[FileDiffSection]:
        sections: List[List[str]] = []
        current: List[str] = []

        for line in diff_text.splitlines(keepends=True):
            if line.startswith("diff --git ") and current:
                sections.append(current)
                current = [line]
            else:
                current.append(line)

        if current:
            sections.append(current)

        parsed: List[FileDiffSection] = []
        for section_lines in sections:
            section_text = "".join(section_lines)
            old_path, new_path = self._extract_paths(section_lines)
            parsed.append(
                FileDiffSection(
                    old_path=old_path,
                    new_path=new_path,
                    diff_text=section_text,
                )
            )
        return parsed

    def _extract_paths(self, section_lines: List[str]) -> tuple:
        for line in section_lines:
            match = self._DIFF_HEADER.match(line.strip())
            if match:
                return match.group(1), match.group(2)

        old_path = "unknown"
        new_path = "unknown"
        for line in section_lines:
            if line.startswith("--- "):
                old_path = self._clean_diff_path(line[4:].strip())
            elif line.startswith("+++ "):
                new_path = self._clean_diff_path(line[4:].strip())
        return old_path, new_path

    def _clean_diff_path(self, path: str) -> str:
        if path == "/dev/null":
            return path
        if path.startswith("a/") or path.startswith("b/"):
            return path[2:]
        return path
