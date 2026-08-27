# Adding the Lovelace card to backend test instances

Backend tests use the authoritative, checksummed snapshot at
`tests/fixtures/lovelace/growspace-manager-card.js`. Test setup never reads a
sibling `lovelace-growspace-manager-card` checkout or mutable `dist/` output.

## Prepare configuration-local fixtures

From the backend repository root, run:

```bash
python tests/utils/prepare_lovelace_fixtures.py
```

The command discovers every `tests/*/configs/configuration.yaml` that declares
`/local/growspace-manager-card.js`, then places a private copy under that
configuration's `www/` directory. These copies are ignored and can be recreated
at any time. Verify them without changing files with:

```bash
python tests/utils/prepare_lovelace_fixtures.py --check
```

A missing or stale fixture produces an error listing the affected paths and the
repair command. The preparer also rejects an authoritative snapshot that does
not match its tracked checksum.

## Docker test instances

`docker compose up` copies the same authoritative snapshot into each isolated
Home Assistant configuration volume during initialization. To deploy it again
to a running instance, use:

```bash
./tests/utils/add-lovelace-resource.sh homeassistant homeassistant-dev
./tests/utils/add-lovelace-resource.sh homeassistant-test homeassistant-test
```

The resource URL declared by the test configurations is:

```yaml
lovelace:
  mode: yaml
  resources:
    - url: /local/growspace-manager-card.js
      type: module
```

After replacing a fixture in a running instance, hard-refresh the browser.

## Refresh the authoritative snapshot

Only refresh the tracked snapshot intentionally, from a build made in an
isolated card worktree:

```bash
python tests/utils/prepare_lovelace_fixtures.py \
  --update-from /absolute/path/to/dist/growspace-manager-card.js
```

Commit the updated JavaScript bundle and `.sha256` file together. Routine setup
must not use `--update-from`.
