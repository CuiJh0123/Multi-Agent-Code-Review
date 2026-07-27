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
