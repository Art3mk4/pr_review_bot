"""WSGI entry point for the PR Review Bot."""

import logging

from dotenv import load_dotenv
from pr_review_bot.app import create_app
from pr_review_bot.config import load_config

# Populate os.environ from .env before load_config() reads it. In Docker the
# file is absent (env_file injects the variables directly) and this is a no-op.
load_dotenv()

config = load_config()

logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = create_app(config)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.port)
