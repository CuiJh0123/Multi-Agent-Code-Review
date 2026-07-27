from pathlib import Path
from typing import Dict, List

from code_review.domain.java_symbol_extractor import JavaSymbolExtractor
from code_review.domain.models import FileReviewContext, ReviewWorkspace


class CallChainResolver:
    """Best-effort Java backend direct context resolver.

    This is intentionally heuristic. It adds related-file hints for reports and
    prompt context, but it does not claim to build a complete call graph.
    """

    RELATED_TOKENS = (
        "Controller.java",
        "Service.java",
        "Repository.java",
        "Mapper.java",
        "Mapper.xml",
        "DTO.java",
        "Entity.java",
        "Consumer.java",
        "Job.java",
    )

    def __init__(self, symbol_extractor: JavaSymbolExtractor = None, max_related_files: int = 5) -> None:
        self._symbol_extractor = symbol_extractor or JavaSymbolExtractor()
        self._max_related_files = max_related_files

    def enrich(self, workspace: ReviewWorkspace, contexts: Dict[str, FileReviewContext]) -> Dict[str, FileReviewContext]:
        if workspace.file_contents:
            return contexts
        java_files = [path for path in workspace.repo_tree if path.endswith(".java") or path.endswith("Mapper.xml")]
        result = dict(contexts)
        for file_path, context in contexts.items():
            if not file_path.endswith(".java") or context.depth != "full_context":
                continue
            symbols = self._symbol_extractor.extract(workspace.worktree_path / file_path, file_path)
            related = self._find_related(file_path, symbols.class_name, java_files)
            if not related:
                continue
            related_text = self._load_related_context(workspace.worktree_path, related)
            result[file_path] = FileReviewContext(
                file_path=context.file_path,
                depth=context.depth,
                reason=context.reason + "; call_chain_context=best_effort",
                context_text=context.context_text + related_text,
                related_files=related,
            )
        return result

    def _find_related(self, path: str, class_name: str, candidates: List[str]) -> List[str]:
        path_parts = set(Path(path).parts)
        related: List[str] = []
        stem = Path(path).stem
        base_tokens = {stem.replace("Impl", ""), class_name.replace("Impl", "") if class_name else stem}

        for candidate in candidates:
            if candidate == path:
                continue
            candidate_name = Path(candidate).name
            candidate_parts = set(Path(candidate).parts)
            shared_parts = len(path_parts.intersection(candidate_parts))
            name_related = any(token and token in candidate_name for token in base_tokens)
            role_related = any(token in candidate_name for token in self.RELATED_TOKENS)
            if name_related or (role_related and shared_parts >= 2):
                related.append(candidate)
            if len(related) >= self._max_related_files:
                break
        return related

    def _load_related_context(self, worktree_path: Path, related: List[str]) -> str:
        chunks: List[str] = []
        for path in related:
            target = worktree_path / path
            if not target.exists() or not target.is_file():
                continue
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks.append(f"\n\n[Related context: {path}]\n{text[:4000]}")
        return "".join(chunks)
