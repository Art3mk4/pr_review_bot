# PR Review Bot

Бот для автоматического AI-ревью Pull Request'ов на GitHub.

Реагирует на события:
- `pull_request`: `opened`, `synchronize`, `reopened` — автоматический обзор.
- `issue_comment`: новый комментарий с текстом `/review` — обзор по запросу.

Для генерации ревью используется OmniRoute (OpenAI-compatible API). По умолчанию модель — `kr/qwen3-coder-next`.

---

## Быстрый старт

### 1. Клонирование и настройка окружения

```bash
cd pr_review_bot
cp env.example .env
# заполни .env своими значениями
```

### 2. Запуск через Docker Compose

```bash
docker compose up --build -d
```

Проверь, что бот жив:

```bash
curl http://localhost:8080/health
```

Ожидаемый ответ:

```json
{"ai":"omniroute","model":"kr/qwen3-coder-next","status":"ok"}
```

---

## Настройка GitHub Webhook

1. Открой настройки репозитория: **Settings → Webhooks → Add webhook**.
2. **Payload URL**: `http(s)://адрес_твоего_сервера:8080/webhook`.
   - Если сервер запущен локально для тестов — используй [ngrok](https://ngrok.com/):
     ```bash
     ngrok http 8080
     ```
     и вставь полученный публичный URL, оканчивающийся на `/webhook`.
3. **Content type**: `application/json`.
4. **Secret**: `WEBHOOK_SECRET` из `.env`.
5. В разделе **Which events would you like to trigger this webhook?** выбери **Let me select individual events** и отметь:
   - Pull requests
   - Issue comments
6. Нажми **Add webhook**.

После этого бот будет автоматически ревьюить PR при открытии/обновлении, а также по команде `/review` в комментариях к PR.

### Принудительный запуск ревью

Чтобы запустить ревью вручную, оставь в PR комментарий, **первое слово в котором** — команда:

```text
/review
```

Например:

```text
/review пожалуйста
```

(`/reviewer needed?` командой не считается.) Бот поставит реакцию 👀 и запустит AI-обзор.

> **Примечание:** команда `/review` работает только в комментариях к Pull Request'ам, но не в обычных issues. Комментарии от имени ботов игнорируются — иначе два бота, вызывающие `/review` друг у друга, устроили бы лавину AI-запросов.

---

## Требования к GitHub-токену

Создай Personal Access Token (classic) на https://github.com/settings/tokens:

- `repo` → read
- `pull_requests` → write (входит в scope `repo` для приватных репозиториев)

Если бот работает с публичными репозиториями, достаточно `public_repo`.

Укажи полученный токен в `.env` как `GITHUB_TOKEN`.

---

## Переменные окружения

```env
GITHUB_TOKEN=ghp_xxxxxxxxx
WEBHOOK_SECRET=your_random_secret
OMNIROUTE_BASE_URL=https://omniroute.art3mk4.site/v1
OMNIROUTE_API_KEY=sk-xxxxxxxxxxxx
OMNIROUTE_MODEL=kr/qwen3-coder-next
PORT=8080
```

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | — |
| `WEBHOOK_SECRET` | Секрет для проверки подписи вебхуков | — |
| `OMNIROUTE_BASE_URL` | Базовый URL OmniRoute | `https://omniroute.art3mk4.site/v1` |
| `OMNIROUTE_API_KEY` | API-ключ OmniRoute | — |
| `OMNIROUTE_MODEL` | Модель для code review | `kr/qwen3-coder-next` |
| `PORT` | Порт для `python server.py`; gunicorn в контейнере всегда слушает 8080 | `8080` |

---

## Запуск тестов

```bash
# Тесты внутри Docker
 docker build --target test -t pr_review_bot:test .
 docker run --rm pr_review_bot:test
```

---

## Полезные команды

```bash
# Пересобрать и перезапустить
 docker compose down
 docker compose up --build -d

# Логи
 docker compose logs -f

# Остановить
 docker compose down
```

---

## Архитектура

- `server.py` — точка входа WSGI для Gunicorn.
- `pr_review_bot/config.py` — загрузка и валидация конфигурации.
- `pr_review_bot/clients/github.py` — клиент для GitHub API.
- `pr_review_bot/clients/ai.py` — клиент для OmniRoute.
- `pr_review_bot/services/review.py` — оркестрация ревью: diff → AI → комментарий.
- `pr_review_bot/webhook/` — проверка подписи и обработчики событий.
- `pr_review_bot/app.py` — фабрика Flask-приложения.
- `tests/` — тесты на pytest.
