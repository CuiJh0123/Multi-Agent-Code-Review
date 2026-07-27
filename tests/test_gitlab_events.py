from code_review.platform.gitlab.events import GitLabWebhookParser


def review_payload(note: str = "/cr") -> dict:
    return {
        "object_kind": "note",
        "user": {"username": "dev1"},
        "project_id": 100,
        "project": {
            "id": 100,
            "git_http_url": "https://gitlab.example.com/group/demo.git",
        },
        "object_attributes": {
            "note": note,
            "noteable_type": "MergeRequest",
            "noteable_iid": 8,
        },
        "merge_request": {
            "iid": 8,
            "source_branch": "feature/order",
            "target_branch": "master",
            "source_sha": "abc123",
            "target_sha": "def456",
        },
    }


def test_gitlab_parser_accepts_merge_request_cr_note():
    parsed = GitLabWebhookParser().parse(review_payload())

    assert parsed.should_review
    assert parsed.trigger is not None
    assert parsed.trigger.project_id == "100"
    assert parsed.trigger.merge_request_iid == 8
    assert parsed.trigger.head_ref == "abc123"
    assert parsed.trigger.base_ref == "def456"
    assert parsed.trigger.author_username == "dev1"


def test_gitlab_parser_ignores_non_cr_note():
    parsed = GitLabWebhookParser().parse(review_payload("LGTM"))

    assert not parsed.should_review
    assert parsed.reason == "note body is not /cr"


def test_gitlab_parser_ignores_non_mr_note():
    payload = review_payload()
    payload["object_attributes"]["noteable_type"] = "Issue"

    parsed = GitLabWebhookParser().parse(payload)

    assert not parsed.should_review
    assert parsed.reason == "note is not for merge request"
