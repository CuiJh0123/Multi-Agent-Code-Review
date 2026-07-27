from code_review.platform.github.events import GitHubWebhookParser


def review_payload(comment_body: str = "/cr") -> dict:
    return {
        "action": "created",
        "comment": {
            "body": comment_body,
            "user": {"login": "dev1"},
        },
        "issue": {
            "number": 12,
            "pull_request": {
                "url": "https://api.github.com/repos/example/demo/pulls/12",
            },
        },
        "repository": {
            "full_name": "example/demo",
            "clone_url": "https://github.com/example/demo.git",
        },
        "pull_request": {
            "base": {"ref": "main", "sha": "base123"},
            "head": {"ref": "feature/order", "sha": "head456"},
        },
    }


def test_github_parser_accepts_pr_cr_comment():
    parsed = GitHubWebhookParser().parse(review_payload(), event_name="issue_comment")

    assert parsed.should_review
    assert parsed.trigger is not None
    assert parsed.trigger.owner == "example"
    assert parsed.trigger.repo == "demo"
    assert parsed.trigger.pull_number == 12
    assert parsed.trigger.review_base_ref == "base123"
    assert parsed.trigger.review_head_ref == "head456"
    assert parsed.trigger.author_login == "dev1"


def test_github_parser_ignores_non_cr_comment():
    parsed = GitHubWebhookParser().parse(review_payload("LGTM"), event_name="issue_comment")

    assert not parsed.should_review
    assert parsed.reason == "comment body is not /cr"


def test_github_parser_ignores_issue_comment_not_on_pr():
    payload = review_payload()
    del payload["issue"]["pull_request"]

    parsed = GitHubWebhookParser().parse(payload, event_name="issue_comment")

    assert not parsed.should_review
    assert parsed.reason == "comment is not on pull request"
