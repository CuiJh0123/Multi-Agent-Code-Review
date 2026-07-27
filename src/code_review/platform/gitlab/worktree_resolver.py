import subprocess
import tempfile
from pathlib import Path

from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.models import ReviewRequest, ReviewWorkspace
from code_review.infrastructure.config import review_request_from_env
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.git.local_workspace_resolver import LocalWorkspaceResolver
from code_review.platform.gitlab.events import GitLabReviewTrigger


class GitLabWorktreeResolver:
    """Resolve a GitLab MR into a local review workspace.

    The first version clones into a temporary directory and leaves it on disk for
    debugging. A production service can add lifecycle cleanup around each job.
    """

    def __init__(self) -> None:
        self._local_resolver = LocalWorkspaceResolver(
            GitDiffProvider(),
            FileDiffSectionParser(),
            JavaBackendRiskClassifier(),
        )

    def resolve(self, trigger: GitLabReviewTrigger) -> tuple[ReviewRequest, ReviewWorkspace]:
        worktree = Path(tempfile.mkdtemp(prefix="code-review-gitlab-"))
        self._run(worktree.parent, "git", "clone", trigger.repo_url, str(worktree))
        self._run(worktree, "git", "fetch", "origin", trigger.source_branch, trigger.target_branch)

        if trigger.source_sha:
            self._run(worktree, "git", "checkout", trigger.source_sha)
        else:
            self._run(worktree, "git", "checkout", trigger.source_branch)

        base_ref = trigger.target_sha or f"origin/{trigger.target_branch}"
        head_ref = trigger.source_sha or "HEAD"
        request = review_request_from_env(
            repo_path=worktree,
            base_ref=base_ref,
            head_ref=head_ref,
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
            trigger_type="gitlab_mr",
            platform="gitlab",
        )

    def _run(self, cwd: Path, *command: str) -> None:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"command failed: {' '.join(command)}\n"
                f"cwd={cwd}\nstdout={completed.stdout}\nstderr={completed.stderr}"
            )
