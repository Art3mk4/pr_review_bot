from __future__ import annotations

import logging
from typing import Any, Callable

from pr_review_bot.clients.github import GitHubClient
from pr_review_bot.config import Config, validate_pr_number

log = logging.getLogger(__name__)

PR_REVIEW_ACTIONS = {"opened", "synchronize", "reopened"}

HandlerResult = tuple[dict[str, Any], int]
SubmitReview = Callable[[str, int, str], None]


def handle_pull_request(
    data: dict[str, Any],
    *,
    config: Config,
    github_client: GitHubClient,
    submit_review: SubmitReview,
) -> HandlerResult:
    """Handle a GitHub pull_request webhook event."""
    if not isinstance(data, dict):
        return {"status": "bad payload"}, 400

    action = data.get("action", "")
    if action not in PR_REVIEW_ACTIONS:
        return {"status": "ignored", "action": action}, 200

    try:
        repo = data["repository"]["full_name"]
        pr_number = validate_pr_number(data["pull_request"]["number"])
        title = data["pull_request"]["title"]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        log.warning("Malformed pull_request payload: %s", exc)
        return {"status": "bad payload"}, 400

    log.info("Auto-review: %s PR #%d action=%s", repo, pr_number, action)
    submit_review(repo, pr_number, title)
    return {"status": "processing", "pr": pr_number}, 202


def handle_issue_comment(
    data: dict[str, Any],
    *,
    config: Config,
    github_client: GitHubClient,
    submit_review: SubmitReview,
) -> HandlerResult:
    """Handle a GitHub issue_comment webhook event for the /review command."""
    if not isinstance(data, dict):
        return {"status": "bad payload"}, 400

    action = data.get("action", "")
    if action != "created":
        return {"status": "ignored", "reason": "not created"}, 200

    try:
        comment = data.get("comment") or {}
        issue = data.get("issue") or {}
        raw_body = comment.get("body")
        body = raw_body.strip() if isinstance(raw_body, str) else ""

        if not body.startswith(config.trigger_command):
            return {"status": "ignored", "reason": "not a command"}, 200

        if "pull_request" not in issue:
            return {"status": "ignored", "reason": "not a PR"}, 200

        repo = data["repository"]["full_name"]
        pr_number = validate_pr_number(issue["number"])
        title = issue["title"]
        comment_id = comment["id"]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        log.warning("Malformed issue_comment payload: %s", exc)
        return {"status": "bad payload"}, 400

    log.info("Manual review requested: %s PR #%d", repo, pr_number)
    github_client.add_reaction(repo, comment_id, "eyes")
    submit_review(repo, pr_number, title)
    return {"status": "processing", "pr": pr_number}, 202
