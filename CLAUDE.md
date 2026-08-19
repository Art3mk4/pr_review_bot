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

Configuration is read from environment variables, normally placed in `.env`:

- `GITHUB_TOKEN` — GitHub Personal Access Token with repo read and pull request comment access.
- `WEBHOOK_SECRET` — shared secret used to verify GitHub webhook HMAC signatures.
- `OMNIROUTE_BASE_URL` — base URL of the OmniRoute API endpoint; defaults to `https://omniroute.art3mk4.site/v1`.
- `OMNIROUTE_API_KEY` — API key for OmniRoute.
- `OMNIROUTE_MODEL` — model identifier; defaults to `kr/qwen3-coder-next`.
- `PORT` — server port; defaults to `8080`.
- `MAX_DIFF_CHARS` — diff truncation threshold; defaults to `14000`.
- `THREAD_POOL_WORKERS` — number of background review workers; defaults to `4`.
- `TRIGGER_COMMAND` — comment prefix that triggers a manual review; defaults to `/review`.
- `LOG_LEVEL` — Python logging level applied via `logging.basicConfig()` in `server.py`; defaults to `INFO`.

The `env.example` file (larger file) documents how to obtain each credential; `.env.example` is a shorter version. Use `env.example` as the starting point.

## Architecture

The code is organized as a Python package `pr_review_bot/`, with `server.py` remaining a thin WSGI entry point for Gunicorn.

- **`pr_review_bot/config.py`** — `Config` dataclass and `load_config()`. Validates required variables and normalizes `OMNIROUTE_BASE_URL`. Configuration is no longer read at import time.
- **`pr_review_bot/clients/github.py`** — `GitHubClient` wraps `requests.Session`, validates `repo`/`pr_number`, and provides `get_pr_diff`, `post_comment`, `add_reaction`.
- **`pr_review_bot/clients/ai.py`** — `OmniRouteClient` calls OmniRoute's OpenAI-compatible `/chat/completions`, builds prompts, and defensively parses responses. `SYSTEM_PROMPT` lives here.
- **`pr_review_bot/services/review.py`** — `process_pr()` orchestrates diff → AI → comment and posts a generic public error message while logging details privately.
- **`pr_review_bot/webhook/security.py`** — pure `verify_signature(payload, sig_header, secret)`.
- **`pr_review_bot/webhook/handlers.py`** — `handle_pull_request` and `handle_issue_comment` route events, filter actions/commands, and trigger reviews.
- **`pr_review_bot/app.py`** — Flask app factory `create_app()`; registers `/webhook` and `/health`, wires clients, and uses a bounded `ThreadPoolExecutor` instead of raw threads.
- **`server.py`** — thin entry point: `app = create_app(load_config())`.

### Endpoints

- `POST /webhook` — receives GitHub webhooks. Verifies HMAC signature, then dispatches based on `X-GitHub-Event`.
- `GET /health` — returns status, provider (`omniroute`), and configured model.

### Review flow

1. Webhook handler validates signature and event.
2. For `pull_request` with `opened`/`synchronize`/`reopened`, or `issue_comment` starting with `/review` on a PR, it submits a review task.
3. A worker fetches the diff from GitHub (truncated if necessary).
4. The diff + PR title are sent to OmniRoute chat completions.
5. The generated review is posted as a PR comment.

### Concurrency

Reviews run in a bounded `ThreadPoolExecutor` so the webhook returns `202 Accepted` immediately. `thread_pool_workers` limits parallelism. A `ReviewGate` (`pr_review_bot/services/review.py`) additionally tracks in-flight `(repo, pr_number)` pairs per process and skips a new review if one for the same PR is already running, so rapid duplicate events (fast pushes, webhook redelivery) don't trigger duplicate AI calls/comments. This dedup is per-process only — it does not coordinate across Gunicorn workers.

### Production run

`Dockerfile` is multi-stage. The `production` target uses Gunicorn with two workers, binding `0.0.0.0:8080` with a 120-second timeout. `docker-compose.yml` mounts `./logs` to `/var/log` and defines a healthcheck against `/health`.

## Important files

- `server.py` — WSGI entry point.
- `pr_review_bot/` — application source package.
- `tests/` — pytest test suite using `responses` and stdlib mocks.
- `requirements.txt` — production dependencies (Flask, Gunicorn, Requests, python-dotenv).
- `requirements-dev.txt` — development dependencies (pytest, pytest-cov, responses).
- `Dockerfile` / `docker-compose.yml` — container build and deployment.
- `env.example` / `.env.example` — environment variable templates.
