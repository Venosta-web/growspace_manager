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
