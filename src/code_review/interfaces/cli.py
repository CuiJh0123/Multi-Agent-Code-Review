import argparse
import subprocess
import tempfile
from pathlib import Path

from code_review.app.review_pipeline import ReviewPipeline
from code_review.domain.models import ReviewRequest
from code_review.domain.prompt_builder import PromptBuilder
from code_review.infrastructure.config import OpenAiCompatibleConfig
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider
from code_review.infrastructure.llm.mock_client import MockLlmClient
from code_review.infrastructure.llm.openai_compatible_client import OpenAiCompatibleClient
from code_review.infrastructure.report.markdown_report_writer import MarkdownReportWriter


def main() -> None:
    args = parse_args()

    if args.mock:
        repo_path = create_demo_repo()
        base_ref = "HEAD~1"
        head_ref = "HEAD"
        llm_client = MockLlmClient()
    else:
        repo_path = Path(args.repo).resolve()
        base_ref = args.base
        head_ref = args.head
        llm_client = OpenAiCompatibleClient(OpenAiCompatibleConfig.from_env())

    pipeline = ReviewPipeline(
        diff_provider=GitDiffProvider(),
        prompt_builder=PromptBuilder(),
        llm_client=llm_client,
        report_writer=MarkdownReportWriter(Path(args.output).resolve()),
    )
    result = pipeline.run(
        ReviewRequest(
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            use_merge_base=args.merge_base,
            max_chars_per_shard=args.max_chars_per_shard,
            max_files_per_shard=args.max_files_per_shard,
            max_high_risk_files_per_shard=args.max_high_risk_files_per_shard,
            max_workers=args.max_workers,
            max_review_rounds=args.max_review_rounds,
        )
    )

    print(f"repo_path={repo_path}")
    print(f"base_ref={base_ref}")
    print(f"head_ref={head_ref}")
    print(f"diff_mode={'merge-base(base...head)' if args.merge_base else 'direct(base head)'}")
    print(f"diff_length={len(result.diff_text)}")
    print(f"slicing_decision={result.slicing_decision.should_slice}")
    print(f"slicing_reason={result.slicing_decision.reason}")
    print(f"shard_count={result.shard_count}")
    print(f"review_report={result.report_path}")
    print("review_content:")
    print(result.review_content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python Code Review Pipeline")
    parser.add_argument("--repo", default=".", help="待评审 Git 仓库路径")
    parser.add_argument(
        "--base",
        default="HEAD~1",
        help="git diff 的起点 ref，可以是 commit hash、branch、tag、HEAD~n",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="git diff 的终点 ref，可以是 commit hash、branch、tag、HEAD~n",
    )
    parser.add_argument(
        "--merge-base",
        action="store_true",
        help="使用 git diff base...head，适合评审某个 feature branch 相对 main/master 的全部变更",
    )
    parser.add_argument("--output", default="./review-log", help="评审报告输出目录")
    parser.add_argument("--mock", action="store_true", help="使用本地 mock 仓库和 mock LLM 响应")
    parser.add_argument(
        "--max-chars-per-shard",
        type=int,
        default=12000,
        help="单个评审 shard 最大字符数，超过后触发切片",
    )
    parser.add_argument(
        "--max-files-per-shard",
        type=int,
        default=5,
        help="单个评审 shard 最大变更文件数，超过后触发切片",
    )
    parser.add_argument(
        "--max-high-risk-files-per-shard",
        type=int,
        default=2,
        help="高风险 Java 后端文件数量阈值，达到后触发切片",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="多 shard 评审时最大并发 worker 数",
    )
    parser.add_argument(
        "--max-review-rounds",
        type=int,
        default=3,
        help="失败分片最大补偿评审轮数",
    )
    return parser.parse_args()


def create_demo_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="python-code-review-demo-"))
    run(repo, "git", "init")
    run(repo, "git", "config", "user.email", "local-demo@example.com")
    run(repo, "git", "config", "user.name", "local-demo")

    target = repo / "OrderService.java"
    target.write_text(
        "public class OrderService {\n"
        "    public boolean lockOrder(String userId) {\n"
        "        return true;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    run(repo, "git", "add", "OrderService.java")
    run(repo, "git", "commit", "-m", "init order service")

    target.write_text(
        "public class OrderService {\n"
        "    public boolean lockOrder(String userId) {\n"
        "        if (userId == null || userId.trim().isEmpty()) {\n"
        "            return false;\n"
        "        }\n"
        "        return true;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    run(repo, "git", "add", "OrderService.java")
    run(repo, "git", "commit", "-m", "add user id validation")
    return repo


def run(cwd: Path, *command: str) -> None:
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
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )


if __name__ == "__main__":
    main()
