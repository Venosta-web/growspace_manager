---
description: Verify Home Assistant Integration Quality Scale Compliance
---
1. Check `manifest.json` for `"quality_scale"` key.
2. Run `ruff check custom_components/growspace_manager` to ensure no linting errors.
3. Run `pytest tests/` to ensure all tests pass.
4. Review `custom_components/growspace_manager/quality_scale.yaml` against the official checklist.
5. Verify that all rules for the target quality scale (and below) are marked as `done` or `exempt`.
