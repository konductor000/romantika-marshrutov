.PHONY: check migrate run-web run-bot run-worker

# MEDIA_DIR has no default in the settings (see romantika/config.py) and the run targets do not
# inject one: an injected value would beat the `.env` a developer wrote (an environment variable
# wins over dotenv in pydantic-settings). Set it in `.env` locally, in the environment in
# deployment; an unset MEDIA_DIR fails loudly at startup.

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy romantika
	uv run pytest -q

migrate:
	uv run alembic upgrade head

run-web:
	uv run python -m romantika.web

run-bot:
	uv run python -m romantika.bot

run-worker:
	uv run python -m romantika.worker
