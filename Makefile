.PHONY: setup lint test clean all

setup:
	pip install -e ".[dev]"

lint:
	ruff check .

test:
	pytest --tb=short

clean:
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache dist/ build/

all: lint test
