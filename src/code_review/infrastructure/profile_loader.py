from pathlib import Path
from typing import Dict, List

from code_review.domain.models import ReviewProfile
from code_review.domain.review_profile import ReviewProfileDefaults, ReviewProfileValidator, TemporaryProfileGenerator


class ReviewProfileLoader:
    """Load and validate `.code-review.yml` from a reviewed repository."""

    def __init__(
        self,
        validator: ReviewProfileValidator = None,
        temporary_generator: TemporaryProfileGenerator = None,
        enable_temporary_generation: bool = False,
    ) -> None:
        self._validator = validator or ReviewProfileValidator()
        self._temporary_generator = temporary_generator
        self._enable_temporary_generation = enable_temporary_generation

    def load(self, repo_path: Path, repo_tree: List[str]) -> ReviewProfile:
        profile_path = repo_path / ".code-review.yml"
        if profile_path.exists():
            raw = self._parse_simple_yaml(profile_path.read_text(encoding="utf-8"))
            profile = self._validator.validate(raw, repo_tree, source=".code-review.yml")
            return self._validator.merge_with_default(profile)

        if self._enable_temporary_generation and self._temporary_generator:
            generated = self._temporary_generator.generate(repo_tree)
            validated = self._validator.validate(
                {
                    "high_risk": generated.high_risk,
                    "low_risk": generated.low_risk,
                    "rules": generated.rules,
                },
                repo_tree,
                source="temporary_generated",
            )
            return self._validator.merge_with_default(validated)

        return ReviewProfileDefaults.default_profile()

    def _parse_simple_yaml(self, content: str) -> Dict:
        """Parse the intentionally small profile schema.

        Supported:
          version: 1
          high_risk:
            - "pattern"
          low_risk:
            - "pattern"
          rules:
            - "rule"
        """
        result: Dict = {}
        current_key = None

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("- "):
                if current_key is None:
                    continue
                result.setdefault(current_key, []).append(self._strip_quotes(line[2:].strip()))
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                current_key = key
                if value:
                    result[key] = self._parse_scalar(value)
                else:
                    result[key] = []
        return result

    def _parse_scalar(self, value: str):
        value = self._strip_quotes(value)
        if value.isdigit():
            return int(value)
        return value

    def _strip_quotes(self, value: str) -> str:
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            return value[1:-1]
        return value
