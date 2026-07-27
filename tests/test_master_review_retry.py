from code_review.app.master_review_agent import MasterReviewAgent
from code_review.domain.models import ChangedFile, ReviewRequest, ReviewShard, ShardReviewResult
from pathlib import Path


class FlakyWorker:
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def review(self, shard):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TimeoutError("temporary timeout")
        return ShardReviewResult(shard=shard, review_content='{"summary":"ok","findings":[]}')


class PerShardFlakyWorker:
    def __init__(self, fail_times_by_shard_id: dict) -> None:
        self.fail_times_by_shard_id = dict(fail_times_by_shard_id)
        self.calls_by_shard_id = {}

    def review(self, shard):
        self.calls_by_shard_id[shard.shard_id] = self.calls_by_shard_id.get(shard.shard_id, 0) + 1
        if self.calls_by_shard_id[shard.shard_id] <= self.fail_times_by_shard_id.get(shard.shard_id, 0):
            raise TimeoutError(f"temporary timeout {shard.shard_id}")
        return ShardReviewResult(shard=shard, review_content='{"summary":"ok","findings":[]}')


def shard() -> ReviewShard:
    return ReviewShard(
        shard_id="shard-1",
        index=1,
        total=1,
        role="service",
        files=[ChangedFile("A.java", "A.java", "service", True)],
        diff_text="diff",
    )


def shard_with_id(shard_id: str, index: int) -> ReviewShard:
    return ReviewShard(
        shard_id=shard_id,
        index=index,
        total=2,
        role="service",
        files=[ChangedFile(f"{shard_id}.java", f"{shard_id}.java", "service", True)],
        diff_text="diff",
    )


def agent(worker) -> MasterReviewAgent:
    return MasterReviewAgent(
        diff_provider=None,
        summary_builder=None,
        decision_policy=None,
        diff_slicer_tool=None,
        worker_agent=worker,
        max_review_attempts=3,
        retry_backoff_seconds=0,
    )


def test_master_review_retries_and_succeeds():
    worker = FlakyWorker(fail_times=1)

    result = agent(worker)._safe_review(shard())

    assert result.success is True
    assert result.retry_attempts == 2
    assert worker.calls == 2


def test_master_review_retry_exhaustion_returns_fallback_finding():
    worker = FlakyWorker(fail_times=3)

    result = agent(worker)._safe_review(shard())

    assert result.success is False
    assert result.retry_attempts == 3
    assert "temporary timeout" in result.error_message
    assert result.structured_findings
    assert result.structured_findings[0].problem.startswith("该评审分片")


def test_master_review_compensation_round_retries_only_failed_shards():
    worker = PerShardFlakyWorker({"shard-1": 3, "shard-2": 0})
    review_agent = agent(worker)
    shards = [shard_with_id("shard-1", 1), shard_with_id("shard-2", 2)]
    request = ReviewRequest(
        repo_path=Path("."),
        base_ref="base",
        head_ref="head",
        max_workers=2,
        max_review_rounds=2,
    )

    results = review_agent._review_shards(shards, request)

    assert [result.success for result in results] == [True, True]
    assert results[0].review_round == 2
    assert results[0].retry_attempts == 4
    assert results[1].review_round == 1
    assert results[1].retry_attempts == 1
    assert worker.calls_by_shard_id == {"shard-1": 4, "shard-2": 1}


def test_master_review_compensation_round_stops_at_max_rounds():
    worker = PerShardFlakyWorker({"shard-1": 99})
    review_agent = agent(worker)
    shards = [shard_with_id("shard-1", 1)]
    request = ReviewRequest(
        repo_path=Path("."),
        base_ref="base",
        head_ref="head",
        max_workers=2,
        max_review_rounds=2,
    )

    results = review_agent._review_shards(shards, request)

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].review_round == 2
    assert results[0].retry_attempts == 6
