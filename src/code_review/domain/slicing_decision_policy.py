from code_review.domain.models import DiffSummary, ReviewRequest, SlicingDecision


class SlicingDecisionPolicy:
    def decide(self, summary: DiffSummary, request: ReviewRequest) -> SlicingDecision:
        if summary.char_count > request.max_chars_per_shard:
            return SlicingDecision(
                should_slice=True,
                reason=(
                    f"context_budget_exceeded: diff chars {summary.char_count} "
                    f"> max {request.max_chars_per_shard}"
                ),
            )

        if summary.file_count > request.max_files_per_shard:
            return SlicingDecision(
                should_slice=True,
                reason=(
                    f"file_count_exceeded: changed files {summary.file_count} "
                    f"> max {request.max_files_per_shard}"
                ),
            )

        if summary.high_risk_file_count >= request.max_high_risk_files_per_shard:
            return SlicingDecision(
                should_slice=True,
                reason=(
                    f"high_risk_file_threshold_reached: high-risk files {summary.high_risk_file_count} "
                    f">= threshold {request.max_high_risk_files_per_shard}"
                ),
            )

        return SlicingDecision(
            should_slice=False,
            reason="within_single_shard_budget",
        )
