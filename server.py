"""WSGI entry point for the PR Review Bot."""

from pr_review_bot.app import create_app
from pr_review_bot.config import load_config

config = load_config()
app = create_app(config)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.port)
