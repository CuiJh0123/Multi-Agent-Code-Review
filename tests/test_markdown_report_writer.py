from pathlib import Path

from code_review.domain.models import (
    ChangedFile,
    DiffSummary,
    ReviewFinding,
    ReviewReport,
    ReviewRequest,
    ReviewShard,
    ShardReviewResult,
    SlicingDecision,
)
from code_review.infrastructure.report.markdown_report_writer import MarkdownReportWriter


def test_render_comment_groups_findings_and_hides_metadata_in_details(tmp_path: Path):
    changed_file = ChangedFile(
        old_path="src/main/java/com/demo/OrderService.java",
        new_path="src/main/java/com/demo/OrderService.java",
        role="service",
        is_high_risk=True,
        risk_level="P0",
        risk_score=90,
        risk_reasons=["role:service+25", "diff_signal:exception+15"],
        context_depth="full_context",
    )
    shard = ReviewShard(
        shard_id="shard-1",
        index=1,
        total=1,
        role="service",
        files=[changed_file],
        diff_text="diff",
    )
    finding = ReviewFinding(
        severity="warning",
        category="test",
        file=changed_file.display_path,
        method="lockOrder",
        line=42,
        problem="缺少边界条件测试",
        impact="后续修改时容易出现回归。",
        suggestion="补充空参数和正常参数测试。",
        confidence="medium",
        fingerprint="fp-1",
        code_snippet="assertThat(result).isNotNull();",
    )
    report = ReviewReport(
        request=ReviewRequest(repo_path=tmp_path, base_ref="base123456", head_ref="head123456"),
        diff_summary=DiffSummary(char_count=120, file_count=1, high_risk_file_count=1, changed_files=[changed_file]),
        slicing_decision=SlicingDecision(should_slice=False, reason="small_change"),
        shard_results=[
            ShardReviewResult(
                shard=shard,
                review_content="{}",
                structured_findings=[finding],
            )
        ],
        context_strategy="small_change_full_context",
    )

    comment = MarkdownReportWriter(tmp_path).render_comment(
        report,
        tmp_path / "report.md",
        inline_stats={"published": 1, "skipped": 0, "failed": 0},
    )

    assert "## 🤖 AI Code Review" in comment
    assert "评审结论：未发现明确阻断问题" in comment
    assert "总体评分" not in comment
    assert "💡 Suggestion（可选改进）" in comment
    assert "缺少边界条件测试" in comment
    assert "<summary>📊 Review 详情</summary>" in comment
    assert "Inline 评论 | `1` 条已标注到 Diff" in comment


def test_render_comment_keeps_failed_worker_out_of_warning_table(tmp_path: Path):
    changed_file = ChangedFile(
        old_path="src/main/java/com/demo/PaymentService.java",
        new_path="src/main/java/com/demo/PaymentService.java",
        role="service",
        is_high_risk=True,
        risk_level="P0",
        risk_score=90,
        context_depth="full_context",
    )
    shard = ReviewShard(
        shard_id="shard-1",
        index=1,
        total=1,
        role="service",
        files=[changed_file],
        diff_text="diff",
    )
    report = ReviewReport(
        request=ReviewRequest(repo_path=tmp_path, base_ref="base123456", head_ref="head123456"),
        diff_summary=DiffSummary(char_count=120, file_count=1, high_risk_file_count=1, changed_files=[changed_file]),
        slicing_decision=SlicingDecision(should_slice=False, reason="small_change"),
        shard_results=[
            ShardReviewResult(
                shard=shard,
                review_content="",
                success=False,
                error_message="The read operation timed out",
                retry_attempts=3,
            )
        ],
        context_strategy="small_change_full_context",
    )

    comment = MarkdownReportWriter(tmp_path).render_comment(report, tmp_path / "report.md")

    assert "评审结论：评审不完整，需人工兜底" in comment
    assert "### ⚠️ Warning（建议修改）\n\n- None" in comment
    assert "未完成评审的分片" in comment
    assert "The read operation timed out" in comment
