import re

import pytest
import responses

from pr_review_bot.clients.github import GitHubAPIError, GitHubClient


@pytest.fixture
def github_client(config) -> GitHubClient:
    return GitHubClient(token=config.github_token)


@responses.activate
def test_get_pr_diff(github_client: GitHubClient) -> None:
    diff_body = "diff --git a/file.txt b/file.txt\n+hello"
    responses.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/pulls/42",
        body=diff_body,
        status=200,
        content_type="text/plain",
    )
    result = github_client.get_pr_diff("owner/repo", 42)
    assert result == diff_body
    assert responses.calls[0].request.headers["Accept"] == "application/vnd.github.v3.diff"


@responses.activate
def test_get_pr_diff_truncates(github_client: GitHubClient) -> None:
    responses.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/pulls/1",
        body="x" * 100,
        status=200,
    )
    result = github_client.get_pr_diff("owner/repo", 1, max_diff_chars=50)
    assert result.startswith("x" * 50)
    assert "...(diff truncated)" in result


@responses.activate
def test_get_pr_diff_raises_on_404(github_client: GitHubClient) -> None:
    responses.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/pulls/99",
        json={"message": "Not Found"},
        status=404,
    )
    with pytest.raises(GitHubAPIError, match="Failed to fetch PR diff"):
        github_client.get_pr_diff("owner/repo", 99)


@responses.activate
def test_post_comment(github_client: GitHubClient) -> None:
    responses.add(
        responses.POST,
        "https://api.github.com/repos/owner/repo/issues/7/comments",
        json={"html_url": "https://github.com/owner/repo/issues/7#issuecomment-1"},
        status=201,
    )
    url = github_client.post_comment("owner/repo", 7, "LGTM")
    assert url == "https://github.com/owner/repo/issues/7#issuecomment-1"
    body = responses.calls[0].request.body
    assert b'"body": "LGTM"' in body


@responses.activate
def test_add_reaction(github_client: GitHubClient) -> None:
    responses.add(
        responses.POST,
        "https://api.github.com/repos/owner/repo/issues/comments/123/reactions",
        json={"id": 1},
        status=201,
    )
    github_client.add_reaction("owner/repo", 123)
    req = responses.calls[0].request
    assert req.headers["Accept"] == "application/vnd.github.squirrel-girl-preview+json"
    assert b'"content": "eyes"' in req.body


def test_get_pr_diff_rejects_invalid_repo(github_client: GitHubClient) -> None:
    with pytest.raises(ValueError, match="Invalid repository full name"):
        github_client.get_pr_diff("bad", 1)


def test_get_pr_diff_rejects_invalid_number(github_client: GitHubClient) -> None:
    with pytest.raises(ValueError, match="PR number must be an integer"):
        github_client.get_pr_diff("owner/repo", "not-a-number")
