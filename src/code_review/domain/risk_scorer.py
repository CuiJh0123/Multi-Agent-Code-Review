import re
from pathlib import Path
from typing import Dict, List

from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.models import ChangedFile, DiffSummary, ReviewProfile


class RiskScorer:
    ROLE_SCORE: Dict[str, int] = {
        "data_access": 30,
        "service": 25,
        "async": 25,
        "api": 20,
        "config": 25,
        "db_script": 25,
        "model": 5,
        "test": 5,
        "other": 5,
    }
    BUSINESS_KEYWORDS = (
        "order",
        "trade",
        "payment",
        "pay",
        "inventory",
        "stock",
        "settlement",
        "refund",
        "lock",
        "occupy",
        "deduct",
        "notify",
        "callback",
    )
    DIFF_SIGNALS = {
        "transaction": ("@Transactional", "commit", "rollback", "事务"),
        "redis": ("Redis", "redis", "StringRedisTemplate", "Redisson", "incr", "setnx"),
        "mq": ("RabbitMQ", "Kafka", "@RabbitListener", "Consumer", "消息", "consume"),
        "sql": (" select ", " update ", " insert ", " delete ", "ALTER TABLE", "CREATE INDEX", "Mapper"),
        "idempotency": ("idempotent", "幂等", "outTradeNo", "unique", "duplicate"),
        "lock": ("lock", "Lock", "synchronized", "锁"),
        "state": ("status", "state", "状态", "flow"),
        "exception": ("catch", "throw", "Exception", "异常"),
    }

    def __init__(self, section_parser: FileDiffSectionParser) -> None:
        self._section_parser = section_parser

    def score(self, diff_text: str, summary: DiffSummary, profile: ReviewProfile) -> DiffSummary:
        sections = {section.display_path: section for section in self._section_parser.parse(diff_text)}
        scored_files: List[ChangedFile] = []
        for changed_file in summary.changed_files:
            section = sections.get(changed_file.display_path)
            section_text = section.diff_text if section else ""
            score, reasons = self._score_file(changed_file, section_text, profile)
            level = self._level(score)
            scored_files.append(
                ChangedFile(
                    old_path=changed_file.old_path,
                    new_path=changed_file.new_path,
                    role=changed_file.role,
                    is_high_risk=changed_file.is_high_risk or level in {"P0", "P1"},
                    risk_tags=changed_file.risk_tags,
                    risk_score=score,
                    risk_level=level,
                    risk_reasons=reasons,
                    context_depth=changed_file.context_depth,
                    context_reason=changed_file.context_reason,
                )
            )

        return DiffSummary(
            char_count=summary.char_count,
            file_count=summary.file_count,
            high_risk_file_count=sum(1 for file in scored_files if file.risk_level in {"P0", "P1"}),
            changed_files=scored_files,
        )

    def _score_file(self, changed_file: ChangedFile, diff_text: str, profile: ReviewProfile) -> tuple:
        score = self.ROLE_SCORE.get(changed_file.role, 5)
        reasons = [f"role:{changed_file.role}+{score}"]
        path = changed_file.display_path
        path_lower = path.lower()

        for pattern in profile.high_risk:
            if self._matches(path, pattern):
                score += 30
                reasons.append(f"high_risk:{pattern}+30")
                break

        matched_low_risk = False
        for pattern in profile.low_risk:
            if self._matches(path, pattern):
                matched_low_risk = True
                score -= 25
                reasons.append(f"low_risk:{pattern}-25")
                break

        matched_keywords = [keyword for keyword in self.BUSINESS_KEYWORDS if keyword in path_lower]
        if matched_keywords:
            score += 20
            reasons.append(f"business_keywords:{','.join(matched_keywords[:3])}+20")

        for signal_name, tokens in self.DIFF_SIGNALS.items():
            if any(token in diff_text for token in tokens):
                score += 15
                reasons.append(f"diff_signal:{signal_name}+15")

        if self._only_low_value_diff(diff_text):
            score -= 15
            reasons.append("low_value_diff:log_or_comment_only-15")

        score = max(0, score)
        if matched_low_risk:
            score = self._cap_low_risk_score(path, score)
        return score, reasons

    def _level(self, score: int) -> str:
        if score >= 70:
            return "P0"
        if score >= 45:
            return "P1"
        if score >= 20:
            return "P2"
        return "P3"

    def _matches(self, path: str, pattern: str) -> bool:
        path_obj = Path(path)
        if path_obj.match(pattern):
            return True
        if pattern.startswith("**/") and path_obj.match(pattern[3:]):
            return True
        if pattern.endswith("/**") and path.startswith(pattern[:-3].rstrip("/") + "/"):
            return True
        if "/**/" in pattern:
            prefix, suffix = pattern.split("/**/", 1)
            return path.startswith(prefix.rstrip("/") + "/") and path_obj.match(f"**/{suffix}")
        return False

    def _only_low_value_diff(self, diff_text: str) -> bool:
        changed_lines = [
            line[1:].strip()
            for line in diff_text.splitlines()
            if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
        ]
        if not changed_lines:
            return False
        low_value = 0
        for line in changed_lines:
            if re.search(r"\blog\.(debug|info|warn|error)\b", line) or line.startswith(("//", "*", "/*")):
                low_value += 1
        return low_value == len(changed_lines)

    def _cap_low_risk_score(self, path: str, score: int) -> int:
        suffix = Path(path).suffix.lower()
        if suffix == ".sql":
            return score
        if suffix in {".md", ".json", ".jmx", ".csv", ".yml", ".yaml"}:
            return min(score, 15)
        if suffix in {".sh", ".txt"}:
            return min(score, 20)
        return score
