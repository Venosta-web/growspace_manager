# ADR 0020 — CI Merge Gate + HA-Core-Aligned Test Rules

**Status:** Accepted

## Context

CI in this repo was advisory, not defensive. Three gaps let a broken change reach
the integration branch:

1. **No branch protection.** Every branch was unprotected, so even when `tests.yaml`
   went red a PR could still be merged. The workflows existed but enforced nothing.
2. **CI never ran ruff or mypy.** `tests.yaml` ran `pytest --cov` only. Linting and
   type-checking lived solely in `.pre-commit-config.yaml`, which checks *staged*
   files. A `git commit --no-verify` (or any path where the hook didn't fire) merged
   lint- and type-dirty code. Run repo-wide, the accumulated debt was **3887 ruff
   errors** and **460 mypy errors in 74 files**.
3. **The ruff config is HA-core-maximal-strict.** `pyproject.toml` is a 43 KB copy of
   Home Assistant core's config, but its `per-file-ignores` are keyed to core's paths
   (`homeassistant/*`, `tests/components/*`) and were never re-pointed at this repo's
   layout. The dominant errors were artefacts of that mismatch, not real debt:
   **2392 `SLF001`** (private-member access) and **800 `D1xx`** (missing docstrings)
   were in `tests/**`. HA core itself ignores `SLF001` in its own tests; we simply
   never inherited that ignore.

The maintainer is effectively the sole developer on the repo, which makes the
"who does the gate bind?" question sharp: a soft gate a solo dev can click past is
indistinguishable from no gate.

## Decision

1. **Branch protection on `dev` and `main`, administrators included (hard gate).**
   Required status checks block merge even for the repo owner. Merging a red PR
   requires deliberately lifting protection — friction is the point. This is what
   converts CI from advisory to defensive.

2. **CI gains required ruff and mypy jobs**, run repo-wide, in addition to
   `pytest --cov` and the existing hassfest/HACS validation. The three tiers are
   split by speed: fast lint/format on **commit** (pre-commit), mypy + unit tests on
   **push** (pre-push), the full suite on the **PR** gate.

3. **`per-file-ignores` are re-pointed at this repo's layout to match HA core's own
   stance**, ignoring `SLF001` and the docstring `D1xx` rules under `tests/**`. This
   is a *correction* of an inherited path mismatch, not a relaxation of the bar:
   production code in `custom_components/` stays fully strict. Tests legitimately
   poke internals and do not need docstrings on every function — the same judgement
   HA core makes for its own tests.

4. **Burn the baseline down to zero before turning on the repo-wide gate**, rather
   than ratcheting on changed files only. After the config correction (~3200 errors)
   and `ruff --fix` (~222), the genuine residual is ~470 src ruff items + 460 mypy
   errors. We fix those first so the gate is green on day one and stays meaningful,
   rather than carrying a permanent suppressed-debt list.

## Consequences

- Stacked feature branches that PR into *other* feature branches are not gated until
  they land on `dev`. That is the intended place for the gate to bite.
- Choosing fix-first over ratchet is the larger up-front cost, paid once, in exchange
  for a clean repo-wide bar with no per-file suppression to reason about later.
