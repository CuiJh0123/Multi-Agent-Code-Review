import os
from pathlib import Path

from code_review.infrastructure.config import review_request_from_env


def test_review_request_from_env_applies_operational_limits():
    old_values = {
        "CODE_REVIEW_MAX_CHARS_PER_SHARD": os.environ.get("CODE_REVIEW_MAX_CHARS_PER_SHARD"),
        "CODE_REVIEW_MAX_FILES_PER_SHARD": os.environ.get("CODE_REVIEW_MAX_FILES_PER_SHARD"),
        "CODE_REVIEW_MAX_HIGH_RISK_FILES_PER_SHARD": os.environ.get("CODE_REVIEW_MAX_HIGH_RISK_FILES_PER_SHARD"),
        "CODE_REVIEW_MAX_WORKERS": os.environ.get("CODE_REVIEW_MAX_WORKERS"),
    }
    try:
        os.environ["CODE_REVIEW_MAX_CHARS_PER_SHARD"] = "18000"
        os.environ["CODE_REVIEW_MAX_FILES_PER_SHARD"] = "3"
        os.environ["CODE_REVIEW_MAX_HIGH_RISK_FILES_PER_SHARD"] = "1"
        os.environ["CODE_REVIEW_MAX_WORKERS"] = "2"

        request = review_request_from_env(
            repo_path=Path("."),
            base_ref="base",
            head_ref="head",
            use_merge_base=True,
        )

        assert request.max_chars_per_shard == 18000
        assert request.max_files_per_shard == 3
        assert request.max_high_risk_files_per_shard == 1
        assert request.max_workers == 2
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
