---
description: Track and increase test coverage
---

# Test Coverage Workflow

Use this workflow to monitor and improve the test coverage of the `growspace_manager` component.

## 1. Establish Coverage Baseline

Run this command to establish a baseline in `COVERAGE_REPORT.md`:
// turbo

```bash
.venv/bin/pytest --cov=custom_components/growspace_manager --cov-report=term-missing tests/ > COVERAGE_LATEST.txt && \
TOTAL_COV=$(grep "TOTAL" COVERAGE_LATEST.txt | awk '{print $4}') && \
echo "Latest Coverage: $TOTAL_COV on $(date)" >> COVERAGE_REPORT.md && \
echo "Baseline established: $TOTAL_COV"
```

## 2. Identify Coverage Gaps

Check `COVERAGE_LATEST.txt` for files with < 100% coverage and missing lines.
// turbo

```bash
grep -v "100%" COVERAGE_LATEST.txt | grep -v "---" | grep -v "TOTAL" | sort -k4 -n
```

## 3. Increase Coverage

For each file identified in step 2:

1. Open the file and locate the missing lines (last column in the report).
2. Create or update the corresponding test file in `tests/`.
3. Run the specific test with coverage to verify the increase.

```bash
.venv/bin/pytest --cov=custom_components/growspace_manager/PATH_TO_FILE --cov-report=term-missing tests/TEST_FILE.py
```

## 4. Verify Total Coverage

Run the full suite again to ensure the total coverage has increased and no regressions were introduced.
// turbo

```bash
.venv/bin/pytest --cov=custom_components/growspace_manager --cov-report=term-missing tests/
```
