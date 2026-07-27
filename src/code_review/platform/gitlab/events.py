from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class GitLabReviewTrigger:
    project_id: str
    merge_request_iid: int
    repo_url: str
    source_branch: str
    target_branch: str
    source_sha: str
    target_sha: str
    note_body: str
    author_username: str = ""

    @property
    def head_ref(self) -> str:
        return self.source_sha or self.source_branch

    @property
    def base_ref(self) -> str:
        return self.target_sha or self.target_branch


@dataclass(frozen=True)
class GitLabWebhookParseResult:
    should_review: bool
    reason: str
    trigger: Optional[GitLabReviewTrigger] = None


class GitLabWebhookParser:
    """Parse GitLab note webhooks and extract `/cr` MR review triggers."""

    REVIEW_COMMAND = "/cr"

    def parse(self, payload: Dict[str, Any]) -> GitLabWebhookParseResult:
        if not isinstance(payload, dict):
            return GitLabWebhookParseResult(False, "payload is not an object")

        if payload.get("object_kind") != "note":
            return GitLabWebhookParseResult(False, "object_kind is not note")

        attrs = payload.get("object_attributes") or {}
        if attrs.get("noteable_type") != "MergeRequest":
            return GitLabWebhookParseResult(False, "note is not for merge request")

        note_body = str(attrs.get("note") or "").strip()
        if note_body != self.REVIEW_COMMAND:
            return GitLabWebhookParseResult(False, "note body is not /cr")

        mr = payload.get("merge_request") or {}
        project = payload.get("project") or {}
        user = payload.get("user") or {}

        project_id = str(project.get("id") or payload.get("project_id") or "")
        repo_url = str(
            project.get("git_http_url")
            or project.get("git_ssh_url")
            or project.get("web_url")
            or ""
        )
        iid = mr.get("iid") or attrs.get("noteable_iid") or mr.get("id")

        try:
            merge_request_iid = int(iid)
        except (TypeError, ValueError):
            return GitLabWebhookParseResult(False, "missing merge request iid")

        trigger = GitLabReviewTrigger(
            project_id=project_id,
            merge_request_iid=merge_request_iid,
            repo_url=repo_url,
            source_branch=str(mr.get("source_branch") or ""),
            target_branch=str(mr.get("target_branch") or ""),
            source_sha=str(mr.get("last_commit", {}).get("id") or mr.get("source_sha") or ""),
            target_sha=str(mr.get("target_sha") or ""),
            note_body=note_body,
            author_username=str(user.get("username") or ""),
        )
        if not trigger.project_id:
            return GitLabWebhookParseResult(False, "missing project id")
        if not trigger.repo_url:
            return GitLabWebhookParseResult(False, "missing repository url")
        if not trigger.head_ref:
            return GitLabWebhookParseResult(False, "missing source ref")
        if not trigger.base_ref:
            return GitLabWebhookParseResult(False, "missing target ref")

        return GitLabWebhookParseResult(True, "review command accepted", trigger)
