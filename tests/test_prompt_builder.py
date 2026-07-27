from code_review.domain.prompt_builder import PromptBuilder


def test_prompt_contains_diff_text():
    diff_text = "diff --git a/a.py b/a.py"
    prompt = PromptBuilder().build(diff_text)
    assert diff_text in prompt
    assert "代码评审" in prompt

