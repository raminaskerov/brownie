# Repository Guidelines

## Project Structure & Module Organization

Brownie is a Python 3.12+ browser runner using Playwright and an installed Google Chrome.

- `src/brownie_agent/`: application package. `cli.py` handles commands; `browser.py` owns browser sessions; `observe.js` extracts viewport observations; `actions.py` validates execution; `reader.py` performs bounded scrolling.
- `steering.py`, `model.py`, and `text_model.py` separate action selection from field-text generation. `state.py` and `controller.py` track decision state and execution limits.
- `tests/`: pytest modules and local HTML fixtures, including login, delayed navigation, and pagination pages.
- `pyproject.toml`: dependencies, Hatchling packaging, and tool configuration. `README.md`: setup and browser workflows.

## Build, Test, and Development Commands

- `uv sync`: install runtime and development dependencies.
- `uv run brownie --headed https://example.com`: observe a page in a visible browser.
- `uv run brownie --read-page --max-scrolls 3 https://example.com`: read successive viewports with a fixed limit.
- `uv run python -m pytest`: run the offline test suite.
- `uv run python -m pytest tests/test_controller.py`: run one focused test module.
- `uv run ruff check .`: check Python errors and import ordering.
- `uv build`: build source and wheel distributions through Hatchling.

## Coding Style & Naming Conventions

Use four-space Python indentation, type annotations, `snake_case` functions/modules, `PascalCase` classes, and uppercase constants. Ruff enforces `E`, `F`, and `I` rules with a 120-character line limit. Follow the existing two-space indentation and camelCase names in `observe.js`.

## Testing Guidelines

Name tests `tests/test_*.py` with descriptive `test_*` functions. Use local HTML fixtures, `tmp_path` profiles, and fake model/browser responses; tests must not require live services or API keys. Browser integration tests require installed Chrome with its security sandbox enabled. Cover changed behavior and failure boundaries; no numeric coverage threshold is configured.

## Commit & Pull Request Guidelines

History contains only `init` and `BMW_M4`, so no consistent commit convention exists. Use concise, imperative subjects describing the change. PRs should explain behavior changes, link relevant issues, and report checks run and limitations. Update README examples when CLI behavior changes.

## Browser Boundaries & Configuration

Keep Brownie independently runnable. Execute only validated operations against fresh observations; never retry mutations or accept model-provided selectors or JavaScript. The bounded automatic search runner applies the controller guards and uses the user's original goal inside a fixed, code-owned search objective. Research mode has an advisory planner above separate bounded one-source searches; it cannot issue browser operations or bypass the validated executor. Keep `.env` and browser profiles private and untracked; bind debugging endpoints to localhost. Never disable Chrome's security sandbox.
