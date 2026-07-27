from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ReviewRequest:
    repo_path: Path
    base_ref: str
    head_ref: str
    use_merge_base: bool = False
    max_chars_per_shard: int = 12000
    max_files_per_shard: int = 5
    max_high_risk_files_per_shard: int = 2
    max_workers: int = 4
    max_review_rounds: int = 3


@dataclass(frozen=True)
class ChangedFile:
    old_path: str
    new_path: str
    role: str
    is_high_risk: bool
    risk_tags: List[str] = field(default_factory=list)
    risk_score: int = 0
    risk_level: str = "P3"
    risk_reasons: List[str] = field(default_factory=list)
    context_depth: str = "diff_only"
    context_reason: str = ""

    @property
    def display_path(self) -> str:
        return self.new_path if self.new_path != "/dev/null" else self.old_path


@dataclass(frozen=True)
class DiffSummary:
    char_count: int
    file_count: int
    high_risk_file_count: int
    changed_files: List[ChangedFile] = field(default_factory=list)


@dataclass(frozen=True)
class SlicingDecision:
    should_slice: bool
    reason: str


@dataclass(frozen=True)
class ReviewShard:
    shard_id: str
    index: int
    total: int
    role: str
    files: List[ChangedFile]
    diff_text: str
    risk_tags: List[str] = field(default_factory=list)
    method_names: List[str] = field(default_factory=list)
    risk_score: int = 0
    risk_level: str = "P3"
    risk_reasons: List[str] = field(default_factory=list)
    context_depth: str = "diff_only"
    context_reason: str = ""
    context_text: str = ""
    profile_rules: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ShardReviewResult:
    shard: ReviewShard
    review_content: str
    success: bool = True
    error_message: str = ""
    structured_summary: str = ""
    structured_findings: List["ReviewFinding"] = field(default_factory=list)
    parser_warnings: List[str] = field(default_factory=list)
    retry_attempts: int = 1
    review_round: int = 1


@dataclass(frozen=True)
class ReviewReport:
    request: ReviewRequest
    diff_summary: DiffSummary
    slicing_decision: SlicingDecision
    shard_results: List[ShardReviewResult]
    profile_source: str = "default"
    profile_warnings: List[str] = field(default_factory=list)
    context_strategy: str = ""
    review_depth_counts: Dict[str, int] = field(default_factory=dict)
    memory_comparison: Optional["ReviewMemoryComparison"] = None


@dataclass(frozen=True)
class ReviewResult:
    diff_text: str
    prompt: str
    review_content: str
    report_path: Path
    slicing_decision: SlicingDecision
    shard_count: int
    shard_review_results: List[ShardReviewResult] = field(default_factory=list)
    comment_content: str = ""
    report: Optional[ReviewReport] = None


@dataclass(frozen=True)
class ReviewWorkspace:
    worktree_path: Path
    repo_tree: List[str]
    base_ref: str
    head_ref: str
    diff_text: str
    changed_files: List[ChangedFile]
    trigger_type: str = "local"
    platform: str = "local"
    file_contents: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewProfile:
    source: str
    high_risk: List[str] = field(default_factory=list)
    low_risk: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileReviewContext:
    file_path: str
    depth: str
    reason: str
    context_text: str = ""
    related_files: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    category: str
    file: str
    method: str
    line: Optional[int]
    problem: str
    impact: str
    suggestion: str
    confidence: str
    fingerprint: str
    code_snippet: str = ""
    shard_id: str = ""
    raw_content: str = ""
    parser_fallback: bool = False


@dataclass(frozen=True)
class HistoricalFinding:
    fingerprint: str
    severity: str
    category: str
    file: str
    method: str
    problem: str
    review_id: str = ""
    commit_sha: str = ""


@dataclass(frozen=True)
class ReviewMemoryDocument:
    review_id: str
    commit_sha: str
    findings: List[HistoricalFinding] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewMemoryComparison:
    new_findings: List[ReviewFinding] = field(default_factory=list)
    still_open_findings: List[ReviewFinding] = field(default_factory=list)
    possibly_resolved_findings: List[HistoricalFinding] = field(default_factory=list)
    historical_count: int = 0
    warnings: List[str] = field(default_factory=list)
