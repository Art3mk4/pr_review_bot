from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"}


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Config:
    github_token: str
    webhook_secret: str
    omniroute_api_key: str
    omniroute_base_url: str
    omniroute_model: str = "kr/qwen3-coder-next"
    port: int = 8080
    max_diff_chars: int = 14_000
    trigger_command: str = "/review"
    thread_pool_workers: int = 4
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        object.__setattr__(
            self,
            "omniroute_base_url",
            self.omniroute_base_url.rstrip("/"),
        )
        parsed = urlparse(self.omniroute_base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ConfigurationError(
                f"OMNIROUTE_BASE_URL must be a valid HTTP(S) URL, got: {self.omniroute_base_url}"
            )
        if not 1 <= self.port <= 65535:
            raise ConfigurationError(f"PORT must be between 1 and 65535, got: {self.port}")
        if self.max_diff_chars <= 0:
            raise ConfigurationError(
                f"MAX_DIFF_CHARS must be positive, got: {self.max_diff_chars}"
            )
        if self.thread_pool_workers <= 0:
            raise ConfigurationError(
                f"THREAD_POOL_WORKERS must be positive, got: {self.thread_pool_workers}"
            )
        # logging.basicConfig() rejects lowercase names (ValueError on import
        # of server.py), so accept them but store the canonical uppercase form.
        normalized_level = self.log_level.upper()
        if normalized_level not in _LOG_LEVELS:
            raise ConfigurationError(
                f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}, got: {self.log_level!r}"
            )
        object.__setattr__(self, "log_level", normalized_level)


def load_config(env: dict[str, str] | None = None) -> Config:
    """Load and validate configuration from environment variables."""
    env = env if env is not None else os.environ

    def _get_required(key: str) -> str:
        value = env.get(key)
        if not value:
            raise ConfigurationError(f"Missing required environment variable: {key}")
        return value

    port_raw = env.get("PORT", "8080")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigurationError(f"PORT must be an integer, got: {port_raw!r}") from exc

    max_diff_chars_raw = env.get("MAX_DIFF_CHARS", "14000")
    try:
        max_diff_chars = int(max_diff_chars_raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"MAX_DIFF_CHARS must be an integer, got: {max_diff_chars_raw!r}"
        ) from exc

    workers_raw = env.get("THREAD_POOL_WORKERS", "4")
    try:
        thread_pool_workers = int(workers_raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"THREAD_POOL_WORKERS must be an integer, got: {workers_raw!r}"
        ) from exc

    return Config(
        github_token=_get_required("GITHUB_TOKEN"),
        webhook_secret=_get_required("WEBHOOK_SECRET"),
        omniroute_api_key=_get_required("OMNIROUTE_API_KEY"),
        omniroute_base_url=_get_required("OMNIROUTE_BASE_URL"),
        omniroute_model=env.get("OMNIROUTE_MODEL", "kr/qwen3-coder-next"),
        port=port,
        max_diff_chars=max_diff_chars,
        trigger_command=env.get("TRIGGER_COMMAND", "/review"),
        thread_pool_workers=thread_pool_workers,
        log_level=env.get("LOG_LEVEL", "INFO"),
    )


def validate_repo(repo: str) -> str:
    """Validate a GitHub repository full name (owner/repo)."""
    if not REPO_RE.match(repo):
        raise ValueError(f"Invalid repository full name: {repo!r}")
    return repo


def validate_pr_number(pr_number: int | str) -> int:
    """Validate and coerce a pull request number."""
    try:
        number = int(pr_number)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PR number must be an integer, got: {pr_number!r}") from exc
    if number <= 0:
        raise ValueError(f"PR number must be positive, got: {number}")
    return number
