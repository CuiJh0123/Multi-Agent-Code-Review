from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.models import ChangedFile, DiffSummary, ReviewProfile
from code_review.domain.risk_scorer import RiskScorer


def summary_for(path: str, role: str = "service") -> DiffSummary:
    return DiffSummary(
        char_count=100,
        file_count=1,
        high_risk_file_count=0,
        changed_files=[
            ChangedFile(
                old_path=path,
                new_path=path,
                role=role,
                is_high_risk=False,
            )
        ],
    )


def diff_for(path: str, body: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,2 +1,2 @@\n"
        f"{body}\n"
    )


def test_risk_scorer_promotes_profile_high_risk_path_and_sql_signal():
    path = "src/main/java/com/demo/payment/PayRepository.java"
    profile = ReviewProfile(source="test", high_risk=["src/main/java/**/payment/**"], low_risk=[], rules=[])

    scored = RiskScorer(FileDiffSectionParser()).score(
        diff_for(path, "+ update pay_order set status = 1"),
        summary_for(path, role="data_access"),
        profile,
    )

    file = scored.changed_files[0]
    assert file.risk_level in {"P0", "P1"}
    assert any("high_risk" in reason for reason in file.risk_reasons)
    assert any("diff_signal:sql" in reason for reason in file.risk_reasons)


def test_risk_scorer_downgrades_low_risk_docs():
    path = "docs/readme.md"
    profile = ReviewProfile(source="test", high_risk=[], low_risk=["docs/**"], rules=[])

    scored = RiskScorer(FileDiffSectionParser()).score(
        diff_for(path, "+ update docs"),
        summary_for(path, role="other"),
        profile,
    )

    assert scored.changed_files[0].risk_level == "P3"


def test_risk_scorer_caps_low_risk_markdown_even_with_business_words():
    path = "docs/dev-ops/load-test/local-baseline-report-template.md"
    profile = ReviewProfile(source="test", high_risk=[], low_risk=["docs/**"], rules=[])

    scored = RiskScorer(FileDiffSectionParser()).score(
        diff_for(path, "+ Redis lock settlement state idempotent"),
        summary_for(path, role="other"),
        profile,
    )

    file = scored.changed_files[0]
    assert file.risk_level == "P3"
    assert file.risk_score <= 15
