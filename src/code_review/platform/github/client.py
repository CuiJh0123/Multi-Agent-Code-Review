import json
import base64
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class GitHubApiConfig:
    api_base_url: str
    token: str


@dataclass(frozen=True)
class GitHubPullRequestInfo:
    owner: str
    repo: str
    pull_number: int
    repo_url: str
    base_ref: str
    head_ref: str
    base_sha: str
    head_sha: str


@dataclass(frozen=True)
class GitHubPullRequestFile:
    filename: str
    status: str
    patch: str = ""
    previous_filename: str = ""


@dataclass(frozen=True)
class GitHubRepositoryTree:
    paths: List[str] = field(default_factory=list)


class GitHubApiClient:
    """Minimal GitHub REST API client for PR metadata and PR comments."""

    def __init__(self, config: GitHubApiConfig) -> None:
        self._base_url = config.api_base_url.rstrip("/")
        self._token = config.token

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> GitHubPullRequestInfo:
        payload = self._request_json("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}")
        head = payload.get("head") or {}
        base = payload.get("base") or {}
        base_repo = base.get("repo") or {}
        return GitHubPullRequestInfo(
            owner=owner,
            repo=repo,
            pull_number=pull_number,
            repo_url=str(base_repo.get("clone_url") or ""),
            base_ref=str(base.get("ref") or ""),
            head_ref=str(head.get("ref") or ""),
            base_sha=str(base.get("sha") or ""),
            head_sha=str(head.get("sha") or ""),
        )

    def publish_pull_request_comment(self, owner: str, repo: str, pull_number: int, body: str) -> dict:
        return self._request_json(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pull_number}/comments",
            {"body": body},
        )

    def publish_pull_request_inline_comment(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        commit_id: str,
        path: str,
        line: int,
        body: str,
    ) -> dict:
        return self._request_json(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/comments",
            {
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
                "side": "RIGHT",
            },
        )

    def list_pull_request_files(self, owner: str, repo: str, pull_number: int) -> List[GitHubPullRequestFile]:
        items = self._request_json("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}/files?per_page=100")
        if not isinstance(items, list):
            return []
        return [
            GitHubPullRequestFile(
                filename=str(item.get("filename") or ""),
                status=str(item.get("status") or "modified"),
                patch=str(item.get("patch") or ""),
                previous_filename=str(item.get("previous_filename") or ""),
            )
            for item in items
            if item.get("filename")
        ]

    def get_repository_tree(self, owner: str, repo: str, sha: str) -> GitHubRepositoryTree:
        payload = self._request_json("GET", f"/repos/{owner}/{repo}/git/trees/{sha}?recursive=1")
        tree = payload.get("tree") if isinstance(payload, dict) else []
        paths = [
            str(item.get("path"))
            for item in tree
            if isinstance(item, dict) and item.get("type") == "blob" and item.get("path")
        ]
        return GitHubRepositoryTree(paths=paths)

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(ref, safe="")
        payload = self._request_json("GET", f"/repos/{owner}/{repo}/contents/{encoded_path}?ref={encoded_ref}")
        if not isinstance(payload, dict):
            return ""
        if payload.get("encoding") != "base64":
            return ""
        raw_content = str(payload.get("content") or "")
        try:
            return base64.b64decode(raw_content).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _request_json(self, method: str, path: str, payload: dict = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}


def with_token_in_clone_url(repo_url: str, token: str) -> str:
    if not token or not repo_url.startswith("https://"):
        return repo_url
    parsed = urllib.parse.urlparse(repo_url)
    if parsed.username or parsed.password:
        return repo_url
    netloc = f"x-access-token:{urllib.parse.quote(token, safe='')}@{parsed.netloc}"
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))
