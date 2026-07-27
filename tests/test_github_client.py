from code_review.platform.github.client import GitHubApiClient, GitHubApiConfig


class RecordingGitHubClient(GitHubApiClient):
    def __init__(self):
        super().__init__(GitHubApiConfig(api_base_url="https://api.github.test", token="token"))
        self.calls = []

    def _request_json(self, method: str, path: str, payload: dict = None) -> dict:
        self.calls.append((method, path, payload))
        return {"ok": True}


def test_publish_pull_request_inline_comment_payload():
    client = RecordingGitHubClient()

    client.publish_pull_request_inline_comment(
        owner="demo",
        repo="repo",
        pull_number=7,
        commit_id="head-sha",
        path="src/main/java/App.java",
        line=12,
        body="review body",
    )

    assert client.calls == [
        (
            "POST",
            "/repos/demo/repo/pulls/7/comments",
            {
                "body": "review body",
                "commit_id": "head-sha",
                "path": "src/main/java/App.java",
                "line": 12,
                "side": "RIGHT",
            },
        )
    ]
