from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
import time

from code_review.app.worker_review_agent import WorkerReviewAgent
from code_review.domain.diff_summary_builder import DiffSummaryBuilder
from code_review.domain.models import DiffSummary, FileReviewContext, ReviewFinding, ReviewProfile, ReviewReport, ReviewRequest, ShardReviewResult
from code_review.domain.review_memory import ReviewMemoryMatcher
from code_review.domain.slicing_decision_policy import SlicingDecisionPolicy
from code_review.infrastructure.git.diff_slicer_tool import DiffSlicerTool
from code_review.infrastructure.git.git_diff_provider import GitDiffProvider


class MasterReviewAgent:
    """Orchestrates diff retrieval, slicing decision, worker dispatch, and aggregation."""

    def __init__(
        self,
        diff_provider: GitDiffProvider,
        summary_builder: DiffSummaryBuilder,
        decision_policy: SlicingDecisionPolicy,
        diff_slicer_tool: DiffSlicerTool,
        worker_agent: WorkerReviewAgent,
        max_review_attempts: int = 3,
        retry_backoff_seconds: float = 0.2,
    ) -> None:
        self._diff_provider = diff_provider
        self._summary_builder = summary_builder
        self._decision_policy = decision_policy
        self._diff_slicer_tool = diff_slicer_tool
        self._worker_agent = worker_agent
        self._max_review_attempts = max(1, max_review_attempts)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def run(self, request: ReviewRequest) -> tuple:
        diff_text = self._diff_provider.get_diff(
            repo_path=request.repo_path,
            base_ref=request.base_ref,
            head_ref=request.head_ref,
            use_merge_base=request.use_merge_base,
        )
        diff_summary = self._summary_builder.build(diff_text)
        slicing_decision = self._decision_policy.decide(diff_summary, request)

        if slicing_decision.should_slice:
            shards = self._diff_slicer_tool.slice(
                diff_text=diff_text,
                max_chars_per_shard=request.max_chars_per_shard,
            )
        else:
            shards = [self._diff_slicer_tool.create_single_shard(diff_text)]

        shard_results = self._review_shards(shards, request=request)
        report = ReviewReport(
            request=request,
            diff_summary=diff_summary,
            slicing_decision=slicing_decision,
            shard_results=shard_results,
        )
        return diff_text, report

    def run_prepared(
        self,
        request: ReviewRequest,
        diff_text: str,
        diff_summary: DiffSummary,
        profile: ReviewProfile,
        contexts_by_path: dict,
        context_strategy: str,
    ) -> tuple:
        slicing_decision = self._decision_policy.decide(diff_summary, request)
        changed_files_by_path = {file.display_path: file for file in diff_summary.changed_files}

        if slicing_decision.should_slice:
            shards = self._diff_slicer_tool.slice(
                diff_text=diff_text,
                max_chars_per_shard=request.max_chars_per_shard,
                changed_files_by_path=changed_files_by_path,
                contexts_by_path=contexts_by_path,
                profile=profile,
            )
        else:
            shards = [
                self._diff_slicer_tool.create_single_shard(
                    diff_text,
                    changed_files_by_path=changed_files_by_path,
                    contexts_by_path=contexts_by_path,
                    profile=profile,
                )
            ]

        shard_results = self._review_shards(shards, request=request)
        depth_counts = {}
        for file in diff_summary.changed_files:
            depth_counts[file.context_depth] = depth_counts.get(file.context_depth, 0) + 1
        current_findings = [finding for result in shard_results for finding in result.structured_findings]
        memory_comparison = ReviewMemoryMatcher().compare(current_findings, memory=None)
        report = ReviewReport(
            request=request,
            diff_summary=diff_summary,
            slicing_decision=slicing_decision,
            shard_results=shard_results,
            profile_source=profile.source,
            profile_warnings=profile.validation_warnings,
            context_strategy=context_strategy,
            review_depth_counts=depth_counts,
            memory_comparison=memory_comparison,
        )
        return diff_text, report

    def _review_shards(self, shards: list, request: ReviewRequest) -> List[ShardReviewResult]:
        results_by_index = {}
        pending_shards = list(shards)
        max_rounds = max(1, request.max_review_rounds)

        for review_round in range(1, max_rounds + 1):
            if not pending_shards:
                break
            worker_count = self._worker_count_for_round(
                pending_count=len(pending_shards),
                max_workers=request.max_workers,
                review_round=review_round,
            )
            round_results = self._review_shards_once(
                pending_shards,
                worker_count=worker_count,
                review_round=review_round,
                previous_results_by_index=results_by_index,
            )
            for result in round_results:
                results_by_index[result.shard.index] = result
            pending_shards = [result.shard for result in round_results if not result.success]

        return [results_by_index[shard.index] for shard in sorted(shards, key=lambda item: item.index)]

    def _review_shards_once(
        self,
        shards: list,
        worker_count: int,
        review_round: int,
        previous_results_by_index: dict,
    ) -> List[ShardReviewResult]:
        results: List[ShardReviewResult] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_shard = {
                executor.submit(
                    self._safe_review,
                    shard,
                    review_round,
                    self._previous_attempts(previous_results_by_index, shard),
                ): shard
                for shard in shards
            }
            for future in as_completed(future_to_shard):
                results.append(future.result())

        return sorted(results, key=lambda result: result.shard.index)

    def _worker_count_for_round(self, pending_count: int, max_workers: int, review_round: int) -> int:
        base_workers = max(1, max_workers)
        if review_round > 1:
            base_workers = max(1, min(base_workers, 2))
        return max(1, min(base_workers, pending_count))

    def _previous_attempts(self, previous_results_by_index: dict, shard) -> int:
        previous = previous_results_by_index.get(shard.index)
        return previous.retry_attempts if previous else 0

    def _safe_review(self, shard, review_round: int = 1, previous_attempts: int = 0) -> ShardReviewResult:
        last_error = None
        for attempt in range(1, self._max_review_attempts + 1):
            try:
                result = self._worker_agent.review(shard)
                return ShardReviewResult(
                    shard=result.shard,
                    review_content=result.review_content,
                    success=result.success,
                    error_message=result.error_message,
                    structured_summary=result.structured_summary,
                    structured_findings=result.structured_findings,
                    parser_warnings=result.parser_warnings,
                    retry_attempts=previous_attempts + attempt,
                    review_round=review_round,
                )
            except Exception as error:
                last_error = error
                if attempt < self._max_review_attempts and self._retry_backoff_seconds:
                    time.sleep(self._retry_backoff_seconds * attempt)

        return ShardReviewResult(
            shard=shard,
            review_content="",
            success=False,
            error_message=str(last_error),
            structured_findings=[self._fallback_finding(shard, last_error)],
            retry_attempts=previous_attempts + self._max_review_attempts,
            review_round=review_round,
        )

    def _fallback_finding(self, shard, error: Exception) -> ReviewFinding:
        file = shard.files[0].display_path if shard.files else ""
        problem = "该评审分片在多次重试后仍调用失败，需要人工复核。"
        return ReviewFinding(
            severity="warning",
            category="other",
            file=file,
            method="",
            line=None,
            problem=problem,
            impact="该分片未完成 AI 评审，相关文件可能存在未被模型覆盖的问题。",
            suggestion="人工复核该分片涉及文件；确认模型服务、网络或限流问题后可重新触发 /cr。",
            confidence="low",
            fingerprint=f"worker-failed-{shard.shard_id}",
            code_snippet="",
            shard_id=shard.shard_id,
            raw_content=str(error),
            parser_fallback=True,
        )
