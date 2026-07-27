from pathlib import Path

from code_review.domain.context_planner import ContextPlanner, ReviewDepth
from code_review.domain.models import ChangedFile, DiffSummary, ReviewWorkspace


def file(path: str, level: str, score: int) -> ChangedFile:
    return ChangedFile(
        old_path=path,
        new_path=path,
        role="service",
        is_high_risk=level in {"P0", "P1"},
        risk_score=score,
        risk_level=level,
    )


def workspace(tmp_path: Path) -> ReviewWorkspace:
    target = tmp_path / "src/main/java/com/demo/OrderService.java"
    target.parent.mkdir(parents=True)
    target.write_text("public class OrderService {}", encoding="utf-8")
    return ReviewWorkspace(
        worktree_path=tmp_path,
        repo_tree=["src/main/java/com/demo/OrderService.java"],
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_text="diff",
        changed_files=[],
    )


def test_context_planner_small_change_uses_full_context(tmp_path):
    summary = DiffSummary(
        char_count=10,
        file_count=1,
        high_risk_file_count=1,
        changed_files=[file("src/main/java/com/demo/OrderService.java", "P1", 50)],
    )

    planned, contexts, strategy = ContextPlanner().plan(workspace(tmp_path), summary)

    assert strategy == "small_change_full_context"
    assert planned.changed_files[0].context_depth == ReviewDepth.FULL_CONTEXT
    assert "OrderService" in contexts["src/main/java/com/demo/OrderService.java"].context_text


def test_context_planner_large_change_summarizes_low_risk(tmp_path):
    files = [file(f"docs/file{i}.md", "P3", 0) for i in range(31)]
    summary = DiffSummary(char_count=10, file_count=31, high_risk_file_count=0, changed_files=files)

    planned, _, strategy = ContextPlanner().plan(workspace(tmp_path), summary)

    assert strategy == "large_change_risk_focused_context"
    assert all(changed.context_depth == ReviewDepth.SUMMARY_ONLY for changed in planned.changed_files)
