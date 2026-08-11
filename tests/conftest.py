from __future__ import annotations

import pytest

from pr_review_bot.clients.ai import OmniRouteClient
from pr_review_bot.clients.github import GitHubClient
from pr_review_bot.config import Config


@pytest.fixture
def config() -> Config:
    return Config(
        github_token="ghp_test_token",
        webhook_secret="test_secret",
        omniroute_api_key="sk_test_key",
        omniroute_base_url="https://omniroute.test/v1",
        omniroute_model="kr/qwen3-coder-next",
        port=8080,
        max_diff_chars=14_000,
        trigger_command="/review",
        thread_pool_workers=2,
    )


@pytest.fixture
def github_client(config: Config) -> GitHubClient:
    return GitHubClient(token=config.github_token)


@pytest.fixture
def ai_client(config: Config) -> OmniRouteClient:
    return OmniRouteClient(
        base_url=config.omniroute_base_url,
        api_key=config.omniroute_api_key,
        model=config.omniroute_model,
        timeout=5.0,
    )
