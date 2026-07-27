import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from code_review.domain.models import ReviewRequest


@dataclass(frozen=True)
class OpenAiCompatibleConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 60

    @staticmethod
    def from_env() -> "OpenAiCompatibleConfig":
        local_env = load_local_env()

        api_key = os.getenv("OPENAI_API_KEY") or local_env.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("缺少 OPENAI_API_KEY，请设置环境变量或 python-code-review/.env.local")

        return OpenAiCompatibleConfig(
            api_key=api_key,
            base_url=(os.getenv("OPENAI_BASE_URL") or local_env.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/"),
            model=os.getenv("OPENAI_MODEL") or local_env.get("OPENAI_MODEL", "gpt-4o-mini"),
            timeout_seconds=int(os.getenv("OPENAI_TIMEOUT_SECONDS") or local_env.get("OPENAI_TIMEOUT_SECONDS", "60")),
        )


def load_local_env() -> Dict[str, str]:
    env_path = find_local_env_file()
    if not env_path.exists():
        return {}

    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_local_env_file() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / ".env.local"
        if candidate.exists():
            return candidate
        if parent.name == "python-code-review":
            return parent / ".env.local"
    return Path.cwd() / ".env.local"


def review_request_from_env(**kwargs) -> ReviewRequest:
    """Build ReviewRequest with environment-overridable operational limits.

    Platform webhook paths do not expose CLI flags, so these values need to be
    controllable by environment variables when switching LLM providers.
    """
    local_env = load_local_env()
    return ReviewRequest(
        **kwargs,
        max_chars_per_shard=_env_int("CODE_REVIEW_MAX_CHARS_PER_SHARD", local_env, 12000),
        max_files_per_shard=_env_int("CODE_REVIEW_MAX_FILES_PER_SHARD", local_env, 5),
        max_high_risk_files_per_shard=_env_int("CODE_REVIEW_MAX_HIGH_RISK_FILES_PER_SHARD", local_env, 2),
        max_workers=_env_int("CODE_REVIEW_MAX_WORKERS", local_env, 4),
        max_review_rounds=_env_int("CODE_REVIEW_MAX_REVIEW_ROUNDS", local_env, 3),
    )


def _env_int(key: str, local_env: Dict[str, str], default: int) -> int:
    raw_value = os.getenv(key) or local_env.get(key)
    if raw_value is None or str(raw_value).strip() == "":
        return default
    try:
        return int(str(raw_value).strip())
    except ValueError as error:
        raise RuntimeError(f"{key} must be an integer") from error
