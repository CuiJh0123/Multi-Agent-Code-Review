from code_review.domain.models import ReviewShard
from code_review.domain.diff_hunk_line_parser import DiffHunkLineParser


class PromptBuilder:
    """构造代码评审 Prompt。

    这里先复现 Java 版的核心提示词，后续可以演进为：
    - 分语言评审模板
    - 分严重级别输出
    - 结构化 JSON 输出
    - 多 Agent 的上下文裁剪策略
    """

    def build(self, diff_text: str) -> str:
        return (
            "你是一个高级编程架构师，精通架构设计、工程质量、代码可维护性和常见编程语言。\n"
            "请根据下面的 git diff 进行代码评审，重点关注：\n"
            "1. 是否存在明显 bug 或边界条件遗漏；\n"
            "2. 是否存在并发、安全、性能、资源释放问题；\n"
            "3. 代码可读性、可维护性是否可以提升；\n"
            "4. 如果有问题，请给出具体原因和修改建议。\n\n"
            "请使用中文输出，按【问题】【影响】【建议】组织。\n\n"
            "git diff 如下：\n"
            f"{diff_text}"
        )

    def build_for_shard(self, shard: ReviewShard) -> str:
        file_list = "\n".join(f"- {file.display_path} role={file.role} risk_tags={file.risk_tags}" for file in shard.files)
        checklist = self._build_checklist(shard.role, shard.risk_tags)
        checklist_text = "\n".join(f"- {item}" for item in checklist)
        profile_rules_text = "\n".join(f"- {rule}" for rule in shard.profile_rules) if shard.profile_rules else "- 无"
        risk_reasons_text = "\n".join(f"- {reason}" for reason in shard.risk_reasons) if shard.risk_reasons else "- 无"
        context_text = shard.context_text if shard.context_text else "未提供额外完整上下文，本 shard 基于 diff 评审。"
        line_evidence = self._hunk_line_parser.render_for_prompt(shard.diff_text)

        return (
            "你是一个资深 Java 后端代码评审工程师，熟悉 Spring Boot、DDD、MyBatis、MySQL、Redis、MQ "
            "以及常见后端工程质量问题。\n\n"
            f"当前评审分片：{shard.shard_id} ({shard.index}/{shard.total})\n"
            f"分片职责类型：{shard.role}\n"
            f"风险标签：{shard.risk_tags}\n"
            f"风险等级：{shard.risk_level}\n"
            f"风险分数：{shard.risk_score}\n"
            f"上下文深度：{shard.context_depth}\n"
            f"上下文原因：{shard.context_reason}\n"
            f"涉及方法：{shard.method_names}\n"
            "涉及文件：\n"
            f"{file_list}\n\n"
            "项目级 Review Rules：\n"
            f"{profile_rules_text}\n\n"
            "本 shard 风险原因：\n"
            f"{risk_reasons_text}\n\n"
            "请基于下面 checklist 做专项评审：\n"
            f"{checklist_text}\n\n"
            "输出要求：\n"
            "1. 只输出合法 JSON，不要输出 Markdown、解释文字或代码块；\n"
            "2. JSON schema 必须为："
            "{\"summary\":\"本 shard 摘要\",\"findings\":[{\"severity\":\"error|warning|suggestion\","
            "\"category\":\"concurrency|idempotency|transaction|sql_performance|security|config|maintainability|observability|test|exception|cache_consistency|mq_reliability|other\","
            "\"file\":\"涉及文件路径\",\"method\":\"涉及方法，没有则为空字符串\",\"line\":123,"
            "\"code_snippet\":\"触发问题的代码片段，没有则为空字符串\","
            "\"problem\":\"问题\",\"impact\":\"影响\",\"suggestion\":\"建议\",\"confidence\":\"high|medium|low\"}]}\n"
            "3. 使用中文填写 summary/problem/impact/suggestion；\n"
            "4. 只指出和当前 diff 直接相关的问题，避免泛泛建议；\n"
            "5. finding 必须尽量给出 file 和 line；line 必须来自下面“可定位 diff 行”；\n"
            "6. 如果只能给泛泛建议、无法定位到具体代码行，请不要输出 finding；\n"
            "7. Error 只用于确定性 bug、安全漏洞、SQL 语法错误、空 catch、确定会导致数据不一致的问题；\n"
            "8. 对 Interface/Enum/VO/DTO/Entity 等契约或数据结构文件，只评审确定性语义错误、兼容性破坏或安全问题，不要泛化推断事务/锁/幂等问题；\n"
            "9. 并发/幂等/事务类 finding 必须指出共享资源、竞争窗口、唯一业务键、状态重复推进、异常回滚路径等具体证据；\n"
            "10. 性能类 finding 必须说明索引现状、执行计划、数据量级或确定的低效代码；缺少证据时最多给 suggestion；\n"
            "11. 每个 finding 必须能回答：哪一行代码、为什么错、什么场景触发、应该怎么改；否则不要输出；\n"
            "12. 如果没有明显问题，findings 返回空数组。\n\n"
            "可定位 diff 行如下，格式为 file:line +/- code：\n"
            f"{line_evidence}\n\n"
            "补充上下文如下：\n"
            f"{context_text}\n\n"
            "git diff 如下：\n"
            f"{shard.diff_text}"
        )

    def _build_checklist(self, role: str, risk_tags: list) -> list:
        checklist = [
            "是否存在明显 bug、空指针、边界条件遗漏",
            "异常处理是否会导致调用方误判或数据不一致",
            "是否存在并发一致性、幂等或重复提交风险",
            "代码变更是否影响核心链路的可维护性和可观测性",
        ]

        if role == "api":
            checklist.extend(
                [
                    "Controller/API 入参校验是否完整",
                    "鉴权、权限边界、异常响应是否合理",
                    "接口是否需要幂等控制或重复请求防护",
                ]
            )

        if role == "service" or "core_business" in risk_tags:
            checklist.extend(
                [
                    "业务状态流转是否完整，是否存在漏状态或重复状态",
                    "事务边界是否合理，异常回滚语义是否正确",
                    "关键资源占用、释放和补偿路径是否存在一致性风险",
                ]
            )

        if role == "data_access" or "data_access" in risk_tags:
            checklist.extend(
                [
                    "SQL 是否可能慢查询，是否需要索引支撑",
                    "是否存在行锁竞争、事务范围过大或 N+1 查询问题",
                    "MyBatis 参数绑定和动态 SQL 是否安全可靠",
                ]
            )

        if role == "async" or "async_reliability" in risk_tags:
            checklist.extend(
                [
                    "MQ/Job/Task 是否具备幂等、重试和失败补偿",
                    "是否可能重复消费、消息丢失或补偿任务重复执行",
                    "异步链路异常是否可观测、可恢复",
                ]
            )

        if role == "config" or "production_config" in risk_tags:
            checklist.extend(
                [
                    "生产配置是否存在敏感信息或错误环境配置",
                    "连接池、超时、重试、线程池参数是否可能影响稳定性",
                ]
            )

        if role == "db_script":
            checklist.extend(
                [
                    "表结构、索引、唯一约束是否能支撑核心查询",
                    "初始化/清理/验证 SQL 是否可能误删数据或覆盖业务数据",
                    "SQL 脚本是否具备本地环境和测试环境的可重复执行能力",
                ]
            )

        return checklist
    def __init__(self) -> None:
        self._hunk_line_parser = DiffHunkLineParser()
