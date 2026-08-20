.PHONY: quality run simulate docker-up docker-down

quality:
	uv run python -m mypy app tests
	uv run python -m pytest
	uv run python -m ruff check .

run:
	uv run uvicorn app.main:app --reload

simulate:
	uv run python scripts/simulate_webhook.py

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
