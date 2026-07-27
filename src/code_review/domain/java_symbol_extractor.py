import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class JavaSymbols:
    path: str
    package: str = ""
    class_name: str = ""
    method_names: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    injected_fields: List[str] = field(default_factory=list)


class JavaSymbolExtractor:
    CLASS_PATTERN = re.compile(r"\b(?:class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
    METHOD_PATTERN = re.compile(
        r"\b(?:public|protected|private)?\s*(?:static\s+)?[A-Za-z0-9_<>,\[\]?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
    )

    def extract(self, file_path: Path, relative_path: str = "") -> JavaSymbols:
        if not file_path.exists() or file_path.suffix != ".java":
            return JavaSymbols(path=relative_path or str(file_path))
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return JavaSymbols(path=relative_path or str(file_path))

        package = ""
        imports: List[str] = []
        annotations: List[str] = []
        injected_fields: List[str] = []
        lines = text.splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("package "):
                package = stripped.removeprefix("package ").rstrip(";")
            elif stripped.startswith("import "):
                imports.append(stripped.removeprefix("import ").rstrip(";"))
            elif stripped.startswith("@"):
                annotations.append(stripped.split("(")[0])
                if stripped in {"@Autowired", "@Resource"} and index + 1 < len(lines):
                    injected_fields.append(lines[index + 1].strip())

        class_match = self.CLASS_PATTERN.search(text)
        method_names = [
            match.group(1)
            for match in self.METHOD_PATTERN.finditer(text)
            if match.group(1) not in {"if", "for", "while", "switch", "catch", "new", "return"}
        ]
        return JavaSymbols(
            path=relative_path or str(file_path),
            package=package,
            class_name=class_match.group(1) if class_match else "",
            method_names=list(dict.fromkeys(method_names)),
            annotations=list(dict.fromkeys(annotations)),
            imports=list(dict.fromkeys(imports)),
            injected_fields=list(dict.fromkeys(injected_fields)),
        )
