from pathlib import Path
from typing import Dict, List, Tuple

from code_review.domain.models import ReviewProfile


class ReviewProfileDefaults:
    """Default zero-config profile for Java backend projects."""

    DEFAULT_HIGH_RISK = [
        "src/main/java/**/controller/**",
        "src/main/java/**/service/**",
        "src/main/java/**/domain/**",
        "src/main/java/**/repository/**",
        "src/main/java/**/dao/**",
        "src/main/java/**/mapper/**",
        "src/main/java/**/consumer/**",
        "src/main/java/**/listener/**",
        "src/main/java/**/job/**",
        "src/main/java/**/task/**",
        "src/main/resources/mapper/**/*.xml",
        "src/main/resources/application*.yml",
        "src/main/resources/bootstrap*.yml",
        "db/migration/**",
        "sql/**",
    ]
    DEFAULT_LOW_RISK = [
        "docs/**",
        "doc/**",
        "**/*.md",
        "README.md",
        "src/test/**",
        "**/*Test.java",
        "**/*Tests.java",
        "grafana/**",
        "jmeter/**",
        "dashboard/**",
    ]
    DEFAULT_RULES = [
        "Controller/API 变更需要关注参数校验、异常响应和幂等控制",
        "Service/Domain 变更需要关注业务状态流转、事务边界和异常回滚语义",
        "Repository/Mapper/SQL 变更需要关注慢查询、索引、行锁竞争和参数绑定安全",
        "Redis/缓存相关变更需要关注缓存一致性、原子操作和过期时间",
        "MQ/Consumer/Job 变更需要关注幂等、重复消费、重试和失败补偿",
        "配置文件变更需要关注敏感信息、环境隔离、连接池、超时和线程池参数",
    ]

    @classmethod
    def default_profile(cls) -> ReviewProfile:
        return ReviewProfile(
            source="default",
            high_risk=list(cls.DEFAULT_HIGH_RISK),
            low_risk=list(cls.DEFAULT_LOW_RISK),
            rules=list(cls.DEFAULT_RULES),
            validation_warnings=[],
        )


class ReviewProfileValidator:
    SUPPORTED_FIELDS = {"version", "high_risk", "low_risk", "rules"}

    def validate(self, raw: Dict, repo_tree: List[str], source: str) -> ReviewProfile:
        warnings: List[str] = []
        if not isinstance(raw, dict):
            return ReviewProfile(
                source=source,
                validation_warnings=["profile root must be a mapping; ignored invalid profile"],
            )

        for key in raw.keys():
            if key not in self.SUPPORTED_FIELDS:
                warnings.append(f"unsupported field ignored: {key}")

        high_risk, high_warnings = self._validate_patterns(raw.get("high_risk", []), "high_risk", repo_tree)
        low_risk, low_warnings = self._validate_patterns(raw.get("low_risk", []), "low_risk", repo_tree)
        rules, rule_warnings = self._validate_rules(raw.get("rules", []))
        warnings.extend(high_warnings)
        warnings.extend(low_warnings)
        warnings.extend(rule_warnings)

        return ReviewProfile(
            source=source,
            high_risk=high_risk,
            low_risk=low_risk,
            rules=rules,
            validation_warnings=warnings,
        )

    def merge_with_default(self, profile: ReviewProfile) -> ReviewProfile:
        default = ReviewProfileDefaults.default_profile()
        return ReviewProfile(
            source=profile.source,
            high_risk=self._dedupe(default.high_risk + profile.high_risk),
            low_risk=self._dedupe(default.low_risk + profile.low_risk),
            rules=self._dedupe(default.rules + profile.rules),
            validation_warnings=profile.validation_warnings,
        )

    def _validate_patterns(self, value, field_name: str, repo_tree: List[str]) -> Tuple[List[str], List[str]]:
        if value is None:
            return [], []
        if not isinstance(value, list):
            return [], [f"{field_name} must be a list; ignored"]

        patterns: List[str] = []
        warnings: List[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                warnings.append(f"{field_name} contains non-string or empty pattern; ignored")
                continue
            pattern = item.strip()
            if not self._matches_tree(pattern, repo_tree):
                warnings.append(f"{field_name} pattern does not match repository tree: {pattern}")
            patterns.append(pattern)
        return patterns, warnings

    def _validate_rules(self, value) -> Tuple[List[str], List[str]]:
        if value is None:
            return [], []
        if not isinstance(value, list):
            return [], ["rules must be a list; ignored"]
        rules: List[str] = []
        warnings: List[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                warnings.append("rules contains non-string or empty rule; ignored")
                continue
            rules.append(item.strip())
        return rules, warnings

    def _matches_tree(self, pattern: str, repo_tree: List[str]) -> bool:
        if not repo_tree:
            return True
        return any(Path(path).match(pattern) or self._globstar_match(path, pattern) for path in repo_tree)

    def _globstar_match(self, path: str, pattern: str) -> bool:
        if pattern.startswith("**/"):
            return Path(path).match(pattern[3:]) or Path(path).match(pattern)
        if "/**/" in pattern:
            prefix, suffix = pattern.split("/**/", 1)
            return path.startswith(prefix.rstrip("/") + "/") and Path(path).match(f"**/{suffix}")
        if pattern.endswith("/**"):
            return path.startswith(pattern[:-3].rstrip("/") + "/")
        return False

    def _dedupe(self, values: List[str]) -> List[str]:
        seen = set()
        result = []
        for value in values:
            if value not in seen:
                result.append(value)
                seen.add(value)
        return result


class TemporaryProfileGenerator:
    """Interface for optional repo-tree-to-profile generation."""

    def generate(self, repo_tree: List[str]) -> ReviewProfile:
        raise NotImplementedError


class MockTemporaryProfileGenerator(TemporaryProfileGenerator):
    def generate(self, repo_tree: List[str]) -> ReviewProfile:
        high_risk = [path for path in repo_tree if any(token in path.lower() for token in ("service", "repository", "mapper", "controller"))]
        return ReviewProfile(
            source="temporary_generated",
            high_risk=high_risk[:20],
            low_risk=["docs/**", "**/*.md", "src/test/**"],
            rules=["自动生成 profile：优先关注核心后端分层、数据访问和配置变更"],
        )
