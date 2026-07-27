import os
from datetime import date
from collections import Counter
from pathlib import Path
from uuid import uuid4

from code_review.domain.finding_triage import FindingTriagePolicy
from code_review.domain.models import ReviewReport
from code_review.domain.review_memory import ReviewMemoryCodec


class MarkdownReportWriter:
    """将评审结果写入本地 Markdown 文件。

    先替代 Java 版 JGit push 日志仓库的逻辑，后续可以再扩展为：
    - 写 GitHub Issue/PR Comment
    - 写远程日志仓库
    - 写数据库
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def write(self, content: str) -> Path:
        report_dir = self._output_dir / date.today().isoformat()
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{uuid4()}.md"
        report_path.write_text(content, encoding="utf-8")
        return report_path

    def render(self, report: ReviewReport) -> str:
        lines = [
            "# Code Review Report",
            "",
            "## Metadata",
            "",
            f"- Repo: `{report.request.repo_path}`",
            f"- Base: `{report.request.base_ref}`",
            f"- Head: `{report.request.head_ref}`",
            f"- Diff mode: `{'merge-base(base...head)' if report.request.use_merge_base else 'direct(base head)'}`",
            f"- Diff chars: `{report.diff_summary.char_count}`",
            f"- Changed files: `{report.diff_summary.file_count}`",
            f"- High-risk files: `{report.diff_summary.high_risk_file_count}`",
            f"- Slicing decision: `{report.slicing_decision.should_slice}`",
            f"- Slicing reason: `{report.slicing_decision.reason}`",
            f"- Shard count: `{len(report.shard_results)}`",
            f"- Profile source: `{report.profile_source}`",
            f"- Context strategy: `{report.context_strategy}`",
            "",
            "## Executive Summary",
            "",
            *self._render_executive_summary(report),
            "",
            "## Finding Triage",
            "",
            *self._render_finding_triage(report),
            "",
            "## Review Memory",
            "",
            *self._render_review_memory(report),
            "",
            "## Changed Files",
            "",
        ]

        for changed_file in report.diff_summary.changed_files:
            lines.append(
                f"- `{changed_file.display_path}` role=`{changed_file.role}` "
                f"high_risk=`{changed_file.is_high_risk}` risk_tags=`{changed_file.risk_tags}` "
                f"risk_level=`{changed_file.risk_level}` risk_score=`{changed_file.risk_score}` "
                f"context_depth=`{changed_file.context_depth}`"
            )

        lines.extend(["", "## Review Results", ""])

        for result in report.shard_results:
            shard = result.shard
            lines.extend(
                [
                    f"### {shard.shard_id} ({shard.index}/{shard.total})",
                    "",
                    f"- Role: `{shard.role}`",
                    f"- Risk tags: `{shard.risk_tags}`",
                    f"- Risk level: `{shard.risk_level}`",
                    f"- Risk score: `{shard.risk_score}`",
                    f"- Risk reasons: `{shard.risk_reasons}`",
                    f"- Context depth: `{shard.context_depth}`",
                    f"- Context reason: `{shard.context_reason}`",
                    f"- Methods: `{shard.method_names}`",
                    f"- Files: {', '.join(f'`{file.display_path}`' for file in shard.files)}",
                    f"- Success: `{result.success}`",
                    "",
                ]
            )
            if result.success:
                if result.structured_summary:
                    lines.extend([f"Structured summary: {result.structured_summary}", ""])
                if result.parser_warnings:
                    lines.append("Parser warnings:")
                    for warning in result.parser_warnings:
                        lines.append(f"- {warning}")
                    lines.append("")
                if result.structured_findings:
                    lines.extend(["Structured findings:", ""])
                    for finding in result.structured_findings:
                        lines.extend(
                            [
                                f"- `{finding.severity}` `{finding.category}` `{finding.file}`",
                                f"  - Method: `{finding.method}`",
                                f"  - Line: `{finding.line}`",
                                f"  - Problem: {finding.problem}",
                                f"  - Impact: {finding.impact}",
                                f"  - Suggestion: {finding.suggestion}",
                                f"  - Confidence: `{finding.confidence}`",
                                f"  - Fingerprint: `{finding.fingerprint}`",
                            ]
                        )
                    lines.append("")
                lines.extend(["Raw worker output:", ""])
                lines.extend([result.review_content, ""])
            else:
                lines.extend([f"Worker review failed: `{result.error_message}`", ""])

        lines.extend(["", self._render_memory_metadata(report)])
        return "\n".join(lines)

    def render_comment(self, report: ReviewReport, report_path: Path, inline_stats: dict = None) -> str:
        """Render a compact, human-readable PR/MR comment.

        The full report remains on disk for debugging. Platform comments should
        be short enough for reviewers to scan quickly.
        """
        success_count = sum(1 for result in report.shard_results if result.success)
        failed_count = len(report.shard_results) - success_count
        risk_counter = Counter(file.risk_level for file in report.diff_summary.changed_files)
        depth_counter = Counter(file.context_depth for file in report.diff_summary.changed_files)
        high_risk_files = sorted(
            [file for file in report.diff_summary.changed_files if file.is_high_risk],
            key=lambda file: file.risk_score,
            reverse=True,
        )
        triage = FindingTriagePolicy().triage(report.shard_results)
        recommended = self._dedupe_triaged_findings(triage.recommended)
        manual = self._dedupe_triaged_findings(triage.need_manual_check)
        low_value = self._dedupe_triaged_findings(triage.low_value_or_informational)
        failed_results = [result for result in report.shard_results if not result.success]
        grouped = self._group_comment_findings(recommended, manual, low_value)
        review_status = self._review_status(grouped, failed_count)
        conclusion = self._readable_comment_conclusion(report, grouped, failed_count, len(high_risk_files))
        inline_stats = inline_stats or {}
        top_risk_files = high_risk_files[:8]

        lines = [
            "## 🤖 AI Code Review",
            "",
            f"**评审结论：{review_status}**",
            "",
            "### 总结",
            "",
            conclusion,
            "",
            *self._render_severity_section("❌ Error（必须修改）", grouped["error"]),
            "",
            *self._render_severity_section("⚠️ Warning（建议修改）", grouped["warning"]),
            "",
            *self._render_severity_section("💡 Suggestion（可选改进）", grouped["suggestion"]),
            "",
            *self._render_failed_review_coverage(failed_results),
            "",
            "### 建议动作",
            "",
            *self._render_readable_action_items(report, grouped, high_risk_files, failed_results),
            "",
            "<details>",
            "<summary>📊 Review 详情</summary>",
            "",
            "| 项目 | 值 |",
            "| --- | --- |",
            f"| Base | `{self._short_ref(report.request.base_ref)}` |",
            f"| Head | `{self._short_ref(report.request.head_ref)}` |",
            f"| 变更文件 | `{report.diff_summary.file_count}` |",
            f"| Diff 大小 | `{report.diff_summary.char_count}` chars |",
            f"| 分片 | `{len(report.shard_results)}` |",
            f"| Worker 成功/失败 | `{success_count}/{failed_count}` |",
            f"| 最大补偿轮数 | `{report.request.max_review_rounds}` |",
            f"| Inline 评论 | `{inline_stats.get('published', 0)}` 条已标注到 Diff |",
            f"| Inline 跳过 | `{inline_stats.get('skipped', 0)}` 条无法定位到 Diff 新行 |",
            f"| Inline 失败 | `{inline_stats.get('failed', 0)}` 条发布失败 |",
            f"| 模型模式 | `{self._model_mode()}` |",
            f"| 策略 | `{report.context_strategy or 'default'}` |",
            f"| 切片原因 | `{self._escape_table(report.slicing_decision.reason)}` |",
            f"| 风险分布 | `{dict(risk_counter)}` |",
            f"| 上下文深度 | `{dict(depth_counter or report.review_depth_counts)}` |",
            f"| Low-value findings | `{len(low_value)}` |",
            f"| 完整本地报告 | `{report_path}` |",
            "",
            "#### Top 高风险文件",
            "",
            *self._render_compact_high_risk_files(top_risk_files, len(high_risk_files)),
            "",
            "</details>",
        ]
        return "\n".join(lines)

    def _group_comment_findings(self, recommended: list, manual: list, low_value: list) -> dict:
        grouped = {"error": [], "warning": [], "suggestion": []}
        for finding in [*recommended, *manual, *low_value]:
            severity = (finding.severity or "").lower()
            if severity not in grouped:
                if finding.category == "recommended":
                    severity = "warning"
                elif finding.category == "need_manual_check":
                    severity = "warning"
                else:
                    severity = "suggestion"
            grouped[severity].append(finding)
        return grouped

    def _review_status(self, grouped: dict, failed_count: int) -> str:
        if failed_count:
            return "评审不完整，需人工兜底"
        if grouped["error"]:
            return "发现必须修改项"
        if grouped["warning"]:
            return "存在建议修改/人工确认项"
        return "未发现明确阻断问题"

    def _readable_comment_conclusion(self, report: ReviewReport, grouped: dict, failed_count: int, high_risk_count: int) -> str:
        if failed_count:
            verdict = f"本次 AI Review 不完整：有 `{failed_count}` 个分片在重试后仍失败，相关文件需要人工兜底复核。"
        elif grouped["error"]:
            verdict = f"发现 `{len(grouped['error'])}` 个必须修改的问题，建议修复后再合并。"
        elif grouped["warning"]:
            verdict = f"未发现明确阻断合并的问题，但有 `{len(grouped['warning'])}` 个建议修改/人工确认的问题。"
        else:
            verdict = "未发现明确阻断合并的问题，可以按团队流程继续复核。"

        return (
            f"{verdict}\n\n"
            f"本次 PR 涉及 `{report.diff_summary.file_count}` 个文件，"
            f"高风险区域 `{high_risk_count}` 个，"
            f"采用 `{report.context_strategy or 'default'}` 策略；"
            "具体问题优先看下方分级列表和 Diff inline 评论。"
        )

    def _render_severity_section(self, title: str, findings: list, limit: int = 8) -> list:
        lines = [f"### {title}", ""]
        if not findings:
            return [*lines, "- None"]
        lines.extend(["| 文件 | 行 | 问题 | 建议 |", "| --- | ---: | --- | --- |"])
        for finding in findings[:limit]:
            file = self._escape_table(finding.files[0] if finding.files else "unknown")
            line = finding.line if finding.line else "-"
            problem = self._escape_table(self._strip_finding_prefix(finding.title))
            suggestion = self._escape_table(self._extract_suggestion(finding))
            lines.append(f"| `{file}` | {line} | {problem} | {suggestion} |")
        if len(findings) > limit:
            lines.append(f"| ... | ... | 还有 `{len(findings) - limit}` 个问题未展开 | 详见完整本地报告 |")

        primary = findings[0]
        if primary.code_snippet:
            lines.extend(["", "示例修复方向：", "", "```", primary.code_snippet[:600], "```"])
        return lines

    def _strip_finding_prefix(self, title: str) -> str:
        if "] " in title:
            return title.split("] ", 1)[1]
        return title

    def _extract_suggestion(self, finding) -> str:
        snippet = finding.snippet or finding.reason or ""
        marker = "Suggestion:"
        if marker in snippet:
            return snippet.split(marker, 1)[1].strip()
        if finding.code_snippet:
            return "参考下方示例修复方向。"
        return "结合上下文确认并补充修复或测试。"

    def _render_readable_action_items(self, report: ReviewReport, grouped: dict, high_risk_files: list, failed_results: list = None) -> list:
        actions = []
        failed_results = failed_results or []
        if failed_results:
            actions.append("先复核失败分片涉及文件，排查模型调用/网络问题后重新触发 `/cr`。")
        if grouped["error"]:
            actions.append("优先修复 Error 项，修复后重新触发 `/cr` 验证。")
        if grouped["warning"]:
            actions.append("Warning 项建议在本 PR 内处理；如果属于业务设计取舍，建议在评论中说明理由。")
        if report.diff_summary.file_count > 30:
            actions.append("本次 PR 较大，后续建议按核心代码、数据访问/脚本、配置/文档拆分，降低 Review 成本。")
        if high_risk_files and not grouped["error"]:
            actions.append("P0/P1 只表示优先复核区域，不等于确认 bug；人工重点看状态一致性、异常路径、边界条件和配置安全。")
        if not grouped["error"] and not grouped["warning"] and not grouped["suggestion"]:
            actions.append("模型未输出明确问题，但仍建议人工快速扫一遍高风险文件。")
        if self._model_mode() == "mock":
            actions.append("当前是 Mock LLM 模式，只能验证平台链路；正式评审请切换真实模型。")
        return [f"- {action}" for action in actions]

    def _render_compact_high_risk_files(self, files: list, total_count: int) -> list:
        if not files:
            return ["- None"]
        lines = []
        for file in files:
            signals = self._translate_risk_reasons(file.risk_reasons[:4]) or "路径/职责命中"
            lines.append(f"- `{file.display_path}` `{file.risk_level}` score=`{file.risk_score}` depth=`{file.context_depth}` signals={signals}")
        if total_count > len(files):
            lines.append(f"- ... and `{total_count - len(files)}` more high-risk file(s)")
        return lines

    def _escape_table(self, value: str) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").strip()

    def _model_mode(self) -> str:
        return "mock" if os.getenv("CODE_REVIEW_MOCK_LLM", "false").lower() == "true" else "real"

    def _comment_conclusion(self, report: ReviewReport, recommended: list, manual: list, high_risk_files: list) -> str:
        failed_count = sum(1 for result in report.shard_results if not result.success)
        if failed_count:
            verdict = f"本次 AI Review 不完整：有 `{failed_count}` 个分片在重试后仍失败，不能仅依据本结果合并。"
        elif recommended:
            verdict = "本次评审发现需要优先处理的问题，建议修复后再合并。"
        elif manual or high_risk_files:
            verdict = "当前未发现明确阻断合并的问题，但存在高风险变更区域，建议人工重点复核后再合并。"
        else:
            verdict = "当前未发现明显风险点，可以按团队流程继续合并。"

        return (
            f"{verdict}\n\n"
            f"本次变更涉及 `{report.diff_summary.file_count}` 个文件，"
            f"其中高风险文件 `{len(high_risk_files)}` 个；"
            f"系统按 `{report.context_strategy or 'default'}` 策略评审，"
            f"对核心文件优先补充完整上下文。"
        )

    def _render_high_risk_review(self, high_risk_files: list, limit: int) -> list:
        if not high_risk_files:
            return ["- 未识别到 P0/P1 高风险文件。"]

        lines = []
        for file in high_risk_files[:limit]:
            lines.append(f"#### `{file.display_path}`")
            lines.append("")
            lines.append(f"- 风险等级：`{file.risk_level}`，风险分：`{file.risk_score}`，上下文：`{file.context_depth}`")
            lines.append(f"- 判定原因：{self._human_risk_reason(file)}")
            lines.append(f"- 合理之处：{self._reasonable_point(file)}")
            lines.append(f"- 建议复核：{self._review_suggestion(file)}")
            lines.append("")
        if len(high_risk_files) > limit:
            lines.append(f"- 另有 `{len(high_risk_files) - limit}` 个高风险文件未在评论中展开，详见完整报告。")
        return lines

    def _human_risk_reason(self, file) -> str:
        role_reason = {
            "data_access": "属于数据访问层，变更可能影响数据库读写、事务边界或数据一致性。",
            "api": "属于对外接口入口，变更会直接影响请求参数、幂等控制和异常返回。",
            "service": "属于核心业务服务层，变更可能影响业务状态流转、资源占用、边界条件或一致性。",
            "async": "属于异步任务/消息链路，变更可能影响重复消费、失败补偿和幂等。",
            "config": "属于配置文件，变更可能影响运行环境、连接池、中间件或敏感配置。",
            "db_script": "属于数据库脚本，变更可能影响表结构、索引、初始化数据或校验逻辑。",
        }.get(file.role, "命中高风险路径或 diff 信号，需要结合业务语义复核。")
        signals = self._translate_risk_reasons(file.risk_reasons[:5])
        if signals:
            return f"{role_reason} 触发信号：{signals}。"
        if file.risk_tags:
            return f"{role_reason} 风险标签：{', '.join(file.risk_tags)}。"
        return role_reason

    def _reasonable_point(self, file) -> str:
        if file.context_depth == "full_context":
            context_note = "系统已读取该文件完整内容进行上下文评审"
        elif file.context_depth == "diff_only":
            context_note = "系统基于 diff 进行评审"
        else:
            context_note = "系统在大变更场景下对该文件做摘要级评审"

        role_point = {
            "data_access": "将数据读写逻辑集中在 Repository/DAO 层，有利于隔离领域逻辑和基础设施细节。",
            "api": "将外部请求入口集中在 Controller，有利于统一参数接入和响应封装。",
            "service": "核心业务逻辑放在服务层或规则组件中，有利于表达业务语义并隔离入口层与基础设施层。",
            "async": "将通知、补偿或任务处理拆到异步服务中，有利于降低主链路阻塞。",
            "config": "配置独立维护，有利于区分本地、测试和运行环境。",
            "db_script": "数据库脚本纳入版本管理，有利于环境初始化和变更追溯。",
        }.get(file.role, "该文件被纳入变更清单，便于追踪本次 PR 对系统结构的影响。")
        return f"{role_point} {context_note}。"

    def _review_suggestion(self, file) -> str:
        suggestions = {
            "data_access": "重点确认查询/更新条件、索引使用、事务边界、幂等更新条件，以及缓存与持久化数据是否可能不一致。",
            "api": "重点确认参数校验、鉴权/权限、重复请求处理、异常码返回、接口幂等，以及是否暴露内部实现细节。",
            "service": "重点确认业务状态流转是否完整，资源占用/释放是否成对出现，异常路径是否具备回滚或补偿机制。",
            "async": "重点确认任务是否可重复执行，消费失败是否有补偿，消息处理是否具备幂等保护。",
            "config": "重点确认是否包含敏感信息，是否误把 local/dev 配置用于生产，以及线程池/连接池参数是否合理。",
            "db_script": "重点确认 DDL/DML 兼容性、索引变化、初始化数据是否可重复执行，以及是否影响已有数据。",
        }
        return suggestions.get(file.role, "重点确认该变更是否影响核心链路、异常路径和可回滚性。")

    def _translate_risk_reasons(self, reasons: list) -> str:
        if not reasons:
            return ""
        translations = []
        mapping = {
            "transaction": "事务",
            "redis": "Redis",
            "idempotency": "幂等",
            "lock": "锁/并发",
            "state": "状态流转",
            "exception": "异常处理",
            "sql": "SQL",
            "mq": "消息队列",
        }
        for reason in reasons:
            matched = ""
            for key, label in mapping.items():
                if key in reason:
                    matched = label
                    break
            if matched and matched not in translations:
                translations.append(matched)
            elif reason.startswith("role:"):
                role = reason.split(":", 1)[1].split("+", 1)[0]
                label = {
                    "data_access": "数据访问层",
                    "api": "接口层",
                    "service": "服务层",
                    "async": "异步链路",
                    "config": "配置",
                    "db_script": "数据库脚本",
                }.get(role, role)
                if label not in translations:
                    translations.append(label)
        return "、".join(translations)

    def _render_failed_review_coverage(self, failed_results: list) -> list:
        if not failed_results:
            return []
        lines = [
            "#### 未完成评审的分片",
            "",
            "以下分片在多次重试后仍失败，相关文件需要人工兜底复核：",
            "",
        ]
        for result in failed_results[:5]:
            files = ", ".join(f"`{file.display_path}`" for file in result.shard.files[:4]) or "`unknown`"
            lines.append(
                f"- `{result.shard.shard_id}` round=`{result.review_round}` "
                f"attempts=`{result.retry_attempts}` files={files}"
            )
            lines.append(f"  - Error: {result.error_message}")
        if len(failed_results) > 5:
            lines.append(f"- ... and `{len(failed_results) - 5}` more failed shard(s)")
        return lines

    def _render_action_items(self, report: ReviewReport, recommended: list, manual: list, high_risk_files: list, failed_results: list = None) -> list:
        actions = []
        failed_results = failed_results or []
        if failed_results:
            actions.append("本次 AI Review 不完整，先人工复核失败分片涉及文件，排查模型调用或网络问题后重新触发 `/cr`。")
        if report.diff_summary.file_count > 30:
            actions.append("本次 PR 变更较大，建议后续按“核心业务代码 / 数据访问与数据库脚本 / 配置与辅助工程文件”拆分，降低人工 Review 成本。")
        if recommended:
            actions.append("先处理“建议优先处理”中的问题，再重新触发 `/cr`。")
        if high_risk_files:
            actions.append("人工优先复核上方 P0/P1 文件，重点看幂等、事务、并发控制、状态一致性、异常补偿和配置安全。")
        if not recommended and not manual:
            actions.append("模型未输出明确问题，但仍建议对高风险文件做一次人工快速复核。")
        actions.append("如当前使用 Mock LLM，本评论主要验证平台链路；正式合并前请切换真实模型重新评审。")
        return [f"- {action}" for action in actions]

    def _render_executive_summary(self, report: ReviewReport) -> list:
        success_count = sum(1 for result in report.shard_results if result.success)
        failed_count = len(report.shard_results) - success_count
        role_counter = Counter(file.role for file in report.diff_summary.changed_files)
        risk_counter = Counter(file.risk_level for file in report.diff_summary.changed_files)
        depth_counter = Counter(file.context_depth for file in report.diff_summary.changed_files)
        high_risk_files = [file for file in report.diff_summary.changed_files if file.is_high_risk]

        lines = [
            f"- Worker success: `{success_count}`",
            f"- Worker failed: `{failed_count}`",
            f"- Slicing reason: `{report.slicing_decision.reason}`",
            f"- Role distribution: `{dict(role_counter)}`",
            f"- Risk distribution: `{dict(risk_counter)}`",
            f"- Review depth distribution: `{dict(depth_counter or report.review_depth_counts)}`",
            f"- Profile source: `{report.profile_source}`",
            f"- Context strategy: `{report.context_strategy}`",
        ]

        if report.profile_warnings:
            lines.append("- Profile validation warnings:")
            for warning in report.profile_warnings:
                lines.append(f"  - {warning}")

        if high_risk_files:
            lines.append("- High-risk files:")
            for file in high_risk_files:
                lines.append(
                    f"  - `{file.display_path}` risk_level=`{file.risk_level}` "
                    f"risk_score=`{file.risk_score}` risk_tags=`{file.risk_tags}` "
                    f"context_depth=`{file.context_depth}`"
                )
        else:
            lines.append("- High-risk files: `none`")

        failed_results = [result for result in report.shard_results if not result.success]
        if failed_results:
            lines.append("- Failed shards:")
            for result in failed_results:
                lines.append(f"  - `{result.shard.shard_id}` error=`{result.error_message}`")

        return lines

    def _render_finding_triage(self, report: ReviewReport) -> list:
        triage = FindingTriagePolicy().triage(report.shard_results)
        lines = [
            "LLM 输出在本报告中作为候选 finding，以下分组由本地规则生成，用于区分优先级和人工确认边界。",
            "",
            "### Recommended Findings",
            "",
            *self._render_triaged_findings(triage.recommended),
            "",
            "### Need Manual Check",
            "",
            *self._render_triaged_findings(triage.need_manual_check),
            "",
            "### Low-value / Informational",
            "",
            *self._render_triaged_findings(triage.low_value_or_informational),
        ]
        return lines

    def _render_triaged_findings(self, findings: list) -> list:
        if not findings:
            return ["- None"]

        lines = []
        for finding in findings:
            lines.append(f"- `{finding.shard_id}` {finding.title}")
            lines.append(f"  - Reason: {finding.reason}")
            lines.append(f"  - Files: {', '.join(f'`{file}`' for file in finding.files[:5])}")
            if finding.snippet:
                lines.append(f"  - Snippet: {finding.snippet}")
            if finding.severity or finding.finding_category or finding.fingerprint:
                lines.append(
                    f"  - Structured: severity=`{finding.severity}` "
                    f"category=`{finding.finding_category}` fingerprint=`{finding.fingerprint}`"
                )
        return lines

    def _dedupe_triaged_findings(self, findings: list) -> list:
        deduped = []
        seen = set()
        for finding in findings:
            key = finding.fingerprint or f"{finding.title}|{','.join(finding.files)}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(finding)
        return deduped

    def _render_comment_findings(self, findings: list, limit: int) -> list:
        if not findings:
            return ["- None"]

        lines = []
        ordered = sorted(
            findings,
            key=lambda finding: (0 if finding.files and finding.files[0] != "unknown" else 1, 0 if getattr(finding, "line", None) else 1),
        )
        for finding in ordered[:limit]:
            files = ", ".join(f"`{file}`" for file in finding.files[:3]) or "`unknown`"
            location = self._finding_location(finding)
            lines.append(f"- {location} {finding.title}")
            lines.append(f"  - 影响文件：{files}")
            if finding.reason:
                lines.append(f"  - 判定依据：{finding.reason}")
            if finding.snippet:
                lines.append(f"  - 详情：{finding.snippet}")
            if finding.fingerprint:
                lines.append(f"  - Fingerprint: `{finding.fingerprint}`")
        if len(findings) > limit:
            lines.append(f"- ... and `{len(findings) - limit}` more finding(s)")
        return lines

    def _finding_location(self, finding) -> str:
        file = finding.files[0] if finding.files else ""
        line = getattr(finding, "line", None)
        if not line and getattr(finding, "snippet", ""):
            line = None
        if file and line:
            return f"`{file}:{line}`"
        if file:
            return f"`{file}`"
        return "`unknown`"

    def _short_ref(self, ref: str) -> str:
        if len(ref) >= 40 and all(ch in "0123456789abcdefABCDEF" for ch in ref):
            return ref[:8]
        return ref

    def _render_review_memory(self, report: ReviewReport) -> list:
        comparison = report.memory_comparison
        if not comparison:
            return ["- Review Memory: `not available`"]
        lines = [
            f"- Historical findings loaded: `{comparison.historical_count}`",
            f"- New findings: `{len(comparison.new_findings)}`",
            f"- Still open findings: `{len(comparison.still_open_findings)}`",
            f"- Possibly resolved findings: `{len(comparison.possibly_resolved_findings)}`",
        ]
        if comparison.warnings:
            lines.append("- Memory warnings:")
            for warning in comparison.warnings:
                lines.append(f"  - {warning}")
        return lines

    def _render_memory_metadata(self, report: ReviewReport) -> str:
        findings = [finding for result in report.shard_results for finding in result.structured_findings]
        review_id = f"{report.request.base_ref}-{report.request.head_ref}"
        return ReviewMemoryCodec().render(
            review_id=review_id,
            commit_sha=report.request.head_ref,
            findings=findings,
        )
