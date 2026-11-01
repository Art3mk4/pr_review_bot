FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pr_review_bot ./pr_review_bot
COPY server.py .

FROM base AS test

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY tests ./tests

CMD ["pytest", "-q"]

FROM base AS production

RUN useradd --system --no-create-home bot && chown -R bot /app
USER bot

EXPOSE 8080

# graceful-timeout > the 120s AI client timeout: atexit waits for in-flight
# reviews (executor.shutdown(wait=True)); the 30s default would SIGKILL them.
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:8080", "--timeout", "120", "--graceful-timeout", "130", "server:app"]
