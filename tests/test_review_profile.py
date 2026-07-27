from code_review.domain.review_profile import ReviewProfileValidator
from code_review.infrastructure.profile_loader import ReviewProfileLoader


def test_profile_validator_accepts_simple_schema_and_warnings_unmatched_path():
    profile = ReviewProfileValidator().validate(
        {
            "version": 1,
            "high_risk": ["src/main/java/**/payment/**", "missing/**"],
            "low_risk": ["docs/**"],
            "rules": ["支付回调必须关注幂等"],
        },
        repo_tree=["src/main/java/com/demo/payment/PayService.java", "docs/readme.md"],
        source=".code-review.yml",
    )

    assert "src/main/java/**/payment/**" in profile.high_risk
    assert "docs/**" in profile.low_risk
    assert profile.rules == ["支付回调必须关注幂等"]
    assert any("missing/**" in warning for warning in profile.validation_warnings)


def test_profile_loader_uses_default_when_file_missing(tmp_path):
    profile = ReviewProfileLoader().load(tmp_path, repo_tree=[])

    assert profile.source == "default"
    assert profile.high_risk
    assert profile.rules
