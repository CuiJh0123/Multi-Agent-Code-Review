import subprocess
import tempfile
import os
from pathlib import Path

from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.models import ReviewRequest, ReviewWorkspace
from code_review.infrastructure.config import review_request_from_env
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.git.local_workspace_resolver import LocalWorkspaceResolver
from code_review.platform.github.client import GitHubPullRequestInfo
from code_review.platform.github.events import GitHubReviewTrigger


class GitHubWorktreeResolver:
    """Resolve a GitHub PR into a local review workspace."""

    def __init__(self, token: str = "") -> None:
        self._token = token
        self._local_resolver = LocalWorkspaceResolver(
            GitDiffProvider(),
            FileDiffSectionParser(),
            JavaBackendRiskClassifier(),
        )

    def resolve(self, trigger: GitHubReviewTrigger, pr_info: GitHubPullRequestInfo) -> tuple[ReviewRequest, ReviewWorkspace]:
        worktree = Path(tempfile.mkdtemp(prefix="code-review-github-"))
        clone_url = pr_info.repo_url or trigger.repo_url
        askpass_path = self._create_askpass_script()
        try:
            self._run(worktree.parent, "git", "clone", clone_url, str(worktree), askpass_path=askpass_path)
            if pr_info.base_ref:
                self._run(
                    worktree,
                    "git",
                    "fetch",
                    "origin",
                    f"{pr_info.base_ref}:refs/remotes/origin/{pr_info.base_ref}",
                    askpass_path=askpass_path,
                )
            self._run(
                worktree,
                "git",
                "fetch",
                "origin",
                f"pull/{pr_info.pull_number}/head:refs/remotes/origin/pr-{pr_info.pull_number}",
                askpass_path=askpass_path,
            )
            self._run(worktree, "git", "checkout", pr_info.head_sha, askpass_path=askpass_path)
        finally:
            if askpass_path and askpass_path.exists():
                askpass_path.unlink()

        request = review_request_from_env(
            repo_path=worktree,
            base_ref=pr_info.base_sha,
            head_ref=pr_info.head_sha,
            use_merge_base=True,
        )
        workspace = self._local_resolver.resolve(request)
        return request, ReviewWorkspace(
            worktree_path=workspace.worktree_path,
            repo_tree=workspace.repo_tree,
            base_ref=workspace.base_ref,
            head_ref=workspace.head_ref,
            diff_text=workspace.diff_text,
            changed_files=workspace.changed_files,
            trigger_type="github_pr",
            platform="github",
        )

    def _run(self, cwd: Path, *command: str, askpass_path: Path = None) -> None:
        env = os.environ.copy()
        if askpass_path is not None:
            env["GIT_ASKPASS"] = str(askpass_path)
            env["GIT_TERMINAL_PROMPT"] = "0"
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"command failed: {' '.join(command)}\n"
                f"cwd={cwd}\nstdout={completed.stdout}\nstderr={completed.stderr}"
            )

    def _create_askpass_script(self) -> Path:
        if not self._token:
            return None
        fd, path = tempfile.mkstemp(prefix="code-review-github-askpass-", text=True)
        askpass_path = Path(path)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write("#!/bin/sh\n")
            file.write("case \"$1\" in\n")
            file.write("*Username*) echo x-access-token ;;\n")
            file.write(f"*Password*) echo '{self._token}' ;;\n")
            file.write("*) echo '' ;;\n")
            file.write("esac\n")
        askpass_path.chmod(0o700)
        return askpass_path
