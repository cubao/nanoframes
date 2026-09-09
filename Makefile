SHELL := /bin/bash
PY ?= python3

.PHONY: install test pytest lint build sdist upload clean

install:
	$(PY) -m pip install -e .[dev]

test:
	$(PY) -m pytest -q

pytest:
	$(PY) -m pytest -q

lint:
	ruff check nanoframes tests

# Local build: sdist + wheel into dist/ (hatchling; wheel embeds docs/skills/font).
build:
	$(PY) -m pip install --upgrade build
	$(PY) -m build .

# PyPI artifact: a fresh sdist only (mirrors ../redisk; pip builds the wheel
# from it on install). Dry-run check:  twine check dist/*.tar.gz
sdist:
	rm -rf dist
	python3 -m pipx run build --sdist

# Publish the sdist to PyPI (needs twine + ~/.pypirc credentials).
# Test index first:  twine upload dist/nanoframes-*.tar.gz -r testpypi
upload: sdist
	twine upload dist/nanoframes-*.tar.gz -r pypi

clean:
	rm -rf build dist *.egg-info nanoframes.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf out