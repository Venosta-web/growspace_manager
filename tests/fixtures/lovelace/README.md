# Lovelace card test fixture

`growspace-manager-card.js` is the repository's authoritative card snapshot for
backend Home Assistant configurations. It is intentionally tracked here so a
backend worktree never reads a sibling card checkout or another task's mutable
`dist/` output.

Prepare a real, private copy in every configuration that declares the card:

```bash
python tests/utils/prepare_lovelace_fixtures.py
```

The copies under `tests/*/configs/www/` are ignored build artifacts. Verify
them without changing anything with `--check`. Both modes validate the tracked
checksum and print an actionable error for missing or stale content.

To intentionally refresh the authoritative snapshot after building the card in
an isolated card worktree:

```bash
python tests/utils/prepare_lovelace_fixtures.py \
  --update-from /absolute/path/to/dist/growspace-manager-card.js
```

Commit the updated bundle and checksum together. Routine test setup must not use
`--update-from`.
