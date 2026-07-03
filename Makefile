# Convenience targets (Mac/Linux). Windows users: see start.ps1 or the README.
.PHONY: setup backend frontend gen test lint

setup:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

gen:
	cd frontend && npm run gen:api

test:
	cd backend && . .venv/bin/activate && pytest -q

lint:
	cd backend && . .venv/bin/activate && ruff check . && mypy
	cd frontend && npm run lint
