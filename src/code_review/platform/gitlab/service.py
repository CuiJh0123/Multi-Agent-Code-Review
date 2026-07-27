from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from code_review.app.review_pipeline import ReviewPipeline
from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.models import ReviewRequest, ReviewResult
from code_review.infrastructure.config import review_request_from_env
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.git.local_workspace_resolver import LocalWorkspaceResolver
from code_review.platform.gitlab.client import GitLabApiClient
from code_review.platform.gitlab.events import GitLabReviewTrigger, GitLabWebhookParseResult, GitLabWebhookParser
from code_review.platform.gitlab.worktree_resolver import GitLabWorktreeResolver


@dataclass(frozen=True)
class GitLabReviewServiceResult:
    status: str
    reason: str
    report_path: str = ""
    published: bool = False


class GitLabReviewService:
    def __init__(
        self,
        pipeline: ReviewPipeline,
        gitlab_client: Optional[GitLabApiClient] = None,
        dry_run: bool = True,
        dry_run_repo_path: Optional[Path] = None,
    ) -> None:
        self._pipeline = pipeline
        self._gitlab_client = gitlab_client
        self._dry_run = dry_run
        self._dry_run_repo_path = dry_run_repo_path
        self._parser = GitLabWebhookParser()
        self._gitlab_worktree_resolver = GitLabWorktreeResolver()
        self._local_resolver = LocalWorkspaceResolver(
            GitDiffProvider(),
            FileDiffSectionParser(),
            JavaBackendRiskClassifier(),
        )

    def handle_payload(self, payload: dict) -> GitLabReviewServiceResult:
        parsed = self._parser.parse(payload)
        if not parsed.should_review or parsed.trigger is None:
            return GitLabReviewServiceResult(status="ignored", reason=parsed.reason)
        return self.review(parsed)

    def review(self, parsed: GitLabWebhookParseResult) -> GitLabReviewServiceResult:
        assert parsed.trigger is not None
        trigger = parsed.trigger
        request, result = self._run_review(trigger)

        published = False
        if not self._dry_run:
            if self._gitlab_client is None:
                raise RuntimeError("GitLab publishing enabled but GitLabApiClient is not configured")
            self._gitlab_client.publish_merge_request_note(
                project_id=trigger.project_id,
                merge_request_iid=trigger.merge_request_iid,
                body=result.comment_content or result.review_content,
            )
            published = True

        return GitLabReviewServiceResult(
            status="reviewed",
            reason=f"review completed for {request.base_ref}...{request.head_ref}",
            report_path=str(result.report_path),
            published=published,
        )

    def _run_review(self, trigger: GitLabReviewTrigger) -> tuple[ReviewRequest, ReviewResult]:
        if self._dry_run_repo_path is not None:
            request = review_request_from_env(
                repo_path=self._dry_run_repo_path,
                base_ref=trigger.base_ref,
                head_ref=trigger.head_ref,
                use_merge_base=True,
            )
            workspace = self._local_resolver.resolve(request)
            result = self._pipeline.run_workspace(request, workspace)
            return request, result

        request, workspace = self._gitlab_worktree_resolver.resolve(trigger)
        result = self._pipeline.run_workspace(request, workspace)
        return request, result
