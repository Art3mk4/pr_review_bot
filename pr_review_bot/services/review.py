from __future__ import annotations

import logging
import threading
from concurrent.futures import Executor

from pr_review_bot.clients.ai import AIAPIError, OmniRouteClient
from pr_review_bot.clients.github import GitHubAPIError, GitHubClient
from pr_review_bot.config import Config

log = logging.getLogger(__name__)

PUBLIC_ERROR_MESSAGE = "⚠️ AI Review Bot failed to process this PR. The error has been logged."


class ReviewGate:
    """Tracks in-flight (repo, pr_number) reviews to stop duplicate concurrent runs.

    GitHub can fire several webhook events for the same PR in quick succession
    (rapid pushes, webhook redelivery), and without this each one would start
    its own review, burning AI calls and posting duplicate comments. Only one
    review per PR runs at a time per process; events that arrive while a
    review is in flight are skipped rather than queued.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight: set[tuple[str, int]] = set()

    def try_acquire(self, repo: str, pr_number: int) -> bool:
        key = (repo, pr_number)
        with self._lock:
            if key in self._in_flight:
                return False
            self._in_flight.add(key)
            return True

    def release(self, repo: str, pr_number: int) -> None:
        with self._lock:
            self._in_flight.discard((repo, pr_number))


def process_pr(
    repo: str,
    pr_number: int,
    title: str,
    *,
    config: Config,
    github_client: GitHubClient,
    ai_client: OmniRouteClient,
) -> None:
    """Fetch the PR diff, ask the AI for a review, and post the result as a comment."""
    log.info("Processing PR #%d in %s", pr_number, repo)
    try:
        diff = github_client.get_pr_diff(repo, pr_number, max_diff_chars=config.max_diff_chars)
        if not diff.strip():
            log.info("Empty diff for PR #%d, skipping.", pr_number)
            return

        review = ai_client.review(title, diff)
        github_client.post_comment(repo, pr_number, review)
        log.info("Done PR #%d in %s", pr_number, repo)
    except (GitHubAPIError, AIAPIError) as e:
        log.error("Error processing PR #%d: %s", pr_number, e, exc_info=True)
        _post_safe_error(github_client, repo, pr_number)
    except Exception as e:  # pragma: no cover - last-resort guard
        log.exception("Unexpected error processing PR #%d in %s: %s", pr_number, repo, e)
        _post_safe_error(github_client, repo, pr_number)


def _post_safe_error(github_client: GitHubClient, repo: str, pr_number: int) -> None:
    """Post a sanitized error comment; never leak secrets or tracebacks."""
    try:
        github_client.post_comment(repo, pr_number, PUBLIC_ERROR_MESSAGE)
    except Exception as inner:
        # Broad on purpose: a requests ConnectionError escaping here would land
        # in an unwatched future and be swallowed without a single log line.
        log.error("Failed to post error comment for PR #%d: %s", pr_number, inner)


def submit_review(
    repo: str,
    pr_number: int,
    title: str,
    *,
    config: Config,
    github_client: GitHubClient,
    ai_client: OmniRouteClient,
    executor: Executor | None = None,
    gate: ReviewGate | None = None,
) -> None:
    """Submit review processing to an executor, or run synchronously for tests."""
    if executor is None:
        process_pr(
            repo,
            pr_number,
            title,
            config=config,
            github_client=github_client,
            ai_client=ai_client,
        )
        return

    if gate is not None and not gate.try_acquire(repo, pr_number):
        log.info("Skipping review for %s PR #%d: already in progress", repo, pr_number)
        return

    def _run() -> None:
        try:
            process_pr(
                repo,
                pr_number,
                title,
                config=config,
                github_client=github_client,
                ai_client=ai_client,
            )
        finally:
            if gate is not None:
                gate.release(repo, pr_number)

    # We deliberately do not capture/return the Future so callers stay fire-and-forget.
    # If the pool is already shut down (worker exiting via atexit), submit raises
    # RuntimeError and _run never executes — release the gate or this PR's future
    # /review commands would be skipped forever.
    try:
        executor.submit(_run)
    except Exception:
        if gate is not None:
            gate.release(repo, pr_number)
        log.exception("Failed to submit review for %s PR #%d", repo, pr_number)
