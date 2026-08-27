# ADR 0020 — CI Merge Gate + HA-Core-Aligned Test Rules

**Status:** Accepted

## Context

CI in this repo was advisory, not defensive. Three gaps let a broken change reach
the integration branch:

1. **No branch protection.** Every branch was unprotected, so even when `tests.yaml`
   went red a PR could still be merged. The workflows existed but enforced nothing.
2. **CI never ran ruff or mypy.** `tests.yaml` ran `pytest --cov` only. Linting and
   type-checking lived solely in `.pre-commit-config.yaml`, which checks _staged_
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
   is a _correction_ of an inherited path mismatch, not a relaxation of the bar:
   production code in `custom_components/` stays fully strict. Tests legitimately
   poke internals and do not need docstrings on every function — the same judgement
   HA core makes for its own tests.

4. **Burn the baseline down to zero before turning on the repo-wide gate**, rather
   than ratcheting on changed files only. After the config correction (~3200 errors)
   and `ruff --fix` (~222), the genuine residual is ~470 src ruff items + 460 mypy
   errors. We fix those first so the gate is green on day one and stays meaningful,
   rather than carrying a permanent suppressed-debt list.

## Consequences

- Stacked feature branches that PR into _other_ feature branches are not gated until
  they land on `dev`. That is the intended place for the gate to bite.
- Choosing fix-first over ratchet is the larger up-front cost, paid once, in exchange
  for a clean repo-wide bar with no per-file suppression to reason about later.

## Amendment (2026-07-07) — enforcement mechanics and hook-tier cut

A workflow review found decisions 1 and 2 were never fully implemented: no branch
was protected, and no local hook was installed. Rather than re-litigate, the gaps
were closed with three refinements:

1. **Rulesets, not classic branch protection — and `prerelease` is included.**
   The gate lands on `prerelease`, `dev`, and `main` (day-to-day integration happens
   on `prerelease`; the original text predates that). Rulesets require a PR with
   green checks (`ruff`, `mypy`, `validate-hassfest`, `validate-hacs`, pytest) and
   carry a bypass list containing **only the GitHub Actions app**, so release
   workflows pushing with `GITHUB_TOKEN` keep working while humans and agents go
   through PRs.
2. **Zero required approvals.** A PR author cannot approve their own PR, so on a
   solo repo a review requirement is a rule the owner bypasses every time — which
   trains bypassing. Green checks are the merge condition; the human gate on agent
   work is the merge click itself.
3. **The three-tier hook ladder is cut to one tier.** Pre-commit runs fast checks
   only (ruff check/format, codespell, `no-commit-to-branch`, and a worktree guard
   that rejects commits made in the shared main checkout unless
   `ALLOW_MAIN_CHECKOUT=1`). The pre-push test tier is dropped: with the ruleset
   enforcing CI, a slow pre-push hook only invites `--no-verify`.
   `pre-commit install` is part of environment setup so fresh checkouts actually
   have the hook.

## Amendment (2026-08-07) — the gate's install must be reproducible

A gate is only as trustworthy as the environment it runs in. On 2026-08-07 every
branch went red with `ModuleNotFoundError: No module named 'hassil.fuzzy'` — 90
collection errors, zero tests executed. Nothing in the repo had changed:
`prerelease` had passed on the same commit (`0de4458`) four weeks earlier. PyPI
changed. `hassil` was unpinned, `tests.yaml` runs `pip install --upgrade`, and a
fresh resolve floated it to 3.11.0, which no longer ships `hassil/fuzzy.py` — a
module HA 2026.5.4's `conversation` component imports at module scope.

**The same commit passed in July and failed in August.** That is the property
that matters here: a gate whose verdict depends on the calendar cannot
distinguish "this change is broken" from "the index moved," so a red result stops
carrying information and the reflex becomes to bypass rather than investigate —
exactly the behaviour decision 2 of the 2026-07-07 amendment was written to avoid.

This was the third instance of the failure mode. `home-assistant-intents` floated
and broke collection once before (the comment above the `homeassistant` pin
records it), `hassil` was the other half of that same pair left floating, and
~20 further dependencies in `requirements.txt` — `voluptuous`, `Pillow`,
`pydantic`, `ruff`, `pytest-asyncio` — remain unpinned under `--upgrade` today.

Two decisions follow:

1. **Every dependency that HA core itself pins is pinned here to the value HA
   pins.** The chain is `pytest-homeassistant-custom-component==0.13.333` →
   `homeassistant==2026.5.4` → `hassil==3.5.0`; HA ships that mapping as
   `homeassistant/package_constraints.txt`, so it is a fact to be read, not a
   judgement to be made. The near-term mechanism is a direct pin. The intended
   end state is a constrained install using Home Assistant's packaged
   `package_constraints.txt` after installing `homeassistant` — which closes the
   class rather than one member of it. A
   dry-run confirms the constraints file resolves cleanly against this
   `requirements.txt` with no conflicts.

   _Rejected:_ a lockfile. A stale `uv.lock` is tracked in the repo root, last
   touched 2026-05-11, referenced by no workflow, and does not contain `hassil`.
   It is debris, not a live mechanism. Adopting a lockfile would mean maintaining
   a second source of truth alongside HA's constraints file, which would drift
   from it; deleting the file is preferable to reviving it.

2. **CI must not lose all signal to one bad transitive dependency.** The pin
   addresses the trigger; the blast radius was a separate defect. Four modules
   imported `homeassistant.components.conversation` / `.ai_task` at module scope
   while sitting on the `__init__` → `service_registration` → `coordinator` chain,
   so an optional AI feature's dependency could take down collection of all 4853
   tests. Those imports are deferred to their call sites. The two mitigations are
   deliberately independent: the pin prevents the bad resolve, and the deferral
   means a bad resolve that slips through costs the AI tests rather than the
   entire suite.

### Consequences

- Bumping `homeassistant` is now a deliberate act with a checklist — the pinned
  HA-owned dependencies move with it — rather than something `--upgrade` does
  silently between runs.
- Deferred imports cost a `PLC0415` `noqa` at each site and mean tests must patch
  `homeassistant.components.conversation`, not the importing module. This is the
  price of keeping collection independent of HA's optional component tree, and the
  pattern already existed in `briefing_scheduler.py`.
- Pinning transitively-owned dependencies by hand is a stopgap. Until the
  constrained install lands, a `homeassistant` bump that changes a pin we mirror
  will fail CI until the mirrored value is updated by hand.

## Amendment (2026-08-12) — test against Home Assistant 2026.8.1

The standalone test and CI baseline moves from Home Assistant 2026.5.4 to
2026.8.1. Its coupled dependency chain moves with it:

- `pytest-homeassistant-custom-component==0.13.355` pins
  `homeassistant==2026.8.1`;
- Home Assistant 2026.8.1's packaged constraints pin `hassil==3.11.0` and
  `home-assistant-intents==2026.7.30`.

The two-phase constrained install remains the source of truth for the rest of
Home Assistant's dependency graph. The explicit `hassil` and
`home-assistant-intents` pins remain mirrored in `requirements.txt` so an
accidental unconstrained install still fails deterministically rather than
silently selecting a different pair.

`hacs.json` retains Home Assistant 2026.5.4 as the minimum supported runtime.
Moving the development baseline does not by itself justify dropping working
installations on 2026.5 through 2026.7. Compatibility fixes exposed by the new
baseline must preserve that minimum; a change that cannot do so requires a
separate decision to raise it. CI continues to exercise one Home Assistant
version for now. A minimum-and-latest matrix is a separate reliability change
with its own paired test-helper dependency maintenance.

## Amendment (2026-08-27) — formatting and typing are blocking gates

The repository-wide Ruff formatting and mypy baselines are now clean. The
temporary `continue-on-error` exceptions in `lint.yaml` are removed: formatting
or typing regressions fail the `Ruff` or `mypy` job and therefore block merging.

CI deliberately runs the same commands as the prescribed local backend gate:

- `ruff format --check custom_components/ tests/`
- `mypy --follow-imports=silent custom_components/`

Both commands use the repository's `pyproject.toml` configuration. Ruff and mypy
versions are pinned identically for CI and local development in `lint.yaml` and
`requirements.txt`; the Ruff pre-commit hook carries the matching version as
well. Any version bump must update those pins together so local and CI verdicts
remain equivalent.

## Amendment (2026-08-27) — one validation event per change boundary

The lint, test, and HACS/Hassfest workflows validate feature-branch commits on
`pull_request`, not on their simultaneous `push` event. Their `push` triggers are
therefore limited to the protected `prerelease`, `dev`, and `main` branches, where
post-merge and direct-push validation must remain available. Without that branch
filter, a commit pushed to a same-repository pull request emits both events and
runs every validation workflow twice.

Each validation workflow has its own concurrency group, keyed by pull-request
number for PR events and by the unique workflow run ID otherwise. A newer commit
cancels the superseded run of the same workflow for the same pull request.
Protected-branch pushes and manual runs are never cancelled by this policy.

Release concurrency remains a separate concern. Stable and prerelease publishing
use dedicated `stable-publish` and `prerelease-publish` groups with cancellation
disabled, so validation churn cannot cancel a publishing run. Workflow names and
job names remain unchanged because the repository ruleset uses those status checks
as merge gates.
