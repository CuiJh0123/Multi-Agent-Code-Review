import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class GitLabApiConfig:
    api_base_url: str
    private_token: str


class GitLabApiClient:
    """Minimal GitLab API client for MR summary comments."""

    def __init__(self, config: GitLabApiConfig) -> None:
        self._base_url = config.api_base_url.rstrip("/")
        self._private_token = config.private_token

    def publish_merge_request_note(self, project_id: str, merge_request_iid: int, body: str) -> dict:
        encoded_project_id = urllib.parse.quote(str(project_id), safe="")
        path = f"/projects/{encoded_project_id}/merge_requests/{merge_request_iid}/notes"
        payload = json.dumps({"body": body}).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "PRIVATE-TOKEN": self._private_token,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body) if response_body else {}
