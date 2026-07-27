from code_review.domain.models import ReviewFinding
from code_review.domain.review_memory import ReviewMemoryCodec, ReviewMemoryMatcher


def finding(fingerprint: str, problem: str = "问题") -> ReviewFinding:
    return ReviewFinding(
        severity="warning",
        category="idempotency",
        file="OrderService.java",
        method="lockOrder",
        line=None,
        problem=problem,
        impact="影响",
        suggestion="建议",
        confidence="medium",
        fingerprint=fingerprint,
    )


def test_memory_codec_renders_and_parses_metadata():
    block = ReviewMemoryCodec().render("review-1", "abc123", [finding("fp1")])

    memory = ReviewMemoryCodec().parse_many([block])

    assert memory.review_id == "review-1"
    assert memory.commit_sha == "abc123"
    assert len(memory.findings) == 1
    assert memory.findings[0].fingerprint == "fp1"


def test_memory_codec_ignores_invalid_block():
    memory = ReviewMemoryCodec().parse_many(["<!-- ai-code-review-memory\nnot-json\n-->"])

    assert memory.findings == []
    assert memory.warnings


def test_memory_matcher_classifies_new_still_open_and_resolved():
    codec = ReviewMemoryCodec()
    memory = codec.parse_many([codec.render("review-1", "abc123", [finding("fp-old"), finding("fp-still")])])

    comparison = ReviewMemoryMatcher().compare([finding("fp-still"), finding("fp-new")], memory)

    assert [item.fingerprint for item in comparison.still_open_findings] == ["fp-still"]
    assert [item.fingerprint for item in comparison.new_findings] == ["fp-new"]
    assert [item.fingerprint for item in comparison.possibly_resolved_findings] == ["fp-old"]


def test_memory_matcher_without_memory_marks_all_new():
    comparison = ReviewMemoryMatcher().compare([finding("fp-new")], memory=None)

    assert len(comparison.new_findings) == 1
    assert not comparison.still_open_findings
    assert not comparison.possibly_resolved_findings
