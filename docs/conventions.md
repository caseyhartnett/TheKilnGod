# Project Conventions

## Naming
- Python: modules/files `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- JavaScript/TypeScript: functions/variables `camelCase`, classes `PascalCase`, file naming consistent within each package.
- Shell scripts: `kebab-case`.

## Layout
- Runtime Python package: `src/thekilngod/`.
- Unified CLI entrypoint: `thekilngod`.
- Operational/debug scripts: `scripts/`.
- Tests: `tests/unit`, `tests/integration`, `tests/hardware`.

## Python Env
- Canonical virtual environment path: `.venv/`.
- Runtime install: `.venv/bin/python -m pip install -e .`
- Development install: `.venv/bin/python -m pip install -e .[dev]`
- `pyproject.toml` is the dependency source of truth.

## Quality Gates
- Lint: `.venv/bin/ruff check src tests scripts ui-v2/src`
- Format check: `.venv/bin/ruff format --check src tests scripts ui-v2/src`
- Typing: `.venv/bin/mypy src`
- Tests: `.venv/bin/pytest` (default excludes hardware-marked tests)
- Frontend build smoke test: `cd ui-v2 && npm run build`
