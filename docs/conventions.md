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

## Quality Gates
- Lint/format: `ruff`.
- Typing: `mypy` (permissive mode during migration).
- Test default excludes hardware-marked tests.
