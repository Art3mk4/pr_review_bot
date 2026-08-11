from unittest.mock import MagicMock

import pytest
import responses

from pr_review_bot.services.review import process_pr


@responses.activate
def test_process_pr_happy_path(config, github_client, ai_client) -> None:
    pr_number = 42
    repo = "owner/repo"
    diff_text = "diff --git a/x b/x\n+change"

    responses.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/pulls/42",
        body=diff_text,
        status=200,
    )
    responses.add(
        responses.POST,
        "https://omniroute.test/v1/chat/completions",
        json={"choices": [{"message": {"content": "LGTM"}}]},
        status=200,
    )
    responses.add(
        responses.POST,
        "https://api.github.com/repos/owner/repo/issues/42/comments",
        json={"html_url": "https://github.com/owner/repo/issues/42#issuecomment-1"},
        status=201,
    )

    process_pr(
        repo,
        pr_number,
        "My PR",
        config=config,
        github_client=github_client,
        ai_client=ai_client,
    )

    bodies = [c.request.body for c in responses.calls]
    assert any(b'"body": "LGTM"' in b for b in bodies if isinstance(b, bytes))


@responses.activate
def test_process_pr_skips_empty_diff(config, github_client, ai_client) -> None:
    responses.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/pulls/1",
        body="   ",
        status=200,
    )
    process_pr(
        "owner/repo",
        1,
        "Empty PR",
        config=config,
        github_client=github_client,
        ai_client=ai_client,
    )
    # Only the diff GET should fire; no POST to AI or comment endpoint.
    assert len(responses.calls) == 1


@responses.activate
def test_process_pr_posts_safe_error_on_ai_failure(config, github_client, ai_client) -> None:
    responses.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/pulls/2",
        body="diff text",
        status=200,
    )
    responses.add(
        responses.POST,
        "https://omniroute.test/v1/chat/completions",
        json={"error": "boom"},
        status=500,
    )
    responses.add(
        responses.POST,
        "https://api.github.com/repos/owner/repo/issues/2/comments",
        json={"html_url": "https://github.com/owner/repo/issues/2#issuecomment-1"},
        status=201,
    )
    process_pr(
        "owner/repo",
        2,
        "Failing PR",
        config=config,
        github_client=github_client,
        ai_client=ai_client,
    )
    # The error comment body should be sanitized.
    for call in responses.calls:
        if call.request.method == "POST" and b"comments" in call.request.url.encode():
            assert b"AI Review Bot failed" in call.request.body
