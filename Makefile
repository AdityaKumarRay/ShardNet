.PHONY: install lint format-check typecheck test run-tracker run-agent run-desktop docker-tracker-up docker-tracker-down

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

run-agent:
	python -m shardnet.client.agent.main

run-desktop:
	cd desktop && npm install && npm run start

docker-tracker-up:
	docker compose up --build tracker

docker-tracker-down:
	docker compose down
