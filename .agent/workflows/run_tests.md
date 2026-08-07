---
description: How to run pytest for the Growspace Manager backend
---

// turbo-all

## Running Backend Tests

Run from the checkout root, through the repo-local venv (Python 3.14+). One venv lives in the main checkout and every worktree shares it; if it does not exist yet, see "Creating or refreshing the venv" in `CLAUDE.md`.

1. Run pytest:

```bash
cd /home/maxi/core/core/vendor/growspace_manager
.venv/bin/pytest tests/ -q
```

From a `.worktrees/<branch>` worktree, reach the same venv the pre-commit hooks use:

```bash
../../.venv/bin/pytest tests/ -q
```

2. Run with coverage:

```bash
.venv/bin/pytest tests/ --cov=custom_components.growspace_manager --cov-report=term-missing -q
```

3. Run a specific test file:

```bash
.venv/bin/pytest tests/test_<module>.py -v
```

4. Run tests matching a pattern:

```bash
.venv/bin/pytest tests/ -k "test_pattern" -v
```

## Notes

- **Never use the Home Assistant core venv at `/home/maxi/core/core/.venv`.** It is HA core's own test environment, so it carries HA core's syrupy rather than the version `pytest-homeassistant-custom-component` pins; every test import then dies inside `pytest_homeassistant_custom_component/syrupy.py`. It surfaces as a collection error, which reads like a broken test rather than a wrong interpreter.
- Always call pytest through the venv path rather than a bare `pytest` — the system `python3` is not 3.14.
- `pytest.ini` sets `pythonpath = .`, so run from the checkout root and no `PYTHONPATH` export is needed.
- The `-q` flag provides quiet output, use `-v` for verbose.
