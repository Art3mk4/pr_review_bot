from __future__ import annotations

import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from flask import Flask, abort, jsonify, request

from pr_review_bot.clients.ai import OmniRouteClient
from pr_review_bot.clients.github import GitHubClient
from pr_review_bot.config import Config, load_config
from pr_review_bot.services.review import submit_review
from pr_review_bot.webhook.handlers import handle_issue_comment, handle_pull_request
from pr_review_bot.webhook.security import verify_signature

log = logging.getLogger(__name__)


def create_app(
    config: Config | None = None,
    *,
    github_client: GitHubClient | None = None,
    ai_client: OmniRouteClient | None = None,
    executor: ThreadPoolExecutor | None = None,
    load_config_func=load_config,
) -> Flask:
    """Create and configure the Flask application."""
    if config is None:
        config = load_config_func()

    if github_client is None:
        github_client = GitHubClient(token=config.github_token)
    if ai_client is None:
        ai_client = OmniRouteClient.from_config(config)
    if executor is None:
        executor = ThreadPoolExecutor(
            max_workers=config.thread_pool_workers,
            thread_name_prefix="review-worker-",
        )
        atexit.register(executor.shutdown, wait=True)

    def _submit_review(repo: str, pr_number: int, title: str) -> None:
        submit_review(
            repo,
            pr_number,
            title,
            config=config,
            github_client=github_client,
            ai_client=ai_client,
            executor=executor,
        )

    app = Flask(__name__)

    @app.route("/webhook", methods=["POST"])
    def webhook() -> tuple[Any, int]:
        sig = request.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(request.data, sig, secret=config.webhook_secret):
            log.warning("Invalid webhook signature from %s", request.remote_addr)
            abort(403)

        event = request.headers.get("X-GitHub-Event", "")
        data = request.get_json(silent=True) or {}
        log.info("Received GitHub event: %s", event)

        if event == "pull_request":
            return handle_pull_request(
                data,
                config=config,
                github_client=github_client,
                submit_review=_submit_review,
            )

        if event == "issue_comment":
            return handle_issue_comment(
                data,
                config=config,
                github_client=github_client,
                submit_review=_submit_review,
            )

        return jsonify({"status": "ignored", "event": event}), 200

    @app.route("/health", methods=["GET"])
    def health() -> tuple[Any, int]:
        return (
            jsonify(
                {
                    "status": "ok",
                    "ai": "omniroute",
                    "model": config.omniroute_model,
                }
            ),
            200,
        )

    @app.errorhandler(500)
    def internal_error(error: Exception) -> tuple[Any, int]:
        log.exception("Unhandled server error: %s", error)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    return app
