import subprocess
from pathlib import Path


class GitDiffProvider:
    """通过 git diff 获取待评审代码。

    支持两种比较方式：
    1. git diff base head：精确比较两个 ref，适合 commit 到 commit。
    2. git diff base...head：比较 merge-base 到 head，适合 main/master 到 feature branch。
    """

    def get_diff(self, repo_path: Path, base_ref: str, head_ref: str, use_merge_base: bool = False) -> str:
        self._ensure_valid_repo(repo_path)
        self._ensure_valid_ref(repo_path, base_ref)
        self._ensure_valid_ref(repo_path, head_ref)

        diff_range = f"{base_ref}...{head_ref}" if use_merge_base else None
        command = ["git", "diff", diff_range] if diff_range else ["git", "diff", base_ref, head_ref]
        completed = subprocess.run(
            command,
            cwd=str(repo_path),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "git diff 执行失败："
                f"command={' '.join(command)}, "
                f"repo={repo_path}, "
                f"stderr={completed.stderr.strip()}"
            )
        if not completed.stdout.strip():
            mode = "merge-base" if use_merge_base else "direct"
            raise RuntimeError(
                "git diff 为空，没有可评审的代码变更："
                f"repo={repo_path}, base={base_ref}, head={head_ref}, mode={mode}"
            )
        return completed.stdout

    def _ensure_valid_repo(self, repo_path: Path) -> None:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(repo_path),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"不是有效 Git 仓库：repo={repo_path}, stderr={completed.stderr.strip()}")

    def _ensure_valid_ref(self, repo_path: Path, ref: str) -> None:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=str(repo_path),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Git ref 不存在或不是 commit：repo={repo_path}, ref={ref}")
