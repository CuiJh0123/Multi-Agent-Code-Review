import hashlib
import json
import re
from typing import List, Tuple

from code_review.domain.models import ReviewFinding, ReviewShard


class StructuredFindingParser:
    VALID_SEVERITIES = {"error", "warning", "suggestion"}
    VALID_CATEGORIES = {
        "concurrency",
        "idempotency",
        "transaction",
        "sql_performance",
        "security",
        "config",
        "maintainability",
        "observability",
        "test",
        "exception",
        "cache_consistency",
        "mq_reliability",
        "other",
    }
    VALID_CONFIDENCE = {"high", "medium", "low"}
    CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

    def parse(self, raw_output: str, shard: ReviewShard) -> Tuple[str, List[ReviewFinding], List[str]]:
        warnings: List[str] = []
        try:
            payload = json.loads(self._extract_json(raw_output))
        except Exception as error:
            warnings.append(f"structured finding parse failed: {error}")
            return "", [self._fallback_finding(raw_output, shard)], warnings

        if not isinstance(payload, dict):
            warnings.append("structured finding root is not object")
            return "", [self._fallback_finding(raw_output, shard)], warnings

        summary = str(payload.get("summary") or "").strip()
        raw_findings = payload.get("findings", [])
        if raw_findings is None:
            raw_findings = []
        if not isinstance(raw_findings, list):
            warnings.append("findings is not list")
            return summary, [self._fallback_finding(raw_output, shard)], warnings

        findings: List[ReviewFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                warnings.append("ignored non-object finding")
                continue
            finding = self._parse_finding(item, shard)
            if finding:
                findings.append(finding)

        return summary, findings, warnings

    def _extract_json(self, raw_output: str) -> str:
        text = raw_output.strip()
        match = self.CODE_FENCE.search(text)
        if match:
            return match.group(1).strip()
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            return text[first : last + 1]
        return text

    def _parse_finding(self, item: dict, shard: ReviewShard) -> ReviewFinding:
        problem = self._string(item.get("problem"))
        if not problem:
            return None
        file = self._string(item.get("file")) or self._default_file(shard)
        method = self._string(item.get("method"))
        category = self._normalize(item.get("category"), self.VALID_CATEGORIES, "other")
        severity = self._normalize(item.get("severity"), self.VALID_SEVERITIES, "warning")
        confidence = self._normalize(item.get("confidence"), self.VALID_CONFIDENCE, "medium")
        line = self._line(item.get("line"))
        code_snippet = self._string(item.get("code_snippet"))
        impact = self._string(item.get("impact"))
        suggestion = self._string(item.get("suggestion"))
        fingerprint = self.fingerprint(file, method, category, problem)
        return ReviewFinding(
            severity=severity,
            category=category,
            file=file,
            method=method,
            line=line,
            problem=problem,
            impact=impact,
            suggestion=suggestion,
            confidence=confidence,
            fingerprint=fingerprint,
            code_snippet=code_snippet,
            shard_id=shard.shard_id,
        )

    def _fallback_finding(self, raw_output: str, shard: ReviewShard) -> ReviewFinding:
        file = self._default_file(shard)
        problem = raw_output.strip()[:500] if raw_output.strip() else "Worker returned empty or invalid structured output"
        return ReviewFinding(
            severity="warning",
            category="other",
            file=file,
            method="",
            line=None,
            problem=problem,
            impact="LLM output was not valid structured JSON; raw output requires manual inspection.",
            suggestion="Check raw Worker output and consider rerunning review.",
            confidence="low",
            fingerprint=self.fingerprint(file, "", "other", problem),
            code_snippet="",
            shard_id=shard.shard_id,
            raw_content=raw_output,
            parser_fallback=True,
        )

    def fingerprint(self, file: str, method: str, category: str, problem: str) -> str:
        normalized_problem = " ".join(problem.lower().split())
        raw = f"{file}|{method}|{category}|{normalized_problem}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _normalize(self, value, valid: set, default: str) -> str:
        normalized = self._string(value).lower().replace("-", "_").replace(" ", "_")
        return normalized if normalized in valid else default

    def _string(self, value) -> str:
        return str(value).strip() if value is not None else ""

    def _line(self, value):
        if value is None or value == "":
            return None
        try:
            line = int(value)
            return line if line > 0 else None
        except (TypeError, ValueError):
            return None

    def _default_file(self, shard: ReviewShard) -> str:
        return shard.files[0].display_path if shard.files else ""
