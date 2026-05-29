---
description: How to run pytest for the Growspace Manager backend
---

// turbo-all

## Running Backend Tests

1. Run pytest with the project venv (Python 3.13+):

```bash
cd /home/maxi/core/core/vendor/growspace_manager
/home/maxi/core/core/.venv/bin/pytest tests/ -q
```

2. Run with coverage:

```bash
/home/maxi/core/core/.venv/bin/pytest tests/ --cov=custom_components.growspace_manager --cov-report=term-missing -q
```

3. Run a specific test file:

```bash
/home/maxi/core/core/.venv/bin/pytest tests/test_<module>.py -v
```

4. Run tests matching a pattern:

```bash
/home/maxi/core/core/.venv/bin/pytest tests/ -k "test_pattern" -v
```

## Notes

- The venv at `/home/maxi/core/core/.venv` contains Python 3.13+ with all required dependencies
- Always use the full path to pytest to ensure correct Python version and dependencies
- The `-q` flag provides quiet output, use `-v` for verbose
