import os

import pytest

from pr_review_bot.config import Config, ConfigurationError, load_config, validate_pr_number, validate_repo


def test_load_config_from_explicit_dict() -> None:
    cfg = load_config(
        {
            "GITHUB_TOKEN": "ghp_x",
            "WEBHOOK_SECRET": "secret",
            "OMNIROUTE_API_KEY": "sk_y",
        }
    )
    assert cfg.github_token == "ghp_x"
    assert cfg.webhook_secret == "secret"
    assert cfg.omniroute_api_key == "sk_y"
    assert cfg.omniroute_base_url == "https://omniroute.io/v1"
    assert cfg.omniroute_model == "kr/qwen3-code-next"
    assert cfg.port == 8080
    assert cfg.max_diff_chars == 14_000


def test_load_config_validates_missing_github_token() -> None:
    with pytest.raises(ConfigurationError, match="Missing required environment variable: GITHUB_TOKEN"):
        load_config({})


def test_load_config_normalizes_base_url_trailing_slash() -> None:
    cfg = load_config(
        {
            "GITHUB_TOKEN": "ghp_x",
            "WEBHOOK_SECRET": "secret",
            "OMNIROUTE_API_KEY": "sk_y",
            "OMNIROUTE_BASE_URL": "https://omniroute.test/v1/",
        }
    )
    assert cfg.omniroute_base_url == "https://omniroute.test/v1"


def test_load_config_rejects_invalid_base_url() -> None:
    with pytest.raises(ConfigurationError, match=r"must be a valid HTTP\(S\) URL"):
        load_config(
            {
                "GITHUB_TOKEN": "ghp_x",
                "WEBHOOK_SECRET": "secret",
                "OMNIROUTE_API_KEY": "sk_y",
                "OMNIROUTE_BASE_URL": "not-a-url",
            }
        )


def test_validate_repo() -> None:
    assert validate_repo("owner/repo") == "owner/repo"
    assert validate_repo("my-org/repo-2.v2") == "my-org/repo-2.v2"


def test_validate_repo_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="Invalid repository full name"):
        validate_repo("owner/../other")


def test_validate_pr_number() -> None:
    assert validate_pr_number("42") == 42
    assert validate_pr_number(7) == 7


def test_validate_pr_number_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="PR number must be positive"):
        validate_pr_number(0)


def test_validate_pr_number_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="PR number must be an integer"):
        validate_pr_number("abc")


def test_config_defaults() -> None:
    cfg = Config(
        github_token="a",
        webhook_secret="b",
        omniroute_api_key="c",
    )
    assert cfg.omniroute_model == "kr/qwen3-code-next"
