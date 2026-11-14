.PHONY: setup test lint processar status custos promover

setup:
	uv sync
	uv run python scripts/bootstrap.py

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

processar:
	uv run python scripts/estudos.py processar

status:
	uv run python scripts/estudos.py status

custos:
	uv run python scripts/estudos.py custos

promover:
	uv run python scripts/promover.py
