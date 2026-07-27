from code_review.platform.github.api_workspace_resolver import GitHubApiWorkspaceResolver
from code_review.platform.github.client import GitHubPullRequestFile, GitHubPullRequestInfo, GitHubRepositoryTree
from code_review.platform.github.events import GitHubReviewTrigger


class FakeGitHubClient:
    def list_pull_request_files(self, owner, repo, pull_number):
        return [
            GitHubPullRequestFile(
                filename="src/main/java/com/demo/OrderService.java",
                status="modified",
                patch="@@ -1,3 +1,4 @@\n public class OrderService {\n+  void lockOrder() {}\n }",
            )
        ]

    def get_repository_tree(self, owner, repo, sha):
        return GitHubRepositoryTree(paths=["src/main/java/com/demo/OrderService.java"])

    def get_file_content(self, owner, repo, path, ref):
        return "public class OrderService { void lockOrder() {} }"


def test_github_api_workspace_resolver_builds_workspace_without_clone():
    trigger = GitHubReviewTrigger(
        owner="demo",
        repo="order",
        repo_full_name="demo/order",
        repo_url="https://github.com/demo/order.git",
        pull_number=1,
        comment_body="/cr",
    )
    pr_info = GitHubPullRequestInfo(
        owner="demo",
        repo="order",
        pull_number=1,
        repo_url="https://github.com/demo/order.git",
        base_ref="main",
        head_ref="feature",
        base_sha="base123",
        head_sha="head456",
    )

    request, workspace = GitHubApiWorkspaceResolver(FakeGitHubClient()).resolve(trigger, pr_info)

    assert request.base_ref == "base123"
    assert request.head_ref == "head456"
    assert workspace.platform == "github"
    assert workspace.file_contents["src/main/java/com/demo/OrderService.java"].startswith("public class")
    assert "diff --git a/src/main/java/com/demo/OrderService.java" in workspace.diff_text
    assert workspace.changed_files[0].display_path == "src/main/java/com/demo/OrderService.java"
