from pathlib import Path

from code_review.app.review_pipeline import ReviewPipeline
from code_review.domain.prompt_builder import PromptBuilder
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.llm.mock_client import MockLlmClient
from code_review.infrastructure.report.markdown_report_writer import MarkdownReportWriter
from code_review.interfaces.cli import create_demo_repo
from code_review.platform.gitlab.service import GitLabReviewService
from test_gitlab_events import review_payload


def test_gitlab_review_service_dry_run_writes_report(tmp_path: Path):
    repo = create_demo_repo()
    payload = review_payload()
    payload["project"]["git_http_url"] = str(repo)
    payload["merge_request"]["source_sha"] = "HEAD"
    payload["merge_request"]["target_sha"] = "HEAD~1"

    pipeline = ReviewPipeline(
        diff_provider=GitDiffProvider(),
        prompt_builder=PromptBuilder(),
        llm_client=MockLlmClient(),
        report_writer=MarkdownReportWriter(tmp_path / "review-log"),
    )
    service = GitLabReviewService(
        pipeline=pipeline,
        dry_run=True,
        dry_run_repo_path=repo,
    )

    result = service.handle_payload(payload)

    assert result.status == "reviewed"
    assert result.published is False
    assert Path(result.report_path).exists()
