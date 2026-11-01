# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`pr_review_bot` is a GitHub webhook server that automatically reviews pull requests using an LLM through the OmniRoute OpenAI-compatible API. It responds to PR lifecycle events (`opened`, `synchronize`, `reopened`) and to the `/review` command posted as an issue comment on a PR.

## Development commands

Local development requires Python 3.12+.

```bash
# Set up environment
cp env.example .env
# Edit .env and fill GITHUB_TOKEN, WEBHOOK_SECRET, OMNIROUTE_BASE_URL, and OMNIROUTE_API_KEY.

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
pytest -q

# Run a single test file or test
pytest tests/test_review_service.py -q
pytest tests/test_review_service.py::test_process_pr_posts_comment -q

# Run the development server
python server.py
```

`pytest` needs neither `.env` nor network access: HTTP is mocked with `responses` and `Config` is built directly in `tests/conftest.py` fixtures (58 tests, sub-second).

Run via Docker:

```bash
docker compose up --build -d
```

Run tests via Docker:

```bash
docker build --target test -t pr_review_bot:test .
docker run --rm pr_review_bot:test
```

Stop containers:

```bash
docker compose down
```

## Configuration

Configuration is read from environment variables, normally placed in `.env` — `server.py` calls `load_dotenv()` before `load_config()`, so `python server.py` picks the file up on its own; in Docker the variables come from `env_file` and the file itself is not needed:

- `GITHUB_TOKEN` — GitHub Personal Access Token with repo read and pull request comment access.
- `WEBHOOK_SECRET` — shared secret used to verify GitHub webhook HMAC signatures.
- `OMNIROUTE_BASE_URL` — base URL of the OmniRoute API endpoint; defaults to `https://omniroute.art3mk4.site/v1`.
- `OMNIROUTE_API_KEY` — API key for OmniRoute.
- `OMNIROUTE_MODEL` — model identifier; defaults to `kr/qwen3-coder-next`.
- `PORT` — port used by `python server.py`; defaults to `8080`. The Gunicorn CMD in the Dockerfile binds `0.0.0.0:8080` regardless of `PORT`.
- `MAX_DIFF_CHARS` — diff truncation threshold; defaults to `14000`.
- `THREAD_POOL_WORKERS` — number of background review workers; defaults to `4`.
- `TRIGGER_COMMAND` — comment word that triggers a manual review; defaults to `/review`.
- `LOG_LEVEL` — Python logging level applied via `logging.basicConfig()` in `server.py`; defaults to `INFO`.

The `env.example` file (larger file) documents how to obtain each credential; `.env.example` is a shorter version. Use `env.example` as the starting point.

`load_config()` raises `ConfigurationError` (a `ValueError` subclass) when a required variable is missing or `PORT`/`MAX_DIFF_CHARS`/`THREAD_POOL_WORKERS` is not an integer. `Config.__post_init__` enforces the remaining invariants on every construction path — port 1–65535, positive `max_diff_chars`/`thread_pool_workers`, `log_level` one of DEBUG/INFO/WARNING/ERROR/CRITICAL/FATAL — and normalizes `log_level` to uppercase, because `logging.basicConfig()` raises on lowercase names at `server.py` import time. `OMNIROUTE_BASE_URL` has trailing slashes stripped and must parse as an http(s) URL. In tests, pass an explicit dict (`load_config({...})`) instead of mutating `os.environ`.

## Architecture

The code is organized as a Python package `pr_review_bot/`, with `server.py` remaining a thin WSGI entry point for Gunicorn.

- **`pr_review_bot/config.py`** — frozen `Config` dataclass and `load_config()`. Validates required variables and normalizes `OMNIROUTE_BASE_URL`. Configuration is no longer read at import time. Also home of `validate_repo`/`validate_pr_number`, which `GitHubClient` re-checks on every API call.
- **`pr_review_bot/clients/github.py`** — `GitHubClient` wraps `requests.Session` and provides `get_pr_diff` (v3 diff format, truncated at `max_diff_chars`), `post_comment`, `add_reaction`. `add_reaction` is best-effort: non-OK statuses and network errors alike are only logged (its timeout is capped at 10 s), so the eyes reaction on `/review` can never fail the webhook.
- **`pr_review_bot/clients/ai.py`** — `OmniRouteClient` calls OmniRoute's OpenAI-compatible `/chat/completions` with `stream: False`, `temperature: 0.3`, `max_tokens: 2048`, a 120 s timeout. `_extract_content` raises `AIAPIError` (never `KeyError`/`IndexError`) on empty `choices` or missing/non-string content. `SYSTEM_PROMPT` lives here and pins the fixed Russian markdown review structure GitHub comments show.
- **`pr_review_bot/services/review.py`** — `process_pr()` orchestrates diff → AI → comment; an empty diff is skipped without posting. On failure it posts the generic `PUBLIC_ERROR_MESSAGE` while logging details privately. `submit_review()` runs `process_pr` inline when `executor is None` (the test path), otherwise fire-and-forget through the executor.
- **`pr_review_bot/webhook/security.py`** — pure `verify_signature(payload, sig_header, secret)`.
- **`pr_review_bot/webhook/handlers.py`** — `handle_pull_request` and `handle_issue_comment` route events, filter actions/commands, and trigger reviews. They are pure functions receiving a `submit_review` callable from the factory rather than importing the service. Malformed payloads return 400, never 500 (GitHub redelivers 5xx in a loop); `/review` must be the whole first word of the comment, and comments authored by bots (`user.type == "Bot"`) are ignored.
- **`pr_review_bot/app.py`** — Flask app factory `create_app(config, *, github_client, ai_client, executor, load_config_func)`; registers `/webhook` and `/health`, wires clients, and uses a bounded `ThreadPoolExecutor` instead of raw threads. Every collaborator is an optional argument — tests inject `MagicMock`s and `executor=None` (see `tests/test_routes.py`). The factory-created executor is shut down via `atexit`.
- **`server.py`** — thin entry point: `load_dotenv()`, then `app = create_app(load_config())`.

### Endpoints

- `POST /webhook` — receives GitHub webhooks. Verifies HMAC signature, then dispatches based on `X-GitHub-Event`.
- `GET /health` — returns status, provider (`omniroute`), and configured model.

### Review flow

1. Webhook handler validates signature and event.
2. For `pull_request` with `opened`/`synchronize`/`reopened`, or `issue_comment` whose first word is `/review` on a PR (bot comments are ignored; the comment also gets a best-effort 👀 reaction), it submits a review task.
3. A worker fetches the diff from GitHub (truncated if necessary; an empty diff ends the run without posting anything).
4. The diff + PR title are sent to OmniRoute chat completions.
5. The generated review is posted as a PR comment.

### Concurrency

Reviews run in a bounded `ThreadPoolExecutor` so the webhook returns `202 Accepted` immediately. `thread_pool_workers` limits parallelism. A `ReviewGate` (`pr_review_bot/services/review.py`) additionally tracks in-flight `(repo, pr_number)` pairs per process and skips a new review if one for the same PR is already running, so rapid duplicate events (fast pushes, webhook redelivery) don't trigger duplicate AI calls/comments; skipped events are dropped, not queued. The future is deliberately not awaited; the gate releases in a `finally` inside the worker, or directly in `submit_review` if an already-shut-down executor rejects the submission. This dedup is per-process only — it does not coordinate across Gunicorn workers.

### Production run

`Dockerfile` is multi-stage. The `production` target uses Gunicorn with two workers, binding `0.0.0.0:8080` with a 120-second request timeout and `--graceful-timeout 130` — `atexit` waits for in-flight reviews to finish, and the 30 s default would SIGKILL the worker mid-review. `docker-compose.yml` mounts `./logs` to `/var/log` and defines a healthcheck against `/health`.

## Important files

- `server.py` — WSGI entry point.
- `pr_review_bot/` — application source package.
- `tests/` — pytest test suite using `responses` and stdlib mocks.
- `requirements.txt` — production dependencies (Flask, Gunicorn, Requests, python-dotenv).
- `requirements-dev.txt` — development dependencies (pytest, pytest-cov, responses).
- `Dockerfile` / `docker-compose.yml` — container build and deployment.
- `env.example` / `.env.example` — environment variable templates.
