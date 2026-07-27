from code_review.domain.diff_sections import FileDiffSectionParser
from code_review.domain.java_backend_risk_classifier import JavaBackendRiskClassifier
from code_review.infrastructure.git.diff_slicer_tool import DiffSlicerTool


def test_oversized_single_file_fallback_splitting():
    diff_text = (
        "diff --git a/docs/large-config.txt b/docs/large-config.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/docs/large-config.txt\n"
        "+++ b/docs/large-config.txt\n"
        "@@ -1,3 +1,8 @@\n"
        + "".join(f"+config.line.{i}=value{i}\n" for i in range(30))
    )
    tool = DiffSlicerTool(FileDiffSectionParser(), JavaBackendRiskClassifier())

    shards = tool.slice(diff_text, max_chars_per_shard=180)

    assert len(shards) > 1
    assert all(shard.files[0].display_path.endswith("large-config.txt") for shard in shards)
    assert all(shard.index == index for index, shard in enumerate(shards, start=1))


def test_same_java_method_is_not_split_even_when_over_soft_limit():
    repeated_lines = "".join(f"+        int value{i} = {i};\n" for i in range(20))
    diff_text = (
        "diff --git a/src/main/java/com/demo/OrderService.java b/src/main/java/com/demo/OrderService.java\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/main/java/com/demo/OrderService.java\n"
        "+++ b/src/main/java/com/demo/OrderService.java\n"
        "@@ -1,5 +1,25 @@ public boolean lockOrder(String userId) {\n"
        " public boolean lockOrder(String userId) {\n"
        "-        return true;\n"
        f"{repeated_lines}"
        "+        return true;\n"
        " }\n"
    )
    tool = DiffSlicerTool(FileDiffSectionParser(), JavaBackendRiskClassifier())

    shards = tool.slice(diff_text, max_chars_per_shard=180)

    assert len(shards) == 1
    assert "lockOrder" in shards[0].diff_text


def test_different_java_methods_can_be_split():
    method_one = "".join(f"+        int left{i} = {i};\n" for i in range(12))
    method_two = "".join(f"+        int right{i} = {i};\n" for i in range(12))
    diff_text = (
        "diff --git a/src/main/java/com/demo/OrderService.java b/src/main/java/com/demo/OrderService.java\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/main/java/com/demo/OrderService.java\n"
        "+++ b/src/main/java/com/demo/OrderService.java\n"
        "@@ -1,5 +1,18 @@ public boolean lockOrder(String userId) {\n"
        " public boolean lockOrder(String userId) {\n"
        f"{method_one}"
        " }\n"
        "@@ -20,5 +33,18 @@ public boolean settleOrder(String orderId) {\n"
        " public boolean settleOrder(String orderId) {\n"
        f"{method_two}"
        " }\n"
    )
    tool = DiffSlicerTool(FileDiffSectionParser(), JavaBackendRiskClassifier())

    shards = tool.slice(diff_text, max_chars_per_shard=500)

    assert len(shards) == 2
    assert "lockOrder" in shards[0].diff_text
    assert "settleOrder" in shards[1].diff_text
