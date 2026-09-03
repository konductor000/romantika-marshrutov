.PHONY: check migrate run-web run-bot run-worker

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
