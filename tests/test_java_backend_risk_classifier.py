from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier


def test_application_local_yml_is_config_not_service():
    role, is_high_risk, risk_tags = JavaBackendRiskClassifier().classify(
        "group-buy-market-jiahao-app/src/main/resources/application-local.yml"
    )

    assert role == "config"
    assert is_high_risk is False
    assert risk_tags == []


def test_sql_file_is_db_script():
    role, is_high_risk, risk_tags = JavaBackendRiskClassifier().classify(
        "docs/dev-ops/mysql/sql/group-buy-market-local-schema.sql"
    )

    assert role == "db_script"
    assert is_high_risk is False
    assert risk_tags == []


def test_prod_config_is_high_risk_config():
    role, is_high_risk, risk_tags = JavaBackendRiskClassifier().classify(
        "src/main/resources/application-prod.yml"
    )

    assert role == "config"
    assert is_high_risk is True
    assert risk_tags == ["production_config"]


def test_value_object_is_model_not_service():
    role, is_high_risk, risk_tags = JavaBackendRiskClassifier().classify(
        "src/main/java/com/example/domain/payment/model/valobj/PaymentTypeEnum.java"
    )

    assert role == "model"
    assert is_high_risk is True
    assert risk_tags == ["core_business"]


def test_service_interface_is_model_contract():
    role, is_high_risk, risk_tags = JavaBackendRiskClassifier().classify(
        "src/main/java/com/example/domain/payment/service/IPaymentCommandService.java"
    )

    assert role == "model"
    assert is_high_risk is True
    assert risk_tags == ["core_business"]
