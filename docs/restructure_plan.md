# Codebase Restructuring Plan (No Functional Changes)

## Goal
Modernize the `TheKilnGod` project structure and conventions using best practices while strictly preserving existing behavior and integrations.

## 1. Define non-functional-change guardrails
- Freeze current behavior with a baseline checklist: startup flow, PID controller loop, API/WebSocket responses, logging output, hardware I/O scripts, and UI build/run (both legacy and v2).
- Capture before/after command outputs for critical workflows.
- Enforce scope: only file moves, renames, import-path updates, typing, and tooling/config updates. No logic changes to the underlying kiln control.

## 2. Establish one project-wide convention document
- Standardize naming across languages:
  - Python: modules/files `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
  - JavaScript/TypeScript: files use one style consistently (`kebab-case` or `snake_case`), functions/variables `camelCase`, classes `PascalCase`.
  - Shell scripts: `kebab-case`.
- Ban mixed naming patterns unless required by a specific framework or tool.

## 3. Move to modern Python package layout
- Create a `src/thekilngod/` package directory and move Python application code there (e.g., `lib/` modules like `oven.py`, `buzzer.py`, `telemetry_math.py`).
- Keep the root directory focused: `pyproject.toml`, `README.md`, `docs/`, `tests/`, `ui-v2/`, `public/`, and `scripts/`.
- Separate runtime application modules from operational/debug scripts (e.g., `scripts/test_thermocouple.py`, `scripts/gpio_readall.py`, `src/thekilngod/display_updater.py`).

## 4. Standardize entry points without behavior changes
- Define CLI entry points in `pyproject.toml` (e.g., `thekilngod`).
- Use the unified CLI as the only supported command surface for runtime and tooling.

## 5. Normalize module and file naming
- Rename Python modules and files to consistent `snake_case`. Prefer underscore naming for importable modules and operational scripts (e.g., `test_thermocouple.py`).
- Update imports and references atomically during each rename step.
- Ensure references in `start-on-boot` or `kiln-controller.service` are updated accordingly.

## 6. Reorganize tests by intent
- Move all tests under a single lowercase `tests/` directory (consolidating the existing `Test/` folder and scattered test files like `test_buzzer.py`).
- Segment into `tests/unit`, `tests/integration`, and `tests/hardware`.
- Mark hardware-dependent tests (e.g., those requiring SPI/I2C or actual GPIO pins) so CI can skip them by default.

## 7. Introduce typing incrementally
- Add type hints first to public interfaces, config objects, and cross-module boundaries (`src/thekilngod/oven.py`, `src/thekilngod/controller.py`).
- Add `mypy` in permissive mode initially, then tighten in phases.
- Use `Protocol`, `TypedDict`, and dataclasses where appropriate without logic rewrites.

## 8. Enforce formatting and lint consistency
- Python: Use `ruff` (lint + format/import organization) or `black` + `isort` if preferred.
- JS/TS (in `ui-v2/`): `eslint` + `prettier`.
- Add `pre-commit` hooks for naming/style/lint/type checks.

## 9. Add CI quality gates
- Run lint, type checks, unit tests, and UI (`ui-v2`) build checks in GitHub Actions CI.
- Add a smoke check stage that validates critical runtime commands/interfaces.

## 10. Execute in small, reviewable PR batches
- **PR 1**: Conventions + tooling config only (`pyproject.toml`, `ruff`, `pre-commit`).
- **PR 2**: Directory/package restructuring only (creating `src/thekilngod/` and moving `lib/` files).
- **PR 3**: File/module renames + import updates.
- **PR 4**: Test relocation (moving `Test/` and root tests to `tests/`) + markers.
- **PR 5+**: Typing rollout by module area.
- Validate baseline checklist after each PR to ensure no broken imports or failed hardware scripts.

## Definition of Done
- No user-visible behavior changes (kilns fire identically).
- Naming is consistent across Python, UI, and scripts.
- Root directory is cleanly reduced to project metadata and top-level project folders.
- Core interfaces are typed and enforced by CI lint/type/test gates.
