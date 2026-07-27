from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class GitHubReviewTrigger:
    owner: str
    repo: str
    repo_full_name: str
    repo_url: str
    pull_number: int
    comment_body: str
    author_login: str = ""
    base_ref: str = ""
    head_ref: str = ""
    base_sha: str = ""
    head_sha: str = ""

    @property
    def review_base_ref(self) -> str:
        return self.base_sha or self.base_ref

    @property
    def review_head_ref(self) -> str:
        return self.head_sha or self.head_ref


@dataclass(frozen=True)
class GitHubWebhookParseResult:
    should_review: bool
    reason: str
    trigger: Optional[GitHubReviewTrigger] = None


class GitHubWebhookParser:
    """Parse GitHub issue_comment webhooks and extract `/cr` PR review triggers."""

    REVIEW_COMMAND = "/cr"

    def parse(self, payload: Dict[str, Any], event_name: str = "") -> GitHubWebhookParseResult:
        if not isinstance(payload, dict):
            return GitHubWebhookParseResult(False, "payload is not an object")

        if event_name and event_name != "issue_comment":
            return GitHubWebhookParseResult(False, "event is not issue_comment")

        if payload.get("action") != "created":
            return GitHubWebhookParseResult(False, "action is not created")

        issue = payload.get("issue") or {}
        if "pull_request" not in issue:
            return GitHubWebhookParseResult(False, "comment is not on pull request")

        comment = payload.get("comment") or {}
        comment_body = str(comment.get("body") or "").strip()
        if comment_body != self.REVIEW_COMMAND:
            return GitHubWebhookParseResult(False, "comment body is not /cr")

        repository = payload.get("repository") or {}
        full_name = str(repository.get("full_name") or "")
        if "/" not in full_name:
            return GitHubWebhookParseResult(False, "missing repository full_name")
        owner, repo = full_name.split("/", 1)

        try:
            pull_number = int(issue.get("number"))
        except (TypeError, ValueError):
            return GitHubWebhookParseResult(False, "missing pull request number")

        trigger = GitHubReviewTrigger(
            owner=owner,
            repo=repo,
            repo_full_name=full_name,
            repo_url=str(repository.get("clone_url") or repository.get("html_url") or ""),
            pull_number=pull_number,
            comment_body=comment_body,
            author_login=str((comment.get("user") or {}).get("login") or ""),
            base_ref=str(payload.get("pull_request", {}).get("base", {}).get("ref") or ""),
            head_ref=str(payload.get("pull_request", {}).get("head", {}).get("ref") or ""),
            base_sha=str(payload.get("pull_request", {}).get("base", {}).get("sha") or ""),
            head_sha=str(payload.get("pull_request", {}).get("head", {}).get("sha") or ""),
        )
        if not trigger.repo_url:
            return GitHubWebhookParseResult(False, "missing repository clone url")

        return GitHubWebhookParseResult(True, "review command accepted", trigger)
