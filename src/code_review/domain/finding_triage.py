import re
from dataclasses import dataclass
from typing import List

from code_review.domain.models import ShardReviewResult


@dataclass(frozen=True)
class TriagedFinding:
    shard_id: str
    category: str
    title: str
    reason: str
    files: List[str]
    snippet: str = ""
    severity: str = ""
    finding_category: str = ""
    fingerprint: str = ""
    line: int = None
    code_snippet: str = ""


@dataclass(frozen=True)
class TriageSummary:
    recommended: List[TriagedFinding]
    need_manual_check: List[TriagedFinding]
    low_value_or_informational: List[TriagedFinding]


@dataclass(frozen=True)
class FindingQuality:
    bucket: str
    severity: str
    reason: str


class FindingTriagePolicy:
    """Local rule-based triage for LLM review candidates.

    The LLM output remains a candidate finding. This policy only adds a
    deterministic report-level grouping to make the final report more readable.
    """

    RECOMMENDED_KEYWORDS = (
        "高风险",
        "数据不一致",
        "数据丢失",
        "重复提交",
        "重复请求",
        "重复订单",
        "重复执行",
        "唯一性",
        "幂等",
        "重复消费",
        "消息丢失",
        "锁竞争",
        "慢查询",
        "索引",
        "敏感信息",
    )
    MANUAL_CHECK_KEYWORDS = (
        "事务",
        "乐观锁",
        "分布式锁",
        "并发",
        "缓存",
        "回滚",
        "状态流转",
        "需要确认",
        "可能",
    )
    LOW_VALUE_KEYWORDS = (
        "日志级别",
        "注释",
        "文档",
        "可读性",
        "命名",
        "格式",
        "示例输出",
        "面板描述",
    )
    TEMPLATE_TITLES = (
        "评审结果",
        "代码评审",
        "评审结论",
        "评审详情",
        "输出格式",
        "总结",
        "可选改进建议",
        "未发现高风险问题",
        "【严重级别】【问题类别】",
    )
    FINDING_START = re.compile(
        r"^\s*(?:#{3,6}\s+.+|\d+[\.\、]\s+.+|[-*]\s+\*\*【.+|[-*]\s+【[^】]+】.+|\*\*【?.+|【[^】]+】.+)"
    )
    GENERIC_PROBLEM_SIGNALS = (
        "没有明确",
        "未见明确",
        "可能存在",
        "可能会导致",
        "需要注意潜在",
        "建议考虑",
        "考虑使用",
        "缺少事务边界",
        "缺乏幂等性控制",
        "没有考虑幂等性",
        "没有加锁",
        "没有显式的行锁",
        "未明确指定行锁",
        "缺少",
        "建议",
        "考虑",
    )
    CONTRACT_SENSITIVE_CATEGORIES = {"concurrency", "idempotency", "transaction", "mq_reliability"}
    BLOCKING_CATEGORIES = {"security", "exception", "sql_performance", "config", "cache_consistency", "mq_reliability"}
    SYNTAX_OR_DETERMINISTIC_BUG_SIGNALS = (
        "语法错误",
        "编译失败",
        "执行失败",
        "无法执行",
        "空指针",
        "nullpointer",
        "npe",
        "空 catch",
        "没有记录日志",
        "未处理异常",
        "吞掉异常",
        "敏感信息",
        "sql注入",
        "安全漏洞",
        "数据丢失",
        "确定会",
        "必然",
    )
    ACTIONABLE_CODE_TOKENS = (
        "catch",
        "throw",
        "null",
        "where",
        "update",
        "insert",
        "delete",
        "select",
        "status",
        "state",
        "unique",
        "version",
        "id",
        "try",
        "execute",
        "send",
        "consume",
        "ack",
        "rollback",
        "commit",
        "timeout",
    )
    CONCURRENCY_EVIDENCE = (
        "非原子",
        "原子",
        "共享资源",
        "竞争窗口",
        "重复更新",
        "重复消费",
        "重复发送",
        "状态推进",
        "状态流转",
        "唯一约束",
        "乐观锁",
        "版本号",
        "compareandswap",
        "cas",
        "setnx",
        "incr",
    )
    IDEMPOTENCY_EVIDENCE = (
        "重复请求",
        "重复提交",
        "重复消费",
        "重复发送",
        "重复更新",
        "唯一键",
        "唯一约束",
        "业务键",
        "请求id",
        "requestid",
        "traceid",
        "状态重复",
        "二次推进",
    )
    TRANSACTION_EVIDENCE = (
        "部分成功",
        "部分失败",
        "跨多次写入",
        "多次写入",
        "异常路径",
        "回滚",
        "补偿",
        "提交",
        "事务外",
        "写入后发送",
    )
    SQL_PERFORMANCE_EVIDENCE = (
        "执行计划",
        "explain",
        "表数据量",
        "索引现状",
        "全表扫描",
        "filesort",
        "临时表",
        "慢查询日志",
        "语法错误",
        "执行失败",
    )
    LOW_ACTIONABILITY_SUGGESTIONS = (
        "添加锁",
        "加锁",
        "分布式锁",
        "乐观锁",
        "添加事务",
        "增加事务",
        "添加索引",
        "增加索引",
        "添加幂等",
        "增加幂等",
        "自定义异常",
        "更详细的错误信息",
    )
    STRONG_EXCEPTION_EVIDENCE = (
        "空 catch",
        "empty catch",
        "吞掉异常",
        "异常被吞",
        "未进行任何处理",
        "没有任何处理",
        "未处理异常",
        "没有记录日志",
        "未记录日志",
        "丢失原始异常",
        "未保留原始异常",
        "没有保留原始异常",
        "without cause",
        "no cause",
        "影响其他任务",
        "阻断其他任务",
        "任务状态",
        "失败状态",
    )

    def triage(self, shard_results: List[ShardReviewResult]) -> TriageSummary:
        recommended: List[TriagedFinding] = []
        manual: List[TriagedFinding] = []
        low_value: List[TriagedFinding] = []

        for result in shard_results:
            for finding in self._triage_result(result):
                if finding.category == "recommended":
                    recommended.append(finding)
                elif finding.category == "need_manual_check":
                    manual.append(finding)
                else:
                    low_value.append(finding)

        return TriageSummary(
            recommended=self._dedupe_findings(recommended),
            need_manual_check=self._dedupe_findings(manual),
            low_value_or_informational=self._dedupe_findings(low_value),
        )

    def _triage_result(self, result: ShardReviewResult) -> List[TriagedFinding]:
        shard = result.shard
        files = [file.display_path for file in shard.files]

        if not result.success:
            return []

        if result.structured_findings:
            return [self._triage_structured_finding(result, finding) for finding in result.structured_findings]

        if result.structured_summary and not result.parser_warnings:
            return []

        candidates = self._extract_candidate_findings(result.review_content)
        if not candidates:
            candidates = [result.review_content]

        return [self._triage_candidate(result, candidate) for candidate in candidates]

    def _triage_structured_finding(self, result: ShardReviewResult, finding) -> TriagedFinding:
        shard = result.shard
        category = "low_value_or_informational"
        quality = self._quality_gate(result, finding)
        severity = quality.severity
        if quality.bucket:
            category = quality.bucket
        elif severity == "error" or finding.category in self.BLOCKING_CATEGORIES:
            category = "recommended"
        elif severity == "warning":
            category = "need_manual_check"

        title = f"[{severity}/{finding.category}] {finding.problem}"[:120]
        snippet = " ".join(
            part
            for part in [
                f"Problem: {finding.problem}",
                f"Impact: {finding.impact}" if finding.impact else "",
                f"Suggestion: {finding.suggestion}" if finding.suggestion else "",
            ]
            if part
        )
        return TriagedFinding(
            shard_id=shard.shard_id,
            category=category,
            title=title,
            reason=quality.reason or f"结构化 finding: severity={finding.severity}, category={finding.category}, confidence={finding.confidence}",
            files=[finding.file] if finding.file else [file.display_path for file in shard.files],
            snippet=self._compact(snippet),
            severity=severity,
            finding_category=finding.category,
            fingerprint=finding.fingerprint,
            line=finding.line,
            code_snippet=finding.code_snippet,
        )

    def _quality_gate(self, result: ShardReviewResult, finding) -> FindingQuality:
        """Calibrate LLM finding with generic quality rules.

        The full report keeps raw worker output. This gate only controls what
        appears in PR/MR Summary as actionable findings.
        """
        severity = finding.severity
        if finding.parser_fallback:
            return FindingQuality("low_value_or_informational", "suggestion", "LLM 未输出合法结构化 finding，保留到完整报告，不进入 PR 主要结论。")

        score, score_reasons = self._evidence_score(result, finding)
        reason = f"质量门禁 score={score}: {', '.join(score_reasons)}"

        if self._is_contract_or_data_shape(result, finding) and score <= 3:
            return FindingQuality("low_value_or_informational", "suggestion", f"契约/数据结构文件中的低证据 finding 不进入主结论；{reason}")

        if finding.category in {"concurrency", "idempotency", "transaction"} and not finding.code_snippet and self._is_low_actionability_suggestion(finding):
            return FindingQuality("low_value_or_informational", "suggestion", f"并发/幂等/事务类 finding 缺少代码片段，且只是低可执行度建议，降级到完整报告；{reason}")

        if self._is_runtime_threshold_advice(finding):
            return FindingQuality("low_value_or_informational", "suggestion", f"运行时阈值建议需要压测或监控证据，降级到完整报告；{reason}")

        if severity == "error" and score < 7:
            return FindingQuality("need_manual_check", "warning", f"模型标记为 Error，但证据不足，降级为人工确认；{reason}")

        if finding.category == "exception":
            text = self._finding_text(finding)
            has_strong_exception_evidence = self._has_any_text_signal(text, self.STRONG_EXCEPTION_EVIDENCE)
            if not has_strong_exception_evidence and severity == "suggestion":
                return FindingQuality("low_value_or_informational", "suggestion", f"异常处理建议偏规范化，缺少明确故障证据，降级到完整报告；{reason}")
            if not has_strong_exception_evidence:
                return FindingQuality("need_manual_check", "warning", f"异常处理 finding 缺少强故障证据，降级为人工确认；{reason}")
            if score < 7:
                return FindingQuality("need_manual_check", "warning", f"异常处理 finding 证据不足，降级为人工确认；{reason}")

        if finding.category == "sql_performance" and not self._has_any_text_signal(self._finding_text(finding), self.SYNTAX_OR_DETERMINISTIC_BUG_SIGNALS):
            return FindingQuality("need_manual_check", "warning", f"SQL 性能建议需要运行或索引证据确认；{reason}")

        if finding.category in {"concurrency", "idempotency", "transaction"} and score < 6:
            return FindingQuality("low_value_or_informational", "suggestion", f"并发/幂等/事务类 finding 缺少可执行证据，降级到完整报告；{reason}")

        if finding.category == "test" and score < 6:
            return FindingQuality("low_value_or_informational", "suggestion", f"测试类 finding 未指出具体未覆盖行为，降级到完整报告；{reason}")

        if score <= 3:
            return FindingQuality("low_value_or_informational", "suggestion", f"finding 可执行性不足，降级到完整报告；{reason}")

        return FindingQuality("", severity, reason)

    def _evidence_score(self, result: ShardReviewResult, finding) -> tuple[int, List[str]]:
        score = 0
        reasons: List[str] = []
        text = self._finding_text(finding)
        low_text = text.lower()

        if finding.line:
            score += 2
            reasons.append("has_line")
        else:
            reasons.append("missing_line")

        if finding.code_snippet:
            score += 2
            reasons.append("has_code_snippet")
            if self._contains_any(finding.code_snippet.lower(), self.ACTIONABLE_CODE_TOKENS):
                score += 1
                reasons.append("code_snippet_actionable")
        else:
            reasons.append("missing_code_snippet")

        if finding.confidence == "high":
            score += 1
            reasons.append("high_confidence")
        elif finding.confidence == "low":
            score -= 1
            reasons.append("low_confidence")

        if self._has_any_text_signal(text, self.SYNTAX_OR_DETERMINISTIC_BUG_SIGNALS):
            score += 3
            reasons.append("deterministic_bug_signal")

        if self._has_category_evidence(finding.category, text):
            score += 2
            reasons.append(f"{finding.category}_evidence")

        if self._is_contract_or_data_shape(result, finding) and finding.category in self.CONTRACT_SENSITIVE_CATEGORIES:
            score -= 3
            reasons.append("contract_or_data_shape_low_runtime_evidence")

        if self._is_generic_advice(text):
            score -= 2
            reasons.append("generic_advice")

        if self._is_low_actionability_suggestion(finding):
            score -= 1
            reasons.append("low_actionability_suggestion")

        return max(score, 0), reasons

    def _finding_text(self, finding) -> str:
        return " ".join(
            part
            for part in [finding.problem, finding.impact, finding.suggestion, finding.code_snippet]
            if part
        )

    def _has_category_evidence(self, category: str, text: str) -> bool:
        if category == "concurrency":
            return self._has_any_text_signal(text, self.CONCURRENCY_EVIDENCE)
        if category == "idempotency":
            return self._has_any_text_signal(text, self.IDEMPOTENCY_EVIDENCE)
        if category == "transaction":
            return self._has_any_text_signal(text, self.TRANSACTION_EVIDENCE)
        if category == "sql_performance":
            return self._has_any_text_signal(text, self.SQL_PERFORMANCE_EVIDENCE)
        if category in {"exception", "mq_reliability", "security", "cache_consistency", "config"}:
            return True
        return False

    def _is_contract_or_data_shape(self, result: ShardReviewResult, finding) -> bool:
        path = (finding.file or "").replace("\\", "/").lower()
        filename = path.rsplit("/", 1)[-1]
        roles = {file.role for file in result.shard.files}
        if "model" in roles:
            return True
        return (
            filename.startswith("i")
            or path.endswith(("enum.java", "enumvo.java", "dto.java", "vo.java", "entity.java"))
            or any(marker in path for marker in ("/dto/", "/vo/", "/entity/", "/valobj/", "/model/"))
        )

    def _is_generic_advice(self, text: str) -> bool:
        return self._has_any_text_signal(text, self.GENERIC_PROBLEM_SIGNALS)

    def _is_low_actionability_suggestion(self, finding) -> bool:
        return self._has_any_text_signal(finding.suggestion or "", self.LOW_ACTIONABILITY_SUGGESTIONS)

    def _is_runtime_threshold_advice(self, finding) -> bool:
        text = self._finding_text(finding)
        threshold_signal = self._has_any_text_signal(text, ("阈值", "超时", "timeout", "重试次数", "连接池", "线程池大小"))
        observed_evidence = self._has_any_text_signal(text, ("实测", "压测结果", "监控显示", "p95", "p99", "错误率", "慢查询日志"))
        return threshold_signal and not observed_evidence

    def _has_any_text_signal(self, text: str, signals: tuple) -> bool:
        lower_text = text.lower()
        return any(signal.lower() in lower_text for signal in signals)

    def _triage_candidate(self, result: ShardReviewResult, content: str) -> TriagedFinding:
        shard = result.shard
        files = [file.display_path for file in shard.files]
        title = self._extract_title(content, shard.shard_id)
        has_recommended_signal = self._contains_any(content, self.RECOMMENDED_KEYWORDS)
        has_manual_signal = self._contains_any(content, self.MANUAL_CHECK_KEYWORDS)
        has_low_value_signal = self._contains_any(content, self.LOW_VALUE_KEYWORDS)
        is_high_risk_shard = bool(shard.risk_tags) or shard.role in {"data_access", "api", "service", "async", "config"}
        is_low_priority_candidate = self._is_low_priority_candidate(title, content)

        if is_high_risk_shard and has_recommended_signal:
            return TriagedFinding(
                shard_id=shard.shard_id,
                category="recommended",
                title=title,
                reason="命中高风险职责或核心后端关键词，建议优先人工处理。",
                files=files,
                snippet=self._compact(content),
            )

        if is_low_priority_candidate or (has_low_value_signal and not has_recommended_signal):
            return TriagedFinding(
                shard_id=shard.shard_id,
                category="low_value_or_informational",
                title=title,
                reason="主要是日志、文档、配置说明或低优先级可维护性建议。",
                files=files,
                snippet=self._compact(content),
            )

        if is_high_risk_shard and has_manual_signal:
            return TriagedFinding(
                shard_id=shard.shard_id,
                category="need_manual_check",
                title=title,
                reason="模型指出事务、并发、缓存、状态等候选问题，需要结合代码上下文确认。",
                files=files,
                snippet=self._compact(content),
            )

        if shard.role in {"other", "test"} and not has_recommended_signal:
            return TriagedFinding(
                shard_id=shard.shard_id,
                category="low_value_or_informational",
                title=title,
                reason="主要是日志、文档、配置说明或低优先级可维护性建议。",
                files=files,
                snippet=self._compact(content),
            )

        return TriagedFinding(
            shard_id=shard.shard_id,
            category="need_manual_check",
            title=title,
            reason="未命中明确高优先级或低价值规则，保守归入人工确认。",
            files=files,
            snippet=self._compact(content),
        )

    def _extract_candidate_findings(self, content: str) -> List[str]:
        lines = content.splitlines()
        blocks: List[List[str]] = []
        current: List[str] = []
        seen_start = False

        for line in lines:
            if self.FINDING_START.match(line):
                if current:
                    blocks.append(current)
                current = [line]
                seen_start = True
            elif current:
                current.append(line)

        if current:
            blocks.append(current)

        if not seen_start:
            return []

        candidates = ["\n".join(block).strip() for block in blocks]
        return [
            candidate
            for candidate in candidates
            if self._is_useful_candidate(candidate)
        ]

    def _is_useful_candidate(self, candidate: str) -> bool:
        if len(candidate) < 20:
            return False
        low = candidate.lower()
        title = self._extract_title(candidate, "")
        if low.startswith("```json") or low.startswith("```"):
            return False
        if any(template_title in title for template_title in self.TEMPLATE_TITLES):
            return False
        if "未发现高风险问题" in candidate and "问题" not in title:
            return False
        if low.startswith("### 评审结果") or low.startswith("### 代码评审"):
            return False
        return True

    def _extract_title(self, content: str, shard_id: str) -> str:
        first_line = content.strip().splitlines()[0] if content.strip() else shard_id
        title = re.sub(r"^\s*(?:#{3,6}\s+|\d+[\.\、]\s+|[-*]\s+)", "", first_line).strip()
        title = title.replace("**", "").strip()
        return title[:120] if title else shard_id

    def _compact(self, content: str) -> str:
        compacted = " ".join(line.strip() for line in content.splitlines() if line.strip())
        return compacted[:240]

    def _is_low_priority_candidate(self, title: str, content: str) -> bool:
        low_priority_title_signals = ("轻微", "日志级别", "文档", "注释", "面板", "tooltip", "legend")
        if any(signal in title for signal in low_priority_title_signals):
            return True

        if "【低】" in title and not self._contains_any(title + content, self.MANUAL_CHECK_KEYWORDS):
            return True

        if "日志级别" in content and ("debug" in content.lower() or "info" in content.lower()):
            return True

        return False

    def _contains_any(self, text: str, keywords: tuple) -> bool:
        return any(keyword in text for keyword in keywords)

    def _dedupe_findings(self, findings: List[TriagedFinding]) -> List[TriagedFinding]:
        deduped: List[TriagedFinding] = []
        seen = set()
        for finding in findings:
            key = finding.fingerprint or f"{finding.title}|{','.join(finding.files)}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(finding)
        return deduped
