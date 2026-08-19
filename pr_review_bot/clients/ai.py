from __future__ import annotations

import logging
from typing import Any

import requests

from pr_review_bot.config import Config

log = logging.getLogger(__name__)


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


class AIAPIError(Exception):
    """Raised when the AI backend returns an error or unexpected response."""


class OmniRouteClient:
    """OpenAI-compatible chat completion client for OmniRoute."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_key}"})

    @classmethod
    def from_config(cls, config: Config) -> "OmniRouteClient":
        return cls(
            base_url=config.omniroute_base_url,
            api_key=config.omniroute_api_key,
            model=config.omniroute_model,
        )

    def review(self, title: str, diff: str, max_tokens: int = 2048) -> str:
        """Send a PR diff to OmniRoute and return the generated review text."""
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(title, diff)},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }
        resp = self._session.post(url, json=payload, timeout=self._timeout)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise AIAPIError(f"AI backend returned {resp.status_code}: {resp.text[:200]}") from exc

        log.debug("AI response body (first 500 chars): %s", resp.text[:500])
        return _extract_content(resp.json())


def build_prompt(title: str, diff: str) -> str:
    return f"PR Title: {title}\n\nDiff:\n```diff\n{diff}\n```\n\nСделай code review."


def _extract_content(data: dict[str, Any]) -> str:
    """Defensively extract content from an OpenAI-compatible chat completion response."""
    try:
        choices = data["choices"]
        if not choices:
            raise AIAPIError("AI response 'choices' is empty")
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise AIAPIError("AI response message has no 'content' field")
        if not isinstance(content, str):
            raise AIAPIError(f"AI response content is not a string: {type(content)}")
        return content.strip()
    except (KeyError, AttributeError, TypeError) as exc:
        # Make sure we never dump the raw AI key with the error, just shape info.
        body_preview = str(data)[:200] if isinstance(data, dict) else str(type(data))
        raise AIAPIError(f"Unexpected AI response shape: {body_preview}") from exc
