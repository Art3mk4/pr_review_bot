from __future__ import annotations

import logging
from typing import Any

import requests

from pr_review_bot.config import validate_pr_number, validate_repo

log = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    """Raised when a GitHub API call fails."""


class GitHubClient:
    """Minimal GitHub API client for PR review workflows."""

    def __init__(self, token: str, timeout: float = 20.0) -> None:
        self._token = token
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{GITHUB_API_BASE}{path}"
        kwargs.setdefault("timeout", self._timeout)
        resp = self._session.request(method, url, **kwargs)
        log.debug("GitHub API %s %s -> %s", method, path, resp.status_code)
        return resp

    def get_pr_diff(self, repo: str, pr_number: int | str, max_diff_chars: int = 14_000) -> str:
        """Fetch the PR diff in v3 diff format, optionally truncated."""
        validate_repo(repo)
        number = validate_pr_number(pr_number)
        path = f"/repos/{repo}/pulls/{number}"
        resp = self._request(
            "GET",
            path,
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise GitHubAPIError(f"Failed to fetch PR diff: {exc}") from exc
        diff = resp.text
        if len(diff) > max_diff_chars:
            diff = diff[:max_diff_chars] + "\n\n...(diff truncated)"
            log.info("PR #%s diff truncated to %d chars", pr_number, max_diff_chars)
        return diff

    def get_pr_for_issue(self, repo: str, issue_number: int | str) -> dict | None:
        """Return PR data if the issue is a PR, otherwise None."""
        validate_repo(repo)
        number = validate_pr_number(issue_number)
        path = f"/repos/{repo}/pulls/{number}"
        resp = self._request("GET", path)
        if resp.status_code == 404:
            return None
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise GitHubAPIError(f"Failed to fetch PR data: {exc}") from exc
        return resp.json()

    def post_comment(self, repo: str, pr_number: int | str, body: str) -> str:
        """Post a comment on a PR and return its HTML URL."""
        validate_repo(repo)
        number = validate_pr_number(pr_number)
        path = f"/repos/{repo}/issues/{number}/comments"
        resp = self._request("POST", path, json={"body": body})
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise GitHubAPIError(f"Failed to post comment: {exc}") from exc
        data = resp.json()
        html_url = data.get("html_url", "")
        log.info("Comment posted: %s", html_url)
        return html_url

    def add_reaction(
        self, repo: str, comment_id: int | str, reaction: str = "eyes"
    ) -> None:
        """Add a reaction to an issue/PR comment."""
        validate_repo(repo)
        try:
            comment_id_int = int(comment_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"comment_id must be an integer, got: {comment_id!r}") from exc
        path = f"/repos/{repo}/issues/comments/{comment_id_int}/reactions"
        resp = self._request(
            "POST",
            path,
            headers={"Accept": "application/vnd.github.squirrel-girl-preview+json"},
            json={"content": reaction},
            timeout=min(self._timeout, 10.0),
        )
        if not resp.ok:
            log.warning(
                "Failed to add reaction to comment %s in %s: %s %s",
                comment_id,
                repo,
                resp.status_code,
                resp.text[:200],
            )
