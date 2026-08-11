from __future__ import annotations

import logging
from concurrent.futures import Executor

from pr_review_bot.clients.ai import AIAPIError, OmniRouteClient
from pr_review_bot.clients.github import GitHubAPIError, GitHubClient
from pr_review_bot.config import Config

log = logging.getLogger(__name__)

PUBLIC_ERROR_MESSAGE = "⚠️ AI Review Bot failed to process this PR. The error has been logged."


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
    except GitHubAPIError as inner:
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

    # We deliberately do not capture/return the Future so callers stay fire-and-forget.
    executor.submit(
        process_pr,
        repo,
        pr_number,
        title,
        config=config,
        github_client=github_client,
        ai_client=ai_client,
    )
