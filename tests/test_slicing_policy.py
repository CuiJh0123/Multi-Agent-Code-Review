from pathlib import Path

from code_review.domain.models import ChangedFile, DiffSummary, ReviewRequest
from code_review.domain.slicing_decision_policy import SlicingDecisionPolicy


def request(**kwargs):
    defaults = {
        "repo_path": Path("."),
        "base_ref": "HEAD~1",
        "head_ref": "HEAD",
        "max_chars_per_shard": 1000,
        "max_files_per_shard": 3,
        "max_high_risk_files_per_shard": 2,
    }
    defaults.update(kwargs)
    return ReviewRequest(**defaults)


def changed_file(name: str, high_risk: bool = False) -> ChangedFile:
    return ChangedFile(
        old_path=name,
        new_path=name,
        role="service",
        is_high_risk=high_risk,
        risk_tags=["core_business"] if high_risk else [],
    )


def test_single_shard_decision_when_within_all_thresholds():
    summary = DiffSummary(
        char_count=100,
        file_count=1,
        high_risk_file_count=0,
        changed_files=[changed_file("Demo.java")],
    )

    decision = SlicingDecisionPolicy().decide(summary, request())

    assert decision.should_slice is False
    assert decision.reason == "within_single_shard_budget"


def test_context_budget_slicing_decision():
    summary = DiffSummary(
        char_count=1001,
        file_count=1,
        high_risk_file_count=0,
        changed_files=[changed_file("Demo.java")],
    )

    decision = SlicingDecisionPolicy().decide(summary, request())

    assert decision.should_slice is True
    assert "context_budget_exceeded" in decision.reason


def test_file_count_slicing_decision():
    files = [changed_file(f"Demo{i}.java") for i in range(4)]
    summary = DiffSummary(
        char_count=100,
        file_count=len(files),
        high_risk_file_count=0,
        changed_files=files,
    )

    decision = SlicingDecisionPolicy().decide(summary, request())

    assert decision.should_slice is True
    assert "file_count_exceeded" in decision.reason


def test_high_risk_file_slicing_decision():
    files = [changed_file("OrderService.java", True), changed_file("TradeMapper.xml", True)]
    summary = DiffSummary(
        char_count=100,
        file_count=len(files),
        high_risk_file_count=2,
        changed_files=files,
    )

    decision = SlicingDecisionPolicy().decide(summary, request())

    assert decision.should_slice is True
    assert "high_risk_file_threshold_reached" in decision.reason
