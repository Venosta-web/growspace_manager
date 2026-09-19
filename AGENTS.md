# Agent instructions — growspace_manager

## Session isolation: work in a worktree

This checkout is shared by concurrent agent sessions; editing it directly has
wiped in-flight work before. For anything beyond a trivial single-turn change:

```bash
git fetch origin
git worktree add .worktrees/<branch-name> -b <branch-name> origin/<base>
cd .worktrees/<branch-name>
```

- The pre-commit worktree guard rejects commits made in the main checkout;
  override deliberately with `ALLOW_MAIN_CHECKOUT=1` for quick fixes only.
- If the working tree looks wrong or edits seem to have vanished, trust
  `origin`, not the checkout — another session may have moved HEAD.
- Clean up with `git worktree remove` once the PR is open.

## Test environment

One repo-local `.venv` (Python 3.14) lives in the main checkout and every
worktree shares it: `.venv/bin/pytest` from the main checkout,
`../../.venv/bin/pytest` from a worktree — the path the pre-commit hooks
already use. **Never the HA core venv at `/home/maxi/core/core/.venv`**: its
syrupy is newer than the one `pytest-homeassistant-custom-component` pins, so
every test import dies at collection. Building or refreshing the venv is
documented in `CLAUDE.md`.

## Base branches

- Architecture/refactor work integrates on **`prerelease`**, not `dev`.
- Crop-steering feature work integrates on **`feat-stageAnalyzer`**.
- Check the issue / parent PR for stacked topologies before branching, and
  target the PR at the same base you branched from.

## Merge gates

`prerelease`, `dev`, and `main` are ruleset-protected: PR + green checks
(ruff, mypy, hassfest, HACS, pytest), zero required approvals, bypass only for
the GitHub Actions app. Run `pre-commit install` after a fresh clone. See
`docs/adr/0020` (amended) and `docs/adr/0030` for the cross-repo contract
fixture and GSM-first landing order.

### Patch coverage is a sixth gate, and it is the one that gets missed

Codecov posts a **`codecov/patch`** status on every PR, and its target is
`auto` against this repository's own coverage — so in practice **every line a
PR adds has to be executed by a test**. It is not in the list above because it
is not in the ruleset, and it is not in `gh pr checks` output either: that
command has printed only the five ruleset checks, all green, on a PR whose
patch status was red. Read `gh pr view <n> --json statusCheckRollup` instead,
or the Codecov comment on the PR.

Nothing local runs it for you — `pre-commit` runs pytest without coverage — so
check your own patch before pushing:

```bash
../../.venv/bin/pytest tests/<the suites you touched> -q \
  --cov=custom_components/growspace_manager/<the package you touched> \
  --cov-report=term-missing
```

Three shapes account for nearly all of it, and none of them is reached by a
feature test by accident:

- **`as_dict` wire forms.** A result dataclass whose wire shape nothing
  asserts is an uncovered `return {`. `tests/labels/test_template_wire.py` is
  where that belongs.
- **Refusal branches.** Every `raise` wants a test that provokes it. The
  parametrized tables in the label suites exist for exactly this: one row per
  operation beats one test per operation, and an operation added without a row
  is the gap that shape makes obvious.
- **Readers of documents from outside** (a portable bundle, a backup, a stored
  library). Their structural refusals are far quicker to reach by calling the
  reader directly than by driving a whole library into the shape that produces
  them.

`pyproject.toml`'s `[tool.coverage.report]` already excludes what genuinely
cannot run — `if TYPE_CHECKING:`, `@overload`, `...` stubs, `raise
NotImplementedError`. Prefer a test over adding to that list, and keep
`pragma: no cover` for code that cannot be executed rather than code nobody
got round to exercising.
