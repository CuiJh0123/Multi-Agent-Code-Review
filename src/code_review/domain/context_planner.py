from dataclasses import replace
from pathlib import Path
from typing import Dict, List

from code_review.domain.models import ChangedFile, DiffSummary, FileReviewContext, ReviewWorkspace


class ReviewDepth:
    FULL_CONTEXT = "full_context"
    DIFF_ONLY = "diff_only"
    SUMMARY_ONLY = "summary_only"


class ContextPlanner:
    def __init__(self, max_context_chars: int = 60000, max_file_context_chars: int = 12000) -> None:
        self._max_context_chars = max_context_chars
        self._max_file_context_chars = max_file_context_chars

    def plan(self, workspace: ReviewWorkspace, summary: DiffSummary) -> tuple:
        strategy = self._strategy(summary.file_count)
        remaining = self._max_context_chars
        contexts: Dict[str, FileReviewContext] = {}
        planned_files: List[ChangedFile] = []

        ordered = sorted(
            summary.changed_files,
            key=lambda file: (self._risk_rank(file.risk_level), file.risk_score),
            reverse=True,
        )
        depth_by_path: Dict[str, str] = {}
        reason_by_path: Dict[str, str] = {}

        for file in ordered:
            depth = self._choose_depth(file, summary.file_count, remaining)
            reason = self._reason(file, summary.file_count, depth)
            context_text = ""
            if depth == ReviewDepth.FULL_CONTEXT:
                context_text = workspace.file_contents.get(file.display_path, "")
                if not context_text:
                    context_text = self._load_file_context(workspace.worktree_path, file.display_path)
                if len(context_text) > self._max_file_context_chars:
                    context_text = context_text[: self._max_file_context_chars] + "\n...[truncated by context budget]"
                remaining -= len(context_text)
                if remaining < 0:
                    remaining = 0

            depth_by_path[file.display_path] = depth
            reason_by_path[file.display_path] = reason
            contexts[file.display_path] = FileReviewContext(
                file_path=file.display_path,
                depth=depth,
                reason=reason,
                context_text=context_text,
            )

        for file in summary.changed_files:
            planned_files.append(
                replace(
                    file,
                    context_depth=depth_by_path.get(file.display_path, ReviewDepth.DIFF_ONLY),
                    context_reason=reason_by_path.get(file.display_path, ""),
                )
            )

        planned_summary = DiffSummary(
            char_count=summary.char_count,
            file_count=summary.file_count,
            high_risk_file_count=summary.high_risk_file_count,
            changed_files=planned_files,
        )
        return planned_summary, contexts, strategy

    def _strategy(self, file_count: int) -> str:
        if file_count <= 10:
            return "small_change_full_context"
        if file_count <= 30:
            return "medium_change_risk_budgeted_context"
        return "large_change_risk_focused_context"

    def _choose_depth(self, file: ChangedFile, file_count: int, remaining_budget: int) -> str:
        if file.risk_level == "P3":
            return ReviewDepth.SUMMARY_ONLY if file_count > 30 else ReviewDepth.DIFF_ONLY
        if file_count <= 10:
            return ReviewDepth.FULL_CONTEXT if remaining_budget > 0 else ReviewDepth.DIFF_ONLY
        if file_count <= 30:
            if file.risk_level in {"P0", "P1"} and remaining_budget > 0:
                return ReviewDepth.FULL_CONTEXT
            return ReviewDepth.DIFF_ONLY
        if file.risk_level in {"P0", "P1"} and remaining_budget > 0:
            return ReviewDepth.FULL_CONTEXT
        if file.risk_level == "P2":
            return ReviewDepth.DIFF_ONLY
        return ReviewDepth.SUMMARY_ONLY

    def _reason(self, file: ChangedFile, file_count: int, depth: str) -> str:
        return f"{self._strategy(file_count)}; risk_level={file.risk_level}; risk_score={file.risk_score}; depth={depth}"

    def _load_file_context(self, worktree_path: Path, display_path: str) -> str:
        target = worktree_path / display_path
        if display_path == "/dev/null" or not target.exists() or not target.is_file():
            return ""
        try:
            data = target.read_bytes()
        except OSError:
            return ""
        if b"\x00" in data[:4096]:
            return "[binary file omitted]"
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

    def _risk_rank(self, level: str) -> int:
        return {"P0": 4, "P1": 3, "P2": 2, "P3": 1}.get(level, 0)
