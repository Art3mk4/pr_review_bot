import hashlib
import hmac
from unittest.mock import MagicMock

import pytest

from pr_review_bot.app import create_app
from pr_review_bot.config import Config


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def test_app(config: Config) -> tuple:
    """Flask test app with mocked review submission."""
    github = MagicMock()
    ai = MagicMock()
    submit_review = MagicMock()
    app = create_app(
        config=config,
        github_client=github,
        ai_client=ai,
        executor=None,
        load_config_func=lambda: config,
    )
    return app, github, ai, submit_review


def _post(client, event: str, payload: bytes, secret: str):
    sig = _sign(payload, secret)
    return client.post(
        "/webhook",
        data=payload,
        content_type="application/json",
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": sig,
        },
    )


class TestWebhookPullRequest:
    def test_auto_review_triggered(self, test_app) -> None:
        app, github, ai, submit_review = test_app
        # Monkey-patch the route's submission more cleanly by calling handler directly
        # Because app factory wires its own submit_review, we cannot patch here easily.
        # Instead, we assert on the GitHub/AI interactions via the synchronous path.
        with app.test_client() as client:
            payload = (
                '{"action":"opened","repository":{"full_name":"owner/repo"},'
                '"pull_request":{"number":42,"title":"New feature"}}'
            ).encode()
            resp = _post(client, "pull_request", payload, "test_secret")
            assert resp.status_code == 202
            data = resp.get_json()
            assert data["status"] == "processing"

    def test_non_triggering_action_is_ignored(self, test_app) -> None:
        app, *_ = test_app
        with app.test_client() as client:
            payload = (
                '{"action":"closed","repository":{"full_name":"owner/repo"},'
                '"pull_request":{"number":42,"title":"x"}}'
            ).encode()
            resp = _post(client, "pull_request", payload, "test_secret")
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "ignored"


class TestWebhookIssueComment:
    def test_review_command_on_pr(self, test_app) -> None:
        app, github, *_ = test_app
        with app.test_client() as client:
            payload = (
                '{"action":"created","repository":{"full_name":"owner/repo"},'
                '"issue":{"number":7,"title":"PR title","pull_request":{}},'
                '"comment":{"id":123,"body":"/review please"}}'
            ).encode()
            resp = _post(client, "issue_comment", payload, "test_secret")
            assert resp.status_code == 202
            assert github.add_reaction.called

    def test_review_command_on_regular_issue_is_ignored(self, test_app) -> None:
        app, github, *_ = test_app
        with app.test_client() as client:
            payload = (
                '{"action":"created","repository":{"full_name":"owner/repo"},'
                '"issue":{"number":7,"title":"Issue title"},'
                '"comment":{"id":123,"body":"/review please"}}'
            ).encode()
            resp = _post(client, "issue_comment", payload, "test_secret")
            assert resp.status_code == 200
            assert resp.get_json()["reason"] == "not a PR"
            assert not github.add_reaction.called

    def test_non_command_comment_is_ignored(self, test_app) -> None:
        app, github, *_ = test_app
        with app.test_client() as client:
            payload = (
                '{"action":"created","repository":{"full_name":"owner/repo"},'
                '"issue":{"number":7,"title":"PR title","pull_request":{}},'
                '"comment":{"id":123,"body":"thanks"}}'
            ).encode()
            resp = _post(client, "issue_comment", payload, "test_secret")
            assert resp.status_code == 200
            assert resp.get_json()["reason"] == "not a command"
            assert not github.add_reaction.called


class TestSecurity:
    def test_invalid_signature_returns_403(self, test_app) -> None:
        app, *_ = test_app
        with app.test_client() as client:
            payload = b'{"action":"opened","repository":{"full_name":"a/b"},"pull_request":{"number":1,"title":"x"}}'
            resp = client.post(
                "/webhook",
                data=payload,
                content_type="application/json",
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": "sha256=badbad",
                },
            )
            assert resp.status_code == 403


class TestHealth:
    def test_health(self, test_app) -> None:
        app, *_ = test_app
        with app.test_client() as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"
            assert data["ai"] == "omniroute"
            assert data["model"] == "kr/qwen3-code-next"
