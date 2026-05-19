"""
PR Review Bot — Webhook Server
Слушает события GitHub, делает AI review PR'ов.
"""

import hashlib
import hmac
import logging
import os
import threading

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request

load_dotenv()

# ─── Конфигурация ─────────────────────────────────────────────────────────────

GITHUB_TOKEN   = os.environ["GITHUB_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")
PORT           = int(os.environ.get("PORT", 8080))
MAX_DIFF_CHARS = 14_000

# ─── Логирование (stdout — подхватывается Docker) ─────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pr-review-bot")

app = Flask(__name__)

# ─── Безопасность: проверка подписи GitHub ────────────────────────────────────

def verify_signature(payload: bytes, sig_header: str) -> bool:
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", sig_header)

# ─── GitHub API ───────────────────────────────────────────────────────────────

GH = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def get_pr_diff(repo: str, pr_number: int) -> str:
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    resp = requests.get(url, headers={**GH, "Accept": "application/vnd.github.v3.diff"}, timeout=20)
    resp.raise_for_status()
    diff = resp.text
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n...(diff truncated)"
    return diff


def post_comment(repo: str, pr_number: int, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.post(url, headers=GH, json={"body": body}, timeout=20)
    resp.raise_for_status()
    log.info("Comment posted: %s", resp.json()["html_url"])

# ─── Промпт ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты опытный code reviewer. Дай конструктивный обзор Pull Request'а.

Структура ответа (строго markdown):

## 🤖 AI Code Review

### Краткое резюме
<2-3 предложения о том, что делает этот PR>

### ✅ Что хорошо
<список сильных сторон>

### ⚠️ Замечания и предложения
<конкретные замечания с указанием файлов/строк если возможно>

### 🐛 Потенциальные баги / риски
<баги, edge cases, проблемы безопасности — или "Не обнаружено">

### 💡 Итог
<Approve / Request Changes / Neutral + обоснование>

---
*Автоматический AI-обзор. Не является заменой ревью живого разработчика.*"""


def build_prompt(title: str, diff: str) -> str:
    return f"PR Title: {title}\n\nDiff:\n```diff\n{diff}\n```\n\nСделай code review."

# ─── AI Backends ──────────────────────────────────────────────────────────────

def ai_review(title: str, diff: str) -> str:
    if GEMINI_API_KEY:
        log.info("Using Gemini Flash...")
        return _gemini(title, diff)
    if GROQ_API_KEY:
        log.info("Using Groq (Llama 3.3 70B)...")
        return _groq(title, diff)
    raise RuntimeError("No AI API key configured (GEMINI_API_KEY or GROQ_API_KEY)")


def _gemini(title: str, diff: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": build_prompt(title, diff)}]}],
        "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3},
    }
    r = requests.post(url, json=body, timeout=60)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _groq(title: str, diff: str) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": build_prompt(title, diff)},
            ],
            "max_tokens": 2048,
            "temperature": 0.3,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ─── Логика ревью ─────────────────────────────────────────────────────────────

def process_pr(repo: str, pr_number: int, title: str) -> None:
    log.info("Processing PR #%d in %s: %s", pr_number, repo, title)
    try:
        diff = get_pr_diff(repo, pr_number)
        if not diff.strip():
            log.info("Empty diff, skipping.")
            return
        log.info("Diff size: %d chars", len(diff))
        review = ai_review(title, diff)
        post_comment(repo, pr_number, review)
        log.info("Done PR #%d", pr_number)
    except Exception as e:
        log.error("Error processing PR #%d: %s", pr_number, e, exc_info=True)
        try:
            post_comment(repo, pr_number, f"⚠️ AI Review Bot encountered an error: `{e}`")
        except Exception:
            pass

# ─── Webhook endpoint ─────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.data, sig):
        log.warning("Invalid webhook signature from %s", request.remote_addr)
        abort(403)

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return jsonify({"status": "ignored", "event": event}), 200

    data   = request.json
    action = data.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return jsonify({"status": "ignored", "action": action}), 200

    repo      = data["repository"]["full_name"]
    pr_number = data["pull_request"]["number"]
    title     = data["pull_request"]["title"]

    log.info("PR event: action=%s repo=%s pr=#%d", action, repo, pr_number)
    threading.Thread(target=process_pr, args=(repo, pr_number, title), daemon=True).start()

    return jsonify({"status": "processing", "pr": pr_number}), 202


@app.route("/health", methods=["GET"])
def health():
    ai = "gemini" if GEMINI_API_KEY else ("groq" if GROQ_API_KEY else "none")
    return jsonify({"status": "ok", "ai": ai}), 200


if __name__ == "__main__":
    log.info("Starting PR Review Bot on port %d", PORT)
    app.run(host="0.0.0.0", port=PORT)
