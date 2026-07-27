import json
import urllib.error
import urllib.request

from code_review.infrastructure.config import OpenAiCompatibleConfig
from code_review.infrastructure.llm.base import LlmClient


class OpenAiCompatibleClient(LlmClient):
    """OpenAI-compatible Chat Completions 客户端。

    只依赖标准库，调用：
    POST {OPENAI_BASE_URL}/chat/completions
    """

    def __init__(self, config: OpenAiCompatibleConfig) -> None:
        self._config = config

    def chat(self, prompt: str) -> str:
        payload = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self._config.base_url}/chat/completions",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP 调用失败：status={error.code}, body={error_body}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"LLM 网络调用失败：{error}") from error

        result = json.loads(body)
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError(f"LLM 响应结构不符合 OpenAI Chat Completions 格式：{body}") from error

