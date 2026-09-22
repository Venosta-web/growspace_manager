# Vendored Growspace Vision V1 contract fixtures

These files are copied verbatim from the Vision repository, which owns the
normative contract:

- source: `Venosta-web/growspace_manager_vision`,
  `contracts/growspace-vision/v1/fixtures/`
- commit: `088a1e272c0966c83539c704ddd88709f5350d57` (2026-09-01)
- normative schema: `contracts/growspace-vision/v1/openapi.json` in that
  repository

**Do not edit them here.** They are frozen inputs, not test data to adjust
until a test passes: their whole job is to fail this repository's parser when
the wire shape drifts. A contract change starts in the Vision repository
(hub `AGENTS.md`, "Cross-repo contract"), and only then is re-vendored here
with the commit above updated.

`manifest.json` maps every fixture to its component schema and expected
validity, and `tests/test_vision_models.py` walks it, so a fixture added
upstream is exercised as soon as it is copied across.

`invalid/` is the load-bearing half. Those bodies are the outputs V1 must never
be able to emit — `symptoms`, `chlorosis`, `drooping`, the Home Assistant-owned
`anomaly_score`, `change_score` and `trend`, environmental request fields, and a
quality-rejected frame carrying an embedding. Each one must raise
`VisionProtocolError` rather than being parsed into something usable.
