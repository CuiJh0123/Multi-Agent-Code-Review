from code_review.domain.models import ChangedFile, ReviewShard
from code_review.domain.structured_finding_parser import StructuredFindingParser


def shard() -> ReviewShard:
    return ReviewShard(
        shard_id="shard-1",
        index=1,
        total=1,
        role="service",
        files=[
            ChangedFile(
                old_path="OrderService.java",
                new_path="OrderService.java",
                role="service",
                is_high_risk=True,
            )
        ],
        diff_text="diff",
    )


def test_parse_valid_json_finding():
    raw = (
        '{"summary":"摘要","findings":[{"severity":"warning","category":"idempotency",'
        '"file":"OrderService.java","method":"lockOrder","line":12,'
        '"code_snippet":"return true;",'
        '"problem":"缺少幂等控制","impact":"可能重复下单","suggestion":"增加幂等校验","confidence":"high"}]}'
    )

    summary, findings, warnings = StructuredFindingParser().parse(raw, shard())

    assert summary == "摘要"
    assert not warnings
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].category == "idempotency"
    assert findings[0].line == 12
    assert findings[0].code_snippet == "return true;"
    assert findings[0].fingerprint


def test_parse_fenced_json():
    raw = """```json
{"summary":"摘要","findings":[]}
```"""

    summary, findings, warnings = StructuredFindingParser().parse(raw, shard())

    assert summary == "摘要"
    assert findings == []
    assert warnings == []


def test_invalid_json_fallback_finding():
    summary, findings, warnings = StructuredFindingParser().parse("不是 JSON", shard())

    assert summary == ""
    assert warnings
    assert len(findings) == 1
    assert findings[0].parser_fallback is True
    assert findings[0].confidence == "low"


def test_fingerprint_is_stable():
    parser = StructuredFindingParser()

    left = parser.fingerprint("A.java", "m", "idempotency", "缺少 幂等 控制")
    right = parser.fingerprint("A.java", "m", "idempotency", "缺少 幂等 控制")

    assert left == right
