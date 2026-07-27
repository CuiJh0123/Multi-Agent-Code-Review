import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request

from code_review.app.review_pipeline import ReviewPipeline
from code_review.domain.prompt_builder import PromptBuilder
from code_review.infrastructure.config import OpenAiCompatibleConfig
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.llm.mock_client import MockLlmClient
from code_review.infrastructure.llm.openai_compatible_client import OpenAiCompatibleClient
from code_review.infrastructure.report.markdown_report_writer import MarkdownReportWriter
from code_review.platform.gitlab.client import GitLabApiClient, GitLabApiConfig
from code_review.platform.gitlab.service import GitLabReviewService
from code_review.platform.github.client import GitHubApiClient, GitHubApiConfig
from code_review.platform.github.service import GitHubReviewService


def create_app() -> FastAPI:
    app = FastAPI(title="AI Code Review Server", version="0.1.0")
    gitlab_review_service = build_gitlab_review_service()
    github_review_service = build_github_review_service()
    gitlab_webhook_secret = os.getenv("CODE_REVIEW_GITLAB_WEBHOOK_SECRET", "")
    github_webhook_secret = os.getenv("CODE_REVIEW_GITHUB_WEBHOOK_SECRET", "")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "UP"}

    @app.post("/webhook/gitlab")
    async def gitlab_webhook(
        request: Request,
        x_gitlab_token: Optional[str] = Header(default=None),
    ) -> dict:
        if gitlab_webhook_secret and x_gitlab_token != gitlab_webhook_secret:
            raise HTTPException(status_code=401, detail="invalid GitLab webhook token")

        payload = await request.json()
        result = gitlab_review_service.handle_payload(payload)
        return {
            "status": result.status,
            "reason": result.reason,
            "report_path": result.report_path,
            "published": result.published,
        }

    @app.post("/webhook/github")
    async def github_webhook(
        request: Request,
        x_github_event: Optional[str] = Header(default=None),
        x_hub_signature_256: Optional[str] = Header(default=None),
    ) -> dict:
        raw_body = await request.body()
        if github_webhook_secret and not is_valid_github_signature(
            raw_body,
            github_webhook_secret,
            x_hub_signature_256 or "",
        ):
            raise HTTPException(status_code=401, detail="invalid GitHub webhook signature")

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON payload")

        try:
            result = github_review_service.handle_payload(payload, event_name=x_github_event or "")
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"GitHub review failed: {error}")
        return {
            "status": result.status,
            "reason": result.reason,
            "report_path": result.report_path,
            "published": result.published,
        }

    return app


def is_valid_github_signature(raw_body: bytes, secret: str, signature_header: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def build_gitlab_review_service() -> GitLabReviewService:
    pipeline = ReviewPipeline(
        diff_provider=GitDiffProvider(),
        prompt_builder=PromptBuilder(),
        llm_client=build_llm_client(),
        report_writer=MarkdownReportWriter(Path(os.getenv("CODE_REVIEW_REPORT_DIR", "./review-log")).resolve()),
    )
    dry_run = os.getenv("CODE_REVIEW_GITLAB_DRY_RUN", "true").lower() != "false"
    dry_run_repo = os.getenv("CODE_REVIEW_GITLAB_DRY_RUN_REPO", "").strip()

    gitlab_client = None
    if not dry_run:
        token = os.getenv("CODE_REVIEW_GITLAB_TOKEN", "").strip()
        if not token:
            raise RuntimeError("CODE_REVIEW_GITLAB_TOKEN is required when dry-run is disabled")
        gitlab_client = GitLabApiClient(
            GitLabApiConfig(
                api_base_url=os.getenv("CODE_REVIEW_GITLAB_API_BASE_URL", "https://gitlab.com/api/v4"),
                private_token=token,
            )
        )

    return GitLabReviewService(
        pipeline=pipeline,
        gitlab_client=gitlab_client,
        dry_run=dry_run,
        dry_run_repo_path=Path(dry_run_repo).resolve() if dry_run_repo else None,
    )


def build_github_review_service() -> GitHubReviewService:
    pipeline = ReviewPipeline(
        diff_provider=GitDiffProvider(),
        prompt_builder=PromptBuilder(),
        llm_client=build_llm_client(),
        report_writer=MarkdownReportWriter(Path(os.getenv("CODE_REVIEW_REPORT_DIR", "./review-log")).resolve()),
    )
    dry_run = os.getenv("CODE_REVIEW_GITHUB_DRY_RUN", "true").lower() != "false"
    dry_run_repo = os.getenv("CODE_REVIEW_GITHUB_DRY_RUN_REPO", "").strip()
    token = os.getenv("CODE_REVIEW_GITHUB_TOKEN", "").strip()

    github_client = None
    if not dry_run:
        if not token:
            raise RuntimeError("CODE_REVIEW_GITHUB_TOKEN is required when GitHub dry-run is disabled")
        github_client = GitHubApiClient(
            GitHubApiConfig(
                api_base_url=os.getenv("CODE_REVIEW_GITHUB_API_BASE_URL", "https://api.github.com"),
                token=token,
            )
        )

    return GitHubReviewService(
        pipeline=pipeline,
        github_client=github_client,
        token=token,
        dry_run=dry_run,
        dry_run_repo_path=Path(dry_run_repo).resolve() if dry_run_repo else None,
    )


def build_llm_client():
    use_mock = os.getenv("CODE_REVIEW_MOCK_LLM", "true").lower() != "false"
    if use_mock:
        return MockLlmClient()
    return OpenAiCompatibleClient(OpenAiCompatibleConfig.from_env())


app = create_app()
