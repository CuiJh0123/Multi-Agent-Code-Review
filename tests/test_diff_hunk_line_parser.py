from code_review.domain.diff_hunk_line_parser import DiffHunkLineParser


def test_diff_hunk_line_parser_extracts_new_file_lines():
    diff = (
        "diff --git a/OrderService.java b/OrderService.java\n"
        "--- a/OrderService.java\n"
        "+++ b/OrderService.java\n"
        "@@ -10,2 +10,3 @@\n"
        " public class OrderService {\n"
        "+    return true;\n"
        " }\n"
    )

    evidence = DiffHunkLineParser().parse(diff)

    assert evidence[0].file_path == "OrderService.java"
    assert evidence[0].line == 10
    assert evidence[0].kind == "context"
    assert evidence[1].line == 11
    assert evidence[1].kind == "added"
    assert evidence[1].content.strip() == "return true;"


def test_diff_hunk_line_parser_renders_prompt_evidence():
    diff = (
        "diff --git a/A.java b/A.java\n"
        "--- a/A.java\n"
        "+++ b/A.java\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    rendered = DiffHunkLineParser().render_for_prompt(diff)

    assert "A.java:1 + new" in rendered
