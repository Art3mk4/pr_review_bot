import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
import responses

from pr_review_bot.services.review import ReviewGate, process_pr, submit_review


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


def test_review_gate_blocks_reacquire_until_released() -> None:
    gate = ReviewGate()
    assert gate.try_acquire("owner/repo", 1) is True
    assert gate.try_acquire("owner/repo", 1) is False
    # A different PR is unaffected.
    assert gate.try_acquire("owner/repo", 2) is True

    gate.release("owner/repo", 1)
    assert gate.try_acquire("owner/repo", 1) is True


def test_submit_review_skips_duplicate_while_in_flight(monkeypatch, config, github_client, ai_client) -> None:
    calls = []
    started = threading.Event()
    proceed = threading.Event()

    def fake_process_pr(repo, pr_number, title, *, config, github_client, ai_client):
        calls.append((repo, pr_number))
        started.set()
        assert proceed.wait(timeout=2), "test deadlocked waiting for release"

    monkeypatch.setattr("pr_review_bot.services.review.process_pr", fake_process_pr)

    gate = ReviewGate()
    with ThreadPoolExecutor(max_workers=2) as executor:
        submit_review(
            "owner/repo",
            1,
            "title",
            config=config,
            github_client=github_client,
            ai_client=ai_client,
            executor=executor,
            gate=gate,
        )
        assert started.wait(timeout=2), "first review never started"

        # Fired while the first review is still in flight: must be skipped.
        submit_review(
            "owner/repo",
            1,
            "title",
            config=config,
            github_client=github_client,
            ai_client=ai_client,
            executor=executor,
            gate=gate,
        )
        proceed.set()

    assert calls == [("owner/repo", 1)]
    # The gate must release after completion so a later, separate event can run.
    assert gate.try_acquire("owner/repo", 1) is True
