from pathlib import Path

from code_review.app.review_pipeline import ReviewPipeline
from code_review.domain.models import (
    ChangedFile,
    ReviewFinding,
    ReviewRequest,
    ReviewResult,
    ReviewShard,
    ShardReviewResult,
    SlicingDecision,
)
from code_review.domain.prompt_builder import PromptBuilder
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.llm.mock_client import MockLlmClient
from code_review.infrastructure.report.markdown_report_writer import MarkdownReportWriter
from code_review.platform.github.client import GitHubPullRequestInfo
from code_review.interfaces.cli import create_demo_repo
from code_review.platform.github.service import GitHubReviewService
from test_github_events import review_payload


def test_github_review_service_dry_run_writes_report(tmp_path: Path):
    repo = create_demo_repo()
    payload = review_payload()
    payload["pull_request"]["base"]["sha"] = "HEAD~1"
    payload["pull_request"]["head"]["sha"] = "HEAD"

    pipeline = ReviewPipeline(
        diff_provider=GitDiffProvider(),
        prompt_builder=PromptBuilder(),
        llm_client=MockLlmClient(),
        report_writer=MarkdownReportWriter(tmp_path / "review-log"),
    )
    service = GitHubReviewService(
        pipeline=pipeline,
        dry_run=True,
        dry_run_repo_path=repo,
    )

    result = service.handle_payload(payload, event_name="issue_comment")

    assert result.status == "reviewed"
    assert result.published is False
    assert Path(result.report_path).exists()


class InlineRecordingClient:
    def __init__(self):
        self.inline_calls = []

    def publish_pull_request_inline_comment(self, **kwargs):
        self.inline_calls.append(kwargs)
        return {"ok": True}


def test_github_review_service_publishes_only_valid_inline_diff_lines(tmp_path: Path):
    client = InlineRecordingClient()
    service = GitHubReviewService(pipeline=None, github_client=client, dry_run=False)
    pr_trigger = service._parser.parse(review_payload(), event_name="issue_comment").trigger
    pr_info = GitHubPullRequestInfo(
        owner="demo",
        repo="repo",
        pull_number=1,
        repo_url="",
        base_ref="main",
        head_ref="feature",
        base_sha="base",
        head_sha="head",
    )
    changed_file = ChangedFile(
        old_path="src/main/java/com/demo/OrderService.java",
        new_path="src/main/java/com/demo/OrderService.java",
        role="service",
        is_high_risk=True,
    )
    shard = ReviewShard(
        shard_id="shard-1",
        index=1,
        total=1,
        role="service",
        files=[changed_file],
        diff_text="diff",
    )
    valid_finding = ReviewFinding(
        severity="warning",
        category="test",
        file="OrderService.java",
        method="lockOrder",
        line=2,
        problem="缺少测试",
        impact="容易回归",
        suggestion="补测试",
        confidence="medium",
        fingerprint="valid",
    )
    invalid_finding = ReviewFinding(
        severity="warning",
        category="test",
        file="OrderService.java",
        method="lockOrder",
        line=99,
        problem="无法定位",
        impact="",
        suggestion="",
        confidence="low",
        fingerprint="invalid",
    )
    result = ReviewResult(
        diff_text=(
            "diff --git a/src/main/java/com/demo/OrderService.java b/src/main/java/com/demo/OrderService.java\n"
            "--- a/src/main/java/com/demo/OrderService.java\n"
            "+++ b/src/main/java/com/demo/OrderService.java\n"
            "@@ -1,1 +1,2 @@\n"
            " public class OrderService {\n"
            "+  void lockOrder() {}\n"
        ),
        prompt="",
        review_content="",
        report_path=tmp_path / "report.md",
        slicing_decision=SlicingDecision(False, "small"),
        shard_count=1,
        shard_review_results=[
            ShardReviewResult(
                shard=shard,
                review_content="{}",
                structured_findings=[valid_finding, invalid_finding],
            )
        ],
    )

    stats = service._publish_inline_comments(pr_trigger, pr_info, result)

    assert stats.published == 1
    assert stats.skipped == 1
    assert client.inline_calls[0]["path"] == "src/main/java/com/demo/OrderService.java"
    assert client.inline_calls[0]["line"] == 2
