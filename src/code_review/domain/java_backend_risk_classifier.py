import os
from typing import List, Tuple


class JavaBackendRiskClassifier:
    """Rule-based classifier for Java backend review risk.

    第一版只做路径/文件名规则，不做 AST。
    """

    DATA_ACCESS_KEYWORDS = ("dao", "mapper", "repository")
    CORE_BUSINESS_KEYWORDS = (
        "order",
        "payment",
        "pay",
        "trade",
        "inventory",
        "stock",
        "settlement",
        "refund",
    )
    ASYNC_KEYWORDS = (
        "consumer",
        "listener",
        "mq",
        "job",
        "task",
        "scheduled",
        "compensate",
    )
    API_KEYWORDS = ("controller", "trigger", "interfaces", "api")
    SERVICE_KEYWORDS = ("service", "application", "domain")
    TEST_KEYWORDS = ("test", "tests")
    MODEL_PATH_MARKERS = (
        "/model/",
        "/entity/",
        "/aggregate/",
        "/valobj/",
        "/vo/",
        "/dto/",
        "/po/",
    )
    PROD_CONFIG_NAMES = (
        "application-prod.yml",
        "application-prod.yaml",
        "bootstrap-prod.yml",
        "bootstrap-prod.yaml",
    )
    CONFIG_NAMES = (
        "pom.xml",
        "build.gradle",
        "settings.gradle",
        "application.yml",
        "application.yaml",
        "application-local.yml",
        "application-local.yaml",
        "bootstrap.yml",
        "bootstrap.yaml",
        "bootstrap-local.yml",
        "bootstrap-local.yaml",
    )

    def classify(self, path: str) -> Tuple[str, bool, List[str]]:
        normalized = path.replace("\\", "/").lower()
        filename = os.path.basename(normalized)
        risk_tags: List[str] = []

        if not self._is_java_backend_candidate(normalized, filename):
            return "other", False, risk_tags

        if self._contains_any(normalized, self.DATA_ACCESS_KEYWORDS) or normalized.endswith("mapper.xml"):
            risk_tags.append("data_access")

        if self._contains_any(normalized, self.CORE_BUSINESS_KEYWORDS):
            risk_tags.append("core_business")

        if self._contains_any(normalized, self.ASYNC_KEYWORDS):
            risk_tags.append("async_reliability")

        if filename in self.PROD_CONFIG_NAMES:
            risk_tags.append("production_config")

        role = self._detect_role(normalized, filename, risk_tags)
        return role, bool(risk_tags), risk_tags

    def _detect_role(self, normalized: str, filename: str, risk_tags: List[str]) -> str:
        # Config and SQL scripts need to be recognized before generic
        # "application/service/domain" path keywords, otherwise files such as
        # application-local.yml are incorrectly classified as service code.
        if filename in self.CONFIG_NAMES or filename.endswith((".yml", ".yaml", ".properties")):
            return "config"
        if normalized.endswith(".sql"):
            return "db_script"
        if "data_access" in risk_tags:
            return "data_access"
        if "async_reliability" in risk_tags:
            return "async"
        if "production_config" in risk_tags:
            return "config"
        if self._contains_any(normalized, self.API_KEYWORDS):
            return "api"
        if self._is_model_or_contract(normalized, filename):
            return "model"
        if self._contains_any(normalized, self.SERVICE_KEYWORDS) or "core_business" in risk_tags:
            return "service"
        if self._contains_any(normalized, self.TEST_KEYWORDS) or filename.endswith("test.java"):
            return "test"
        return "other"

    def _is_model_or_contract(self, normalized: str, filename: str) -> bool:
        if any(marker in normalized for marker in self.MODEL_PATH_MARKERS):
            return True
        if filename.endswith(("enumvo.java", "enum.java", "entity.java", "vo.java", "dto.java")):
            return True
        if filename.startswith("i") and filename.endswith(".java") and "/service/" in normalized:
            return True
        return False

    def _is_java_backend_candidate(self, normalized: str, filename: str) -> bool:
        if normalized.endswith((".java", ".xml", ".yml", ".yaml", ".properties", ".sql")):
            return True
        if filename in ("pom.xml", "build.gradle", "settings.gradle"):
            return True
        return False

    def _contains_any(self, text: str, keywords: tuple) -> bool:
        return any(keyword in text for keyword in keywords)
