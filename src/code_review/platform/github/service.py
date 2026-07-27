from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from code_review.app.review_pipeline import ReviewPipeline
from code_review.domain.diff_hunk_line_parser import DiffHunkLineParser
from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.models import ReviewFinding, ReviewRequest, ReviewResult
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.git.local_workspace_resolver import LocalWorkspaceResolver
from code_review.infrastructure.config import review_request_from_env
from code_review.infrastructure.report.markdown_report_writer import MarkdownReportWriter
from code_review.platform.github.client import GitHubApiClient, GitHubPullRequestInfo
from code_review.platform.github.events import GitHubReviewTrigger, GitHubWebhookParseResult, GitHubWebhookParser
from code_review.platform.github.api_workspace_resolver import GitHubApiWorkspaceResolver


@dataclass(frozen=True)
class GitHubReviewServiceResult:
    status: str
    reason: str
    report_path: str = ""
    published: bool = False


@dataclass(frozen=True)
class GitHubInlinePublishStats:
    published: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {"published": self.published, "skipped": self.skipped, "failed": self.failed}


class GitHubReviewService:
    def __init__(
        self,
        pipeline: ReviewPipeline,
        github_client: Optional[GitHubApiClient] = None,
        token: str = "",
        dry_run: bool = True,
        dry_run_repo_path: Optional[Path] = None,
    ) -> None:
        self._pipeline = pipeline
        self._github_client = github_client
        self._token = token
        self._dry_run = dry_run
        self._dry_run_repo_path = dry_run_repo_path
        self._parser = GitHubWebhookParser()
        self._local_resolver = LocalWorkspaceResolver(
            GitDiffProvider(),
            FileDiffSectionParser(),
            JavaBackendRiskClassifier(),
        )

    def handle_payload(self, payload: dict, event_name: str = "") -> GitHubReviewServiceResult:
        parsed = self._parser.parse(payload, event_name=event_name)
        if not parsed.should_review or parsed.trigger is None:
            return GitHubReviewServiceResult(status="ignored", reason=parsed.reason)
        return self.review(parsed)

    def review(self, parsed: GitHubWebhookParseResult) -> GitHubReviewServiceResult:
        assert parsed.trigger is not None
        trigger = parsed.trigger
        self._publish_processing_comment(trigger)
        request, result, pr_info = self._run_review(trigger)

        published = False
        if not self._dry_run:
            if self._github_client is None:
                raise RuntimeError("GitHub publishing enabled but GitHubApiClient is not configured")
            inline_stats = self._publish_inline_comments(trigger, pr_info, result)
            comment_content = result.comment_content or result.review_content
            if result.report is not None:
                comment_content = MarkdownReportWriter(result.report_path.parent).render_comment(
                    result.report,
                    result.report_path,
                    inline_stats=inline_stats.as_dict(),
                )
            self._github_client.publish_pull_request_comment(
                owner=trigger.owner,
                repo=trigger.repo,
                pull_number=trigger.pull_number,
                body=comment_content,
            )
            published = True

        return GitHubReviewServiceResult(
            status="reviewed",
            reason=f"review completed for {request.base_ref}...{request.head_ref}",
            report_path=str(result.report_path),
            published=published,
        )

    def _run_review(self, trigger: GitHubReviewTrigger) -> tuple[ReviewRequest, ReviewResult, Optional[GitHubPullRequestInfo]]:
        if self._dry_run_repo_path is not None:
            request = review_request_from_env(
                repo_path=self._dry_run_repo_path,
                base_ref=trigger.review_base_ref or "HEAD~1",
                head_ref=trigger.review_head_ref or "HEAD",
                use_merge_base=True,
            )
            workspace = self._local_resolver.resolve(request)
            result = self._pipeline.run_workspace(request, workspace)
            return request, result, None

        if self._github_client is None:
            raise RuntimeError("GitHubApiClient is required when dry-run repo is not configured")
        pr_info = self._github_client.get_pull_request(trigger.owner, trigger.repo, trigger.pull_number)
        request, workspace = GitHubApiWorkspaceResolver(self._github_client).resolve(trigger, pr_info)
        result = self._pipeline.run_workspace(request, workspace)
        return request, result, pr_info

    def _publish_processing_comment(self, trigger: GitHubReviewTrigger) -> None:
        if self._dry_run or self._github_client is None:
            return
        body = "\n".join(
            [
                "## 🤖 Auto Code Review — 处理中 ⏳",
                "",
                "已收到 `/cr` 指令，正在拉取 PR Diff、规划上下文并执行代码评审，请稍候...",
            ]
        )
        try:
            self._github_client.publish_pull_request_comment(
                owner=trigger.owner,
                repo=trigger.repo,
                pull_number=trigger.pull_number,
                body=body,
            )
        except Exception:
            return

    def _publish_inline_comments(
        self,
        trigger: GitHubReviewTrigger,
        pr_info: Optional[GitHubPullRequestInfo],
        result: ReviewResult,
    ) -> GitHubInlinePublishStats:
        if self._dry_run or self._github_client is None or pr_info is None:
            return GitHubInlinePublishStats()

        valid_locations = self._valid_inline_locations(result.diff_text)
        valid_paths = {path for path, _ in valid_locations}
        published = 0
        skipped = 0
        failed = 0
        seen = set()
        max_inline_comments = 10

        for finding in self._dedupe_findings(result.shard_review_results):
            if published >= max_inline_comments:
                skipped += 1
                continue
            if not finding.line or not finding.file:
                skipped += 1
                continue
            resolved_file = self._resolve_finding_file(finding.file, valid_paths)
            if not resolved_file or (resolved_file, finding.line) not in valid_locations:
                skipped += 1
                continue
            key = finding.fingerprint or f"{resolved_file}:{finding.line}:{finding.problem}"
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            try:
                self._github_client.publish_pull_request_inline_comment(
                    owner=trigger.owner,
                    repo=trigger.repo,
                    pull_number=trigger.pull_number,
                    commit_id=pr_info.head_sha,
                    path=resolved_file,
                    line=finding.line,
                    body=self._render_inline_comment_body(finding),
                )
                published += 1
            except Exception:
                failed += 1
        return GitHubInlinePublishStats(published=published, skipped=skipped, failed=failed)

    def _valid_inline_locations(self, diff_text: str) -> set[tuple[str, int]]:
        return {
            (item.file_path, item.line)
            for item in DiffHunkLineParser().parse(diff_text)
            if item.kind == "added"
        }

    def _dedupe_findings(self, shard_results) -> list[ReviewFinding]:
        findings = []
        seen = set()
        for shard_result in shard_results:
            for finding in shard_result.structured_findings:
                key = finding.fingerprint or f"{finding.file}:{finding.line}:{finding.problem}"
                if key in seen:
                    continue
                seen.add(key)
                findings.append(finding)
        severity_rank = {"error": 0, "warning": 1, "suggestion": 2}
        return sorted(findings, key=lambda item: (severity_rank.get(item.severity, 3), item.file, item.line or 0))

    def _resolve_finding_file(self, finding_file: str, valid_paths: set[str]) -> str:
        if finding_file in valid_paths:
            return finding_file
        matches = [path for path in valid_paths if path.endswith(f"/{finding_file}") or path.endswith(finding_file)]
        if len(matches) == 1:
            return matches[0]
        return ""

    def _render_inline_comment_body(self, finding: ReviewFinding) -> str:
        icon = {"error": "❌", "warning": "⚠️", "suggestion": "💡"}.get(finding.severity, "💬")
        label = {"error": "ERROR", "warning": "WARNING", "suggestion": "SUGGESTION"}.get(
            finding.severity,
            finding.severity.upper() or "REVIEW",
        )
        lines = [f"{icon} **[{label}] {finding.problem}**", ""]
        if finding.impact:
            lines.extend([finding.impact, ""])
        if finding.suggestion:
            lines.extend(["建议：", "", finding.suggestion, ""])
        if finding.code_snippet:
            lines.extend(["```", finding.code_snippet[:800], "```", ""])
        lines.append("由 AI Code Review 自动生成。")
        return "\n".join(lines)
