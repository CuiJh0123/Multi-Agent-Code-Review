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

| 项目 | 结果 |
| --- | --- |
| Changed files | 12 |
| Diff chars | 16,263 |
| High-risk files | 9 |
| Context strategy | `medium_change_risk_budgeted_context` |
| Slicing decision | `diff chars 16263 > max 16000` |
| Shard count | 6 |
| Worker success / failed | 6 / 0 |
| Review depth | 9 个文件 `full_context`，3 个文件 `diff_only` |

代表性评审结论：

- `Error / mq_reliability`：MQ 消费者捕获异常后未记录日志，也未重新抛出异常，可能导致消息被自动 ACK，业务失败但消息不再重试。
- `Warning / concurrency`：分布式锁过期时间的数值和单位不匹配，可能导致锁长时间不释放。
- `Warning / cache_consistency`：Redis 恢复库存 Key 的后缀大小写不一致，可能造成库存恢复和查询使用不同 Key。
- `Warning / exception`：枚举解析方法在入参为 `null` 时可能直接抛出 `NullPointerException`，异常语义不清晰。

该示例体现了工具的几个核心能力：

- 对中小 Diff 自动切分为多个 Review Shard；
- 根据文件职责和风险等级为核心文件补充完整上下文；
- Worker 并行评审全部成功，避免大 Diff 单次请求超时；
- 通过质量门禁将明确问题和人工确认项分层展示，减少泛化建议对 PR 评论的干扰。

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
