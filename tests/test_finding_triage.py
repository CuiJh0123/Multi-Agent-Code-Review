from code_review.domain.finding_triage import FindingTriagePolicy
from code_review.domain.models import ChangedFile, ReviewFinding, ReviewShard, ShardReviewResult


def shard(role: str, risk_tags=None) -> ReviewShard:
    risk_tags = risk_tags or []
    changed_file = ChangedFile(
        old_path="OrderService.java",
        new_path="OrderService.java",
        role=role,
        is_high_risk=bool(risk_tags),
        risk_tags=risk_tags,
    )
    return ReviewShard(
        shard_id="shard-1",
        index=1,
        total=1,
        role=role,
        files=[changed_file],
        diff_text="diff",
        risk_tags=risk_tags,
    )


def result_with_finding(changed_file: ChangedFile, finding: ReviewFinding) -> ShardReviewResult:
    review_shard = ReviewShard(
        shard_id="shard-1",
        index=1,
        total=1,
        role=changed_file.role,
        files=[changed_file],
        diff_text="diff",
        risk_tags=changed_file.risk_tags,
    )
    return ShardReviewResult(
        shard=review_shard,
        review_content="{}",
        structured_findings=[finding],
    )


def test_triage_recommended_for_high_risk_backend_signal():
    result = ShardReviewResult(
        shard=shard("data_access", ["data_access"]),
        review_content="这里可能存在慢查询和索引缺失问题",
    )

    summary = FindingTriagePolicy().triage([result])

    assert len(summary.recommended) == 1
    assert not summary.need_manual_check


def test_triage_manual_check_for_transaction_candidate():
    result = ShardReviewResult(
        shard=shard("service", ["core_business"]),
        review_content="事务边界可能需要确认",
    )

    summary = FindingTriagePolicy().triage([result])

    assert len(summary.need_manual_check) == 1


def test_triage_low_value_for_log_advice():
    result = ShardReviewResult(
        shard=shard("other"),
        review_content="日志级别和文档说明可以优化",
    )

    summary = FindingTriagePolicy().triage([result])

    assert len(summary.low_value_or_informational) == 1


def test_triage_extracts_multiple_candidate_findings():
    result = ShardReviewResult(
        shard=shard("data_access", ["data_access"]),
        review_content=(
            "### 评审结果\n\n"
            "1. **【中】【SQL 性能】**\n"
            "- **问题**：可能存在慢查询和索引缺失。\n"
            "- **建议**：检查核心查询索引。\n\n"
            "2. **【低】【日志级别】**\n"
            "- **问题**：日志级别可以优化。\n"
        ),
    )

    summary = FindingTriagePolicy().triage([result])

    assert len(summary.recommended) == 1
    assert len(summary.low_value_or_informational) == 1


def test_triage_ignores_llm_template_sections():
    result = ShardReviewResult(
        shard=shard("data_access", ["data_access"]),
        review_content=(
            "### 输出格式\n"
            "- **严重级别**：低\n"
            "- **问题类别**：事务边界、索引、慢查询\n"
            "- **问题**：模板说明，不是独立 finding。\n\n"
            "1. **事务边界是否合理**\n"
            "- **问题**：事务边界可能需要确认。\n"
        ),
    )

    summary = FindingTriagePolicy().triage([result])

    assert len(summary.recommended) == 0
    assert len(summary.need_manual_check) == 1


def test_triage_keeps_log_level_advice_low_priority_even_with_manual_words():
    result = ShardReviewResult(
        shard=shard("service", ["core_business"]),
        review_content=(
            "1. **【低】【日志级别调整】**\n"
            "- **问题**：log.info 改为 log.debug，生产环境可能需要确认是否影响排查。\n"
            "- **建议**：按日志规范确认即可。\n"
        ),
    )

    summary = FindingTriagePolicy().triage([result])

    assert len(summary.need_manual_check) == 0
    assert len(summary.low_value_or_informational) == 1


def test_triage_does_not_downgrade_low_severity_concurrency_candidate():
    result = ShardReviewResult(
        shard=shard("data_access", ["data_access"]),
        review_content=(
            "1. **【低】【并发一致性】**\n"
            "- **问题**：Redis 计数和数据库更新之间可能存在并发一致性问题。\n"
            "- **建议**：结合压测和代码上下文人工确认。\n"
        ),
    )

    summary = FindingTriagePolicy().triage([result])

    assert len(summary.low_value_or_informational) == 0
    assert len(summary.need_manual_check) == 1


def test_triage_downgrades_generic_runtime_advice_without_code_evidence():
    changed_file = ChangedFile(
        old_path="WorkflowRouter.java",
        new_path="WorkflowRouter.java",
        role="service",
        is_high_risk=True,
        risk_tags=["core_business"],
    )
    finding = ReviewFinding(
        severity="warning",
        category="concurrency",
        file="WorkflowRouter.java",
        method="route",
        line=49,
        problem="该方法可能存在并发问题。",
        impact="多个线程可能同时调用该方法导致数据不一致。",
        suggestion="考虑加锁或使用乐观锁。",
        confidence="medium",
        fingerprint="fp-generic-advice",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.need_manual_check) == 0
    assert len(summary.low_value_or_informational) == 1


def test_triage_downgrades_contract_transaction_advice():
    changed_file = ChangedFile(
        old_path="IWorkflowCommand.java",
        new_path="IWorkflowCommand.java",
        role="model",
        is_high_risk=False,
        risk_tags=["core_business"],
    )
    finding = ReviewFinding(
        severity="warning",
        category="transaction",
        file="IWorkflowCommand.java",
        method="execute",
        line=12,
        problem="execute 方法没有明确指定事务边界和异常回滚策略。",
        impact="可能导致数据不一致。",
        suggestion="建议在接口上添加事务注解。",
        confidence="medium",
        fingerprint="fp-interface",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.low_value_or_informational) == 1


def test_triage_keeps_concrete_sql_syntax_error_recommended():
    changed_file = ChangedFile(
        old_path="user_mapper.xml",
        new_path="user_mapper.xml",
        role="data_access",
        is_high_risk=True,
        risk_tags=["data_access"],
    )
    finding = ReviewFinding(
        severity="error",
        category="sql_performance",
        file="user_mapper.xml",
        method="updateUserStatus",
        line=95,
        problem="SQL where 条件使用逗号分隔，会导致语法错误。",
        impact="状态更新 SQL 执行失败。",
        suggestion="将逗号替换为 AND。",
        confidence="high",
        fingerprint="fp-sql",
        code_snippet="where user_id = #{userId}, order_id = #{orderId}, status = 0",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 1
    assert len(summary.low_value_or_informational) == 0


def test_triage_downgrades_sql_index_advice_from_error():
    changed_file = ChangedFile(
        old_path="payment_mapper.xml",
        new_path="payment_mapper.xml",
        role="data_access",
        is_high_risk=True,
        risk_tags=["data_access"],
    )
    finding = ReviewFinding(
        severity="error",
        category="sql_performance",
        file="payment_mapper.xml",
        method="updatePayment",
        line=88,
        problem="SQL 语句中使用了多个条件，可能存在索引缺失导致慢查询的风险。",
        impact="可能导致查询性能下降。",
        suggestion="建议添加复合索引。",
        confidence="high",
        fingerprint="fp-index",
        code_snippet="where team_id = #{teamId} and status = 1",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.need_manual_check) == 1


def test_triage_downgrades_lock_only_advice_without_conflict_evidence():
    changed_file = ChangedFile(
        old_path="task_mapper.xml",
        new_path="task_mapper.xml",
        role="data_access",
        is_high_risk=True,
        risk_tags=["data_access"],
    )
    finding = ReviewFinding(
        severity="warning",
        category="concurrency",
        file="task_mapper.xml",
        method="updateTaskStatus",
        line=101,
        problem="更新操作可能在高并发场景下存在行锁竞争。",
        impact="可能导致并发更新。",
        suggestion="考虑添加锁或使用乐观锁。",
        confidence="medium",
        fingerprint="fp-lock-only",
        code_snippet="update task set status = 2 where task_id = #{taskId}",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.low_value_or_informational) == 1


def test_triage_downgrades_runtime_threshold_advice_without_operational_evidence():
    changed_file = ChangedFile(
        old_path="PaymentRepository.java",
        new_path="PaymentRepository.java",
        role="data_access",
        is_high_risk=True,
        risk_tags=["data_access"],
    )
    finding = ReviewFinding(
        severity="error",
        category="transaction",
        file="PaymentRepository.java",
        method="savePayment",
        line=86,
        problem="运行时阈值设置可能过小，可能导致高负载下失败。",
        impact="可能影响稳定性。",
        suggestion="建议结合压测或线上指标调整阈值。",
        confidence="high",
        fingerprint="fp-runtime-threshold",
        code_snippet="timeout = 500",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.low_value_or_informational) == 1


def test_triage_sql_performance_warning_goes_manual_not_recommended():
    changed_file = ChangedFile(
        old_path="payment_mapper.xml",
        new_path="payment_mapper.xml",
        role="data_access",
        is_high_risk=True,
        risk_tags=["data_access"],
    )
    finding = ReviewFinding(
        severity="warning",
        category="sql_performance",
        file="payment_mapper.xml",
        method="updatePayment",
        line=10,
        problem="可能存在的慢查询风险。",
        impact="如果 team_id 和 status 没有索引，可能导致查询性能下降。",
        suggestion="建议添加复合索引。",
        confidence="high",
        fingerprint="fp-sql-warning",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.need_manual_check) == 1


def test_triage_downgrades_generic_lock_advice_without_actionable_evidence():
    changed_file = ChangedFile(
        old_path="PaymentService.java",
        new_path="PaymentService.java",
        role="service",
        is_high_risk=True,
        risk_tags=["core_business"],
    )
    finding = ReviewFinding(
        severity="error",
        category="concurrency",
        file="PaymentService.java",
        method="settle",
        line=37,
        problem="在并发场景下，多个线程可能同时调用 settle 方法，导致数据不一致。",
        impact="可能导致状态不一致。",
        suggestion="考虑添加分布式锁或乐观锁。",
        confidence="high",
        fingerprint="fp-generic-lock",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.low_value_or_informational) == 1


def test_triage_downgrades_contract_idempotency_advice():
    changed_file = ChangedFile(
        old_path="ICommandRepository.java",
        new_path="ICommandRepository.java",
        role="data_access",
        is_high_risk=True,
        risk_tags=["data_access"],
    )
    finding = ReviewFinding(
        severity="warning",
        category="idempotency",
        file="ICommandRepository.java",
        method="saveCommand",
        line=20,
        problem="未见幂等性控制逻辑",
        impact="重试可能导致数据不一致",
        suggestion="建议在方法实现中加入幂等性检查",
        confidence="high",
        fingerprint="fp-interface-idempotency",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.low_value_or_informational) == 1


def test_triage_downgrades_data_shape_runtime_exception_style_advice():
    changed_file = ChangedFile(
        old_path="CommandTypeEnum.java",
        new_path="CommandTypeEnum.java",
        role="model",
        is_high_risk=True,
        risk_tags=["core_business"],
    )
    finding = ReviewFinding(
        severity="error",
        category="exception",
        file="CommandTypeEnum.java",
        method="parse",
        line=50,
        problem="在找不到匹配的命令类型时抛出运行时异常，缺乏具体的错误信息和业务上下文。",
        impact="调用方可能无法准确判断失败原因。",
        suggestion="建议使用自定义异常。",
        confidence="high",
        fingerprint="fp-enum-exception",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.low_value_or_informational) == 1


def test_triage_does_not_turn_empty_structured_findings_into_manual_check():
    result = ShardReviewResult(
        shard=shard("config", ["config"]),
        review_content='```json\n{"summary":"配置变更未发现明显问题。","findings":[]}\n```',
        structured_summary="配置变更未发现明显问题。",
        structured_findings=[],
        parser_warnings=[],
    )

    summary = FindingTriagePolicy().triage([result])

    assert summary.recommended == []
    assert summary.need_manual_check == []
    assert summary.low_value_or_informational == []


def test_triage_does_not_report_failed_worker_as_code_finding():
    review_shard = shard("service", ["core_business"])
    result = ShardReviewResult(
        shard=review_shard,
        review_content="",
        success=False,
        error_message="The read operation timed out",
    )

    summary = FindingTriagePolicy().triage([result])

    assert summary.recommended == []
    assert summary.need_manual_check == []
    assert summary.low_value_or_informational == []


def test_triage_dedupes_structured_findings_by_fingerprint():
    changed_file = ChangedFile(
        old_path="CommandTypeEnum.java",
        new_path="CommandTypeEnum.java",
        role="model",
        is_high_risk=True,
        risk_tags=["core_business"],
    )
    finding = ReviewFinding(
        severity="suggestion",
        category="exception",
        file="CommandTypeEnum.java",
        method="parse",
        line=50,
        problem="异常处理方式过于简单，直接抛出 RuntimeException 可能会导致调用方难以定位问题。",
        impact="调用方可能无法准确判断失败原因。",
        suggestion="建议使用自定义异常并提供更详细的错误信息。",
        confidence="high",
        fingerprint="same-fp",
        code_snippet="throw new RuntimeException(\"invalid command type\");",
    )
    result = result_with_finding(changed_file, finding)
    duplicated_result = ShardReviewResult(
        shard=result.shard,
        review_content=result.review_content,
        structured_findings=[finding, finding],
    )

    summary = FindingTriagePolicy().triage([duplicated_result])

    total = len(summary.recommended) + len(summary.need_manual_check) + len(summary.low_value_or_informational)
    assert total == 1


def test_triage_downgrades_generic_exception_style_advice_to_manual_check():
    changed_file = ChangedFile(
        old_path="PaymentService.java",
        new_path="PaymentService.java",
        role="service",
        is_high_risk=True,
        risk_tags=["core_business"],
    )
    finding = ReviewFinding(
        severity="warning",
        category="exception",
        file="PaymentService.java",
        method="pay",
        line=88,
        problem="捕获到异常后直接抛出新的运行时异常，可能导致调用方误判。",
        impact="调用方难以区分具体异常类型。",
        suggestion="建议根据具体异常类型处理，或者使用自定义异常。",
        confidence="high",
        fingerprint="fp-generic-exception",
        code_snippet="catch (Exception e) { throw new RuntimeException(e); }",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 0
    assert len(summary.need_manual_check) == 1


def test_triage_keeps_swallowed_exception_recommended():
    changed_file = ChangedFile(
        old_path="MessageConsumer.java",
        new_path="MessageConsumer.java",
        role="async",
        is_high_risk=True,
        risk_tags=["async_reliability"],
    )
    finding = ReviewFinding(
        severity="warning",
        category="exception",
        file="MessageConsumer.java",
        method="consume",
        line=42,
        problem="catch 块吞掉异常，没有记录日志，也没有更新失败状态。",
        impact="消息处理失败后不可观测，任务状态可能一直停留在处理中。",
        suggestion="记录错误日志，并将任务更新为失败状态或进入重试队列。",
        confidence="high",
        fingerprint="fp-swallowed-exception",
        code_snippet="catch (Exception e) { }",
    )

    summary = FindingTriagePolicy().triage([result_with_finding(changed_file, finding)])

    assert len(summary.recommended) == 1
