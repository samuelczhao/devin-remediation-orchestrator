.PHONY: quality run simulate docker-up docker-down

quality:
	uv run python -m mypy app tests
	uv run python -m mypy --explicit-package-bases --follow-imports=silent verification/pr4
	uv run python -m pytest tests verification/pr4/test_verify.py
	uv run python -m ruff check .
	uv run python -m ruff format --check .

run:
	uv run uvicorn app.main:app --reload

simulate:
	uv run python scripts/simulate_webhook.py

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
