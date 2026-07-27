# AI Code Review Agent

面向开发者的 AI Code Review 辅助工具，支持本地 Git Diff 与 GitHub/GitLab Webhook 触发。项目重点解决大 Diff 场景下的上下文规划、分片评审、并行调用稳定性和 Review 结果可读性问题。

## 当前核心链路

```text
Git Diff / PR Webhook
  -> RiskScorer 识别高风险文件
  -> ContextPlanner 按上下文预算补充完整文件内容
  -> MasterReviewAgent 判断是否切片
  -> WorkerReviewAgent 并行调用 OpenAI-compatible LLM
  -> FindingTriagePolicy 过滤低证据建议
  -> MarkdownReportWriter 输出 Summary / Inline Review
```

## 真实评审示例

示例 PR：[CuiJh0123/group-buy-pintuan#3](https://github.com/CuiJh0123/group-buy-pintuan/pull/3)

该 PR 用于验证中小规模后端变更的评审效果，评审过程由 GitHub Webhook 触发，并使用 OpenAI-compatible 模型完成分片 Review。

下面摘录一次真实 Review Report 的核心结果：

```markdown
## Metadata

- Base: `bf1bae69be630f05ba8550acb085572cd265d5eb`
- Head: `fe9a897ff78caf9bc5442b04df3d67db870e9e6c`
- Diff mode: `merge-base(base...head)`
- Diff chars: `16263`
- Changed files: `12`
- High-risk files: `9`
- Slicing decision: `True`
- Slicing reason: `context_budget_exceeded: diff chars 16263 > max 16000`
- Shard count: `6`
- Profile source: `default`
- Context strategy: `medium_change_risk_budgeted_context`

## Executive Summary

- Worker success: `6`
- Worker failed: `0`
- Role distribution: `{'data_access': 2, 'model': 4, 'service': 5, 'async': 1}`
- Risk distribution: `{'P1': 6, 'P2': 3, 'P0': 3}`
- Review depth distribution: `{'full_context': 9, 'diff_only': 3}`

## Finding Triage

LLM 输出在本报告中作为候选 finding，以下分组由本地规则生成，用于区分优先级和人工确认边界。

### Recommended Findings

- `shard-2` [error/mq_reliability] MQ 消费者捕获异常后未记录日志也未重新抛出，导致 Spring AMQP 认为消息消费成功并自动 ACK。
  - Reason: 质量门禁 score=11: has_line, has_code_snippet, code_snippet_actionable, high_confidence, deterministic_bug_signal, mq_reliability_evidence
  - Files: `group-buy-market-jiahao-trigger/src/main/java/cn/jiahao/trigger/listener/TeamRefundTopicListener.java`
  - Snippet: Problem: MQ 消费者捕获异常后未记录日志也未重新抛出，导致 Spring AMQP 认为消息消费成功并自动 ACK。Impact: 若业务逻辑执行失败（如数据库异常、JSON 解析失败），消息将丢失，退款后库存无法恢复，造成资损且无告警，事务回滚但消息已确认导致数据不一致。Suggestion: catch 块中记录错误日志（包含消息内容和异常堆栈），并重新抛出异常（或手动 Nack）以触发 MQ 重试机制或进入死信队列。

### Need Manual Check

- `shard-1` [warning/concurrency] 锁过期时间单位与数值不匹配。数值 `30*24*60*60*1000L` 是毫秒数，但单位指定为 `TimeUnit.MINUTES`，导致锁过期时间变为约 4932 年。
  - Files: `group-buy-market-jiahao-infrastructure/src/main/java/cn/jiahao/infrastructure/adapter/repository/ITradeRepositoryImpl.java`
  - Suggestion: 将时间单位改为 `TimeUnit.MILLISECONDS`，或将数值调整为分钟数 `30*24*60`。

- `shard-1` [warning/concurrency] 获取锁成功后，代码中缺少 finally 块释放锁（lockKey）。
  - Files: `group-buy-market-jiahao-infrastructure/src/main/java/cn/jiahao/infrastructure/adapter/repository/ITradeRepositoryImpl.java`
  - Suggestion: 增加 finally 块，在其中调用 `redisService.remove(lockKey)` 确保锁必然释放。

- `shard-1` [warning/exception] 异常捕获逻辑错误。当 incr 失败时，直接删除了业务库存 Key 而非锁 Key。
  - Files: `group-buy-market-jiahao-infrastructure/src/main/java/cn/jiahao/infrastructure/adapter/repository/ITradeRepositoryImpl.java`
  - Suggestion: 移除该删除业务 Key 的逻辑；若需保证一致性，应记录日志或进行补偿，而非直接删除业务数据。

- `shard-3` [warning/cache_consistency] Redis 恢复库存 Key 后缀大小写不一致。实例方法使用 `_Recovery`，而静态方法使用 `_recovery`。
  - Files: `group-buy-market-jiahao-domain/src/main/java/cn/jiahao/domain/trade/service/lock/factory/TradeRuleLockFilterFactory.java`
  - Suggestion: 统一 Key 生成逻辑中的后缀大小写，避免库存恢复和库存查询使用不同 Redis Key。

- `shard-3` [warning/exception] 缺少空指针防御。`getRefundTypeEnumVOByCode` 可能返回 null，且 `refundOrderStrategyMap.get` 也可能返回 null，后续直接调用方法会导致 NPE。
  - Files: `group-buy-market-jiahao-domain/src/main/java/cn/jiahao/domain/trade/service/refund/TradeRefundOrderService.java`
  - Suggestion: 在调用策略前增加 null 判断，缺少策略时返回明确业务异常。

- `shard-4` [warning/exception] 当入参 type 为 null 时，switch 语句会直接抛出 NullPointerException，而不是预期的 RuntimeException。
  - Files: `group-buy-market-jiahao-domain/src/main/java/cn/jiahao/domain/trade/model/valobj/RefundTypeEnumVO.java`
  - Suggestion: 在 switch 前增加 null 判断，明确处理非法参数。
```

该示例体现了工具在真实 PR 中的运行效果：对中小 Diff 自动切分为多个 Review Shard，为高风险文件补充完整上下文，Worker 并行评审全部成功，并通过质量门禁将明确问题与人工确认项分层展示。

## 目录结构

```text
python-code-review/
  pyproject.toml
  README.md
  .env.example
  .code-review.example.yml
  src/code_review/
    app/                 # 应用编排层
    domain/              # 领域模型、风险评分、上下文规划、Prompt 策略
    infrastructure/      # Git、LLM、Profile、报告输出等外部能力
    interfaces/          # CLI / FastAPI Webhook 入口
    platform/            # GitHub / GitLab 平台适配
  tests/
```

## 环境变量

真实调用大模型时需要：

```bash
export OPENAI_API_KEY="你的 API Key"
export OPENAI_MODEL="gpt-4o-mini"
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

如果你用的是 OpenAI-compatible 平台，只需要把 `OPENAI_BASE_URL` 改成对应平台的 `/v1` 地址。

千问百炼 OpenAI-compatible 示例：

```bash
export OPENAI_API_KEY="你的百炼 API Key"
export OPENAI_MODEL="qwen-plus"
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

大 PR 或较慢模型建议调大超时并降低并发：

```bash
export OPENAI_TIMEOUT_SECONDS=180
export CODE_REVIEW_MAX_WORKERS=2
export CODE_REVIEW_MAX_REVIEW_ROUNDS=3
```

## 本地 Mock 跑通

不需要 API Key：

```bash
cd /Users/cuijiahao/Desktop/OpenAi-Code-Review-Repository-master/python-code-review
PYTHONPATH=src python3 -m code_review.interfaces.cli --mock
```

或在项目根目录：

```bash
PYTHONPATH=src python3 -m code_review.interfaces.cli --mock
```

## 在真实 Git 仓库中运行

比较任意两个本地 commit：

```bash
PYTHONPATH=src python3 -m code_review.interfaces.cli \
  --repo /path/to/your/repo \
  --base 2f3a91c \
  --head 7bd20aa
```

比较某个历史提交到当前工作分支最新提交：

```bash
PYTHONPATH=src python3 -m code_review.interfaces.cli \
  --repo /path/to/your/repo \
  --base HEAD~3 \
  --head HEAD
```

比较两个本地分支的直接差异：

```bash
PYTHONPATH=src python3 -m code_review.interfaces.cli \
  --repo /path/to/your/repo \
  --base master \
  --head feature/code-review-agent
```

评审 feature 分支相对 master 的全部变更，推荐使用 `--merge-base`：

```bash
PYTHONPATH=src python3 -m code_review.interfaces.cli \
  --repo /path/to/your/repo \
  --base master \
  --head feature/code-review-agent \
  --merge-base
```

参数说明：

- `--base`：起点 ref，可以是 commit hash、branch、tag、`HEAD~n`。
- `--head`：终点 ref，可以是 commit hash、branch、tag、`HEAD~n`。
- `--merge-base`：使用 `git diff base...head`，适合分支评审；不加时使用 `git diff base head`，适合精确比较两个提交。

## 切片策略

MasterReviewAgent 不直接让 LLM 判断是否切片，而是使用稳定的规则策略：

```text
1. diff 字符数超过 max_chars_per_shard
2. 变更文件数超过 max_files_per_shard
3. Java 后端高风险文件数量达到 max_high_risk_files_per_shard
```

默认值：

```text
max_chars_per_shard = 12000
max_files_per_shard = 5
max_high_risk_files_per_shard = 2
max_workers = 4
max_review_rounds = 3
```

高风险 Java 后端文件包括：

```text
DAO / Mapper / Repository / Mapper XML
Service / Controller / Adapter / Gateway / Client
Order / Payment / Trade / Inventory / Stock / Settlement 等业务关键词
Consumer / Listener / MQ / Job / Task / Scheduled / Compensate
application-prod.yml / bootstrap-prod.yml
```

自定义切片阈值：

```bash
PYTHONPATH=src python3 -m code_review.interfaces.cli \
  --repo /path/to/java-backend-repo \
  --base master \
  --head feature/order-fix \
  --merge-base \
  --max-chars-per-shard 12000 \
  --max-files-per-shard 5 \
  --max-high-risk-files-per-shard 2 \
  --max-workers 4 \
  --max-review-rounds 3
```

强制演示切片：

```bash
PYTHONPATH=src python3 -m code_review.interfaces.cli \
  --mock \
  --max-chars-per-shard 180 \
  --max-workers 2
```
