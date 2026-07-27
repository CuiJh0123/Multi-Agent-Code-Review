from pathlib import Path
from tempfile import gettempdir
from typing import Dict, List

from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.models import ChangedFile, ReviewRequest, ReviewWorkspace
from code_review.infrastructure.config import review_request_from_env
from code_review.platform.github.client import GitHubApiClient, GitHubPullRequestFile, GitHubPullRequestInfo
from code_review.platform.github.events import GitHubReviewTrigger


class GitHubApiWorkspaceResolver:
    """Resolve a GitHub PR using GitHub APIs instead of cloning the repository."""

    def __init__(
        self,
        github_client: GitHubApiClient,
        section_parser: FileDiffSectionParser = None,
        risk_classifier: JavaBackendRiskClassifier = None,
    ) -> None:
        self._github_client = github_client
        self._section_parser = section_parser or FileDiffSectionParser()
        self._risk_classifier = risk_classifier or JavaBackendRiskClassifier()

    def resolve(self, trigger: GitHubReviewTrigger, pr_info: GitHubPullRequestInfo) -> tuple[ReviewRequest, ReviewWorkspace]:
        pr_files = self._github_client.list_pull_request_files(trigger.owner, trigger.repo, trigger.pull_number)
        diff_text = self._build_unified_diff(pr_files)
        changed_files = self._changed_files(diff_text)
        repo_tree = self._github_client.get_repository_tree(trigger.owner, trigger.repo, pr_info.head_sha).paths
        file_contents = self._load_changed_file_contents(trigger, pr_info, changed_files)

        request = review_request_from_env(
            repo_path=Path(gettempdir()) / f"github-api-workspace-{trigger.owner}-{trigger.repo}-{trigger.pull_number}",
            base_ref=pr_info.base_sha,
            head_ref=pr_info.head_sha,
            use_merge_base=True,
        )
        workspace = ReviewWorkspace(
            worktree_path=request.repo_path,
            repo_tree=repo_tree,
            base_ref=request.base_ref,
            head_ref=request.head_ref,
            diff_text=diff_text,
            changed_files=changed_files,
            trigger_type="github_pr",
            platform="github",
            file_contents=file_contents,
        )
        return request, workspace

    def _build_unified_diff(self, pr_files: List[GitHubPullRequestFile]) -> str:
        chunks: List[str] = []
        for item in pr_files:
            old_path = item.previous_filename if item.status == "renamed" and item.previous_filename else item.filename
            new_path = item.filename
            chunks.append(f"diff --git a/{old_path} b/{new_path}\n")
            if item.status == "added":
                chunks.append("new file mode 100644\n")
                chunks.append("--- /dev/null\n")
                chunks.append(f"+++ b/{new_path}\n")
            elif item.status == "removed":
                chunks.append(f"--- a/{old_path}\n")
                chunks.append("+++ /dev/null\n")
            else:
                chunks.append(f"--- a/{old_path}\n")
                chunks.append(f"+++ b/{new_path}\n")
            if item.patch:
                chunks.append(item.patch.rstrip("\n") + "\n")
            else:
                chunks.append("@@ -0,0 +0,0 @@\n")
                chunks.append("[patch omitted by GitHub API]\n")
        diff_text = "".join(chunks)
        if not diff_text.strip():
            raise RuntimeError("GitHub PR diff is empty")
        return diff_text

    def _changed_files(self, diff_text: str) -> List[ChangedFile]:
        changed_files: List[ChangedFile] = []
        for section in self._section_parser.parse(diff_text):
            role, is_high_risk, risk_tags = self._risk_classifier.classify(section.display_path)
            changed_files.append(
                ChangedFile(
                    old_path=section.old_path,
                    new_path=section.new_path,
                    role=role,
                    is_high_risk=is_high_risk,
                    risk_tags=risk_tags,
                )
            )
        return changed_files

    def _load_changed_file_contents(
        self,
        trigger: GitHubReviewTrigger,
        pr_info: GitHubPullRequestInfo,
        changed_files: List[ChangedFile],
    ) -> Dict[str, str]:
        contents: Dict[str, str] = {}
        for file in changed_files:
            path = file.display_path
            if path == "/dev/null":
                continue
            try:
                content = self._github_client.get_file_content(trigger.owner, trigger.repo, path, pr_info.head_sha)
            except Exception:
                content = ""
            if content:
                contents[path] = content
        return contents
