import re
from dataclasses import dataclass
from typing import List

from code_review.domain.diff_sections import FileDiffSection


@dataclass(frozen=True)
class MethodDiffSection:
    method_name: str
    diff_text: str


class JavaMethodDiffSlicer:
    """Best-effort Java method-aware diff slicer.

    It relies on unified diff hunk headers first, for example:
    @@ -10,7 +10,8 @@ public void lockOrder(...) {

    If method names cannot be detected, it returns an empty list so callers can
    fall back to hunk/line splitting.
    """

    _METHOD_IN_HUNK = re.compile(r"@@.*@@\s*(.*)$")
    _METHOD_SIGNATURE = re.compile(
        r"(?:public|private|protected)?\s*"
        r"(?:static\s+)?"
        r"[\w<>\[\], ?]+\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)"
    )

    def slice_by_method(self, section: FileDiffSection) -> List[MethodDiffSection]:
        if not section.display_path.endswith(".java"):
            return []

        lines = section.diff_text.splitlines(keepends=True)
        header_lines: List[str] = []
        hunks: List[List[str]] = []
        current_hunk: List[str] = []

        for line in lines:
            if line.startswith("@@ "):
                if current_hunk:
                    hunks.append(current_hunk)
                current_hunk = [line]
            elif current_hunk:
                current_hunk.append(line)
            else:
                header_lines.append(line)

        if current_hunk:
            hunks.append(current_hunk)

        grouped = {}
        order: List[str] = []
        for hunk in hunks:
            method_name = self._detect_method_name(hunk)
            if not method_name:
                return []
            if method_name not in grouped:
                grouped[method_name] = []
                order.append(method_name)
            grouped[method_name].extend(hunk)

        if not grouped:
            return []

        header_text = "".join(header_lines)
        return [
            MethodDiffSection(
                method_name=method_name,
                diff_text=header_text + "".join(grouped[method_name]),
            )
            for method_name in order
        ]

    def _detect_method_name(self, hunk: List[str]) -> str:
        header = hunk[0]
        hunk_context = self._METHOD_IN_HUNK.match(header)
        if hunk_context:
            method_name = self._extract_method_name(hunk_context.group(1))
            if method_name:
                return method_name

        for line in hunk[:20]:
            content = line[1:] if line.startswith(("+", "-", " ")) else line
            method_name = self._extract_method_name(content)
            if method_name:
                return method_name
        return ""

    def _extract_method_name(self, text: str) -> str:
        text = text.strip()
        if not text or text.startswith(("@", "//", "*")):
            return ""
        match = self._METHOD_SIGNATURE.search(text)
        if not match:
            return ""
        name = match.group("name")
        if name in {"if", "for", "while", "switch", "catch", "return", "new"}:
            return ""
        return name
