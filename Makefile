.PHONY: install lint format-check typecheck test run-tracker docker-tracker-up docker-tracker-down

install:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

lint:
	ruff check .

format-check:
	ruff format --check .

typecheck:
	mypy src

test:
	pytest -q

run-tracker:
	python -m shardnet.tracker.main

docker-tracker-up:
	docker compose up --build tracker

docker-tracker-down:
	docker compose down
