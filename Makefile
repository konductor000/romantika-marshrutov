.PHONY: check migrate run-web run-bot run-worker

# MEDIA_DIR has no default in the settings (see romantika/config.py); the run targets fall back
# to the checkout so local runs work without a .env. Deployment sets it in the environment.
MEDIA_DIR ?= $(CURDIR)/data/media

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy romantika
	uv run pytest -q

migrate:
	MEDIA_DIR=$(MEDIA_DIR) uv run alembic upgrade head

run-web:
	MEDIA_DIR=$(MEDIA_DIR) uv run python -m romantika.web

run-bot:
	MEDIA_DIR=$(MEDIA_DIR) uv run python -m romantika.bot

run-worker:
	MEDIA_DIR=$(MEDIA_DIR) uv run python -m romantika.worker
