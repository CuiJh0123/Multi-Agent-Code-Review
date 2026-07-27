import json
import re

from code_review.infrastructure.llm.base import LlmClient


class MockLlmClient(LlmClient):
    """本地验收用，不依赖真实 API Key。"""

    def chat(self, prompt: str) -> str:
        file_path, line = self._first_diff_line(prompt)
        return json.dumps(
            {
                "summary": "本 shard 变更了关键代码路径，Mock 模式返回一条可定位的示例 finding。",
                "findings": [
                    {
                        "severity": "warning",
                        "category": "test",
                        "file": file_path,
                        "method": "",
                        "line": line,
                        "code_snippet": "// TODO: 补充该变更对应的边界条件测试",
                        "problem": "本次 diff 涉及关键代码变更，但缺少对应测试用例。",
                        "impact": "后续修改相关逻辑时，缺少测试会导致回归问题不容易被发现。",
                        "suggestion": "补充正常路径、空值/非法参数、异常路径等最小测试集；如果该文件只是配置或文档变更，可在 PR 中说明无需测试的原因。",
                        "confidence": "medium",
                    }
                ],
            },
            ensure_ascii=False,
        )

    def _first_diff_line(self, prompt: str) -> tuple[str, int]:
        match = re.search(r"(?m)^([^:\n]+):(\d+)\s+\+\s+", prompt)
        if not match:
            return "unknown", 1
        return match.group(1), int(match.group(2))
