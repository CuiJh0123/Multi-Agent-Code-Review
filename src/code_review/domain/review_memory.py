import json
import re
from typing import Iterable, List

from code_review.domain.models import HistoricalFinding, ReviewFinding, ReviewMemoryComparison, ReviewMemoryDocument


class ReviewMemoryCodec:
    START = "<!-- ai-code-review-memory"
    END = "-->"
    BLOCK_PATTERN = re.compile(r"<!--\s*ai-code-review-memory\s*(.*?)-->", re.DOTALL)

    def render(self, review_id: str, commit_sha: str, findings: Iterable[ReviewFinding]) -> str:
        payload = {
            "version": 1,
            "review_id": review_id,
            "commit_sha": commit_sha,
            "findings": [
                {
                    "fingerprint": finding.fingerprint,
                    "severity": finding.severity,
                    "category": finding.category,
                    "file": finding.file,
                    "method": finding.method,
                    "problem": finding.problem,
                }
                for finding in findings
                if finding.fingerprint
            ],
        }
        return f"{self.START}\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n{self.END}"

    def parse_many(self, markdown_texts: Iterable[str]) -> ReviewMemoryDocument:
        findings: List[HistoricalFinding] = []
        warnings: List[str] = []
        review_id = ""
        commit_sha = ""
        for text in markdown_texts:
            for match in self.BLOCK_PATTERN.finditer(text or ""):
                raw = match.group(1).strip()
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as error:
                    warnings.append(f"invalid review memory block ignored: {error}")
                    continue
                if not isinstance(payload, dict):
                    warnings.append("invalid review memory block ignored: root is not object")
                    continue
                review_id = str(payload.get("review_id") or review_id)
                commit_sha = str(payload.get("commit_sha") or commit_sha)
                raw_findings = payload.get("findings", [])
                if not isinstance(raw_findings, list):
                    warnings.append("invalid review memory findings ignored: findings is not list")
                    continue
                for item in raw_findings:
                    historical = self._parse_historical_finding(item, review_id, commit_sha)
                    if historical:
                        findings.append(historical)

        return ReviewMemoryDocument(
            review_id=review_id,
            commit_sha=commit_sha,
            findings=findings,
            warnings=warnings,
        )

    def _parse_historical_finding(self, item, review_id: str, commit_sha: str):
        if not isinstance(item, dict):
            return None
        fingerprint = str(item.get("fingerprint") or "").strip()
        if not fingerprint:
            return None
        return HistoricalFinding(
            fingerprint=fingerprint,
            severity=str(item.get("severity") or ""),
            category=str(item.get("category") or ""),
            file=str(item.get("file") or ""),
            method=str(item.get("method") or ""),
            problem=str(item.get("problem") or ""),
            review_id=review_id,
            commit_sha=commit_sha,
        )


class ReviewMemoryMatcher:
    def compare(self, current_findings: Iterable[ReviewFinding], memory: ReviewMemoryDocument = None) -> ReviewMemoryComparison:
        current = [finding for finding in current_findings if finding.fingerprint]
        if memory is None:
            return ReviewMemoryComparison(new_findings=current)

        historical_by_fingerprint = {finding.fingerprint: finding for finding in memory.findings}
        current_by_fingerprint = {finding.fingerprint: finding for finding in current}
        new_findings: List[ReviewFinding] = []
        still_open: List[ReviewFinding] = []

        for finding in current:
            if finding.fingerprint in historical_by_fingerprint:
                still_open.append(finding)
            else:
                new_findings.append(finding)

        possibly_resolved = [
            finding
            for fingerprint, finding in historical_by_fingerprint.items()
            if fingerprint not in current_by_fingerprint
        ]

        return ReviewMemoryComparison(
            new_findings=new_findings,
            still_open_findings=still_open,
            possibly_resolved_findings=possibly_resolved,
            historical_count=len(memory.findings),
            warnings=memory.warnings,
        )
