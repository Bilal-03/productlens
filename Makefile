.PHONY: dev db bootstrap-roles migrate seed seed-smoke seed-validate integration preflight test benchmark lint build e2e

db:
	docker compose up -d postgres

bootstrap-roles:
	cd backend && .venv/bin/python -m app.data.bootstrap_roles

migrate:
	cd backend && .venv/bin/alembic upgrade head

seed:
	cd backend && .venv/bin/python -m app.data.generate --profile full --load

seed-smoke:
	cd backend && .venv/bin/python -m app.data.generate --profile smoke --load

seed-validate:
	cd backend && .venv/bin/python -m app.data.generate --validate-only

integration: migrate seed-smoke
	cd backend && RUN_DB_INTEGRATION=1 .venv/bin/pytest -m integration

preflight: build
	python3 scripts/deployment_preflight.py --require-frontend-build

test:
	cd backend && .venv/bin/pytest
	cd frontend && npm test -- --run

benchmark:
	PYTHONPATH=backend backend/.venv/bin/python evals/run_benchmark.py

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/mypy app
	cd frontend && npm run lint && npm run typecheck

build:
	cd frontend && npm run build

e2e:
	cd frontend && npm run test:e2e
