import subprocess
from pathlib import Path
from typing import List

from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.domain.models import ChangedFile, ReviewRequest, ReviewWorkspace
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider


class LocalWorkspaceResolver:
    """Build a shared review workspace from a local Git repository."""

    def __init__(
        self,
        diff_provider: GitDiffProvider,
        section_parser: FileDiffSectionParser,
        risk_classifier: JavaBackendRiskClassifier,
    ) -> None:
        self._diff_provider = diff_provider
        self._section_parser = section_parser
        self._risk_classifier = risk_classifier

    def resolve(self, request: ReviewRequest) -> ReviewWorkspace:
        diff_text = self._diff_provider.get_diff(
            repo_path=request.repo_path,
            base_ref=request.base_ref,
            head_ref=request.head_ref,
            use_merge_base=request.use_merge_base,
        )
        changed_files = []
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

        return ReviewWorkspace(
            worktree_path=request.repo_path,
            repo_tree=self._repo_tree(request.repo_path),
            base_ref=request.base_ref,
            head_ref=request.head_ref,
            diff_text=diff_text,
            changed_files=changed_files,
            trigger_type="local",
            platform="local",
        )

    def _repo_tree(self, repo_path: Path) -> List[str]:
        completed = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo_path),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            return []
        return [line.strip() for line in completed.stdout.splitlines() if line.strip()]
