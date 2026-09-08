SHELL := /bin/bash
PY ?= python3

.PHONY: install test pytest lint build clean

install:
	$(PY) -m pip install -e .[dev]

test:
	$(PY) -m pytest -q

pytest:
	$(PY) -m pytest -q

lint:
	ruff check nanoframes tests

build:
	$(PY) -m pip install --upgrade build
	$(PY) -m build .

clean:
	rm -rf build dist *.egg-info nanoframes.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf out