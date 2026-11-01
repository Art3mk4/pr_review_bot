import os

import pytest

from pr_review_bot.config import Config, ConfigurationError, load_config, validate_pr_number, validate_repo


def test_load_config_from_explicit_dict() -> None:
    cfg = load_config(
        {
            "GITHUB_TOKEN": "ghp_x",
            "WEBHOOK_SECRET": "secret",
            "OMNIROUTE_API_KEY": "sk_y",
            "OMNIROUTE_BASE_URL": "https://omniroute.test/v1",
        }
    )
    assert cfg.github_token == "ghp_x"
    assert cfg.webhook_secret == "secret"
    assert cfg.omniroute_api_key == "sk_y"
    assert cfg.omniroute_base_url == "https://omniroute.test/v1"
    assert cfg.omniroute_model == "kr/qwen3-coder-next"
    assert cfg.port == 8080
    assert cfg.max_diff_chars == 14_000
    assert cfg.log_level == "INFO"


def test_load_config_validates_missing_base_url() -> None:
    with pytest.raises(
        ConfigurationError, match="Missing required environment variable: OMNIROUTE_BASE_URL"
    ):
        load_config(
            {"GITHUB_TOKEN": "ghp_x", "WEBHOOK_SECRET": "secret", "OMNIROUTE_API_KEY": "sk_y"}
        )


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


def _cfg(**overrides) -> Config:
    """Config with the required fields filled in; override single fields per test."""
    base = dict(
        github_token="a",
        webhook_secret="b",
        omniroute_api_key="c",
        omniroute_base_url="https://omniroute.test/v1",
    )
    base.update(overrides)
    return Config(**base)


def test_config_defaults() -> None:
    cfg = _cfg()
    assert cfg.omniroute_model == "kr/qwen3-coder-next"


_REQUIRED = {
    "GITHUB_TOKEN": "ghp_x",
    "WEBHOOK_SECRET": "secret",
    "OMNIROUTE_API_KEY": "sk_y",
    "OMNIROUTE_BASE_URL": "https://omniroute.test/v1",
}


@pytest.mark.parametrize("port", [0, 70000])
def test_config_rejects_out_of_range_port(port: int) -> None:
    with pytest.raises(ConfigurationError, match="PORT must be between 1 and 65535"):
        _cfg(port=port)


def test_config_rejects_non_positive_max_diff_chars() -> None:
    with pytest.raises(ConfigurationError, match="MAX_DIFF_CHARS must be positive"):
        _cfg(max_diff_chars=0)


def test_config_rejects_non_positive_thread_pool_workers() -> None:
    with pytest.raises(ConfigurationError, match="THREAD_POOL_WORKERS must be positive"):
        _cfg(thread_pool_workers=0)


def test_config_rejects_unknown_log_level() -> None:
    with pytest.raises(ConfigurationError, match="LOG_LEVEL must be one of"):
        _cfg(log_level="BOGUS")


def test_config_normalizes_lowercase_log_level() -> None:
    # basicConfig() would raise ValueError on "debug" at server.py import time.
    cfg = _cfg(log_level="debug")
    assert cfg.log_level == "DEBUG"


def test_load_config_rejects_non_integer_thread_pool_workers() -> None:
    with pytest.raises(ConfigurationError, match="THREAD_POOL_WORKERS must be an integer"):
        load_config({**_REQUIRED, "THREAD_POOL_WORKERS": "abc"})
