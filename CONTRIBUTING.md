# Contributing to Growspace Manager

Thanks for helping. Where to start depends on what you have:

| You have…                        | Go to                                                                                                                                                 |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| A bug                            | [New issue → Bug report](https://github.com/Venosta-web/growspace_manager/issues/new/choose). Attach the diagnostics download; the form explains how. |
| A question                       | [Discussions → Q&A](https://github.com/Venosta-web/growspace_manager/discussions/categories/q-a)                                                      |
| An idea to talk through          | [Discussions → Ideas](https://github.com/Venosta-web/growspace_manager/discussions/categories/ideas)                                                  |
| A concrete feature request       | [New issue → Feature request](https://github.com/Venosta-web/growspace_manager/issues/new/choose)                                                     |
| Results from a commissioned grow | [Discussions → Commissioning results](https://github.com/Venosta-web/growspace_manager/discussions/categories/commissioning-results)                  |
| Code                             | Read on.                                                                                                                                              |

The [roadmap](https://github.com/Venosta-web/growspace_manager_workspace/issues/245)
shows what is planned. Please open or comment on an issue before starting a large
change, so that two people do not build the same thing.

## Development happens in the workspace hub

Growspace Manager ships as several repositories that change together: this
integration, the [Lovelace card](https://github.com/Venosta-web/lovelace-growspace-manager-card),
the optional Tissue Culture companion and the Growspace Vision service. The
[workspace hub](https://github.com/Venosta-web/growspace_manager_workspace) clones them
side by side. It also runs a real Home Assistant on `http://localhost:8123` with
this integration's source mounted live.

1. Clone the hub next to this repository. Its
   [README](https://github.com/Venosta-web/growspace_manager_workspace#readme) covers
   setup and the dev loop.
2. Read the hub's [`AGENTS.md`](https://github.com/Venosta-web/growspace_manager_workspace/blob/main/AGENTS.md)
   for the runtime commands, validation levels and cross-repository rules.
3. Read this repository's [`AGENTS.md`](AGENTS.md). It is the authority for this
   repository: base branches, merge gates and patch coverage. The domain vocabulary
   lives in [`CONTEXT.md`](CONTEXT.md), and design decisions in [`docs/adr/`](docs/adr).

## Work in a worktree

Every change goes on its own branch in its own worktree, never in the main
checkout. A pre-commit guard rejects commits there.

```bash
git fetch origin
git worktree add .worktrees/<branch-name> -b <branch-name> origin/prerelease
cd .worktrees/<branch-name>
```

The pre-commit hooks use the worktree's own `.venv` when it has one, and the
main checkout's otherwise. For a change that also
touches the card, run `./scripts/feature new <name>` from the hub instead. It
creates a matched pair of worktrees with the same branch in both repositories.

Integration work targets **`prerelease`**. Open your pull request against it.

## Check before you push

From the hub:

```bash
./scripts/check backend fast   # ruff, mypy and the test suite
./scripts/check backend full   # the same, with coverage
```

`check` prints which checkout it is validating before it starts. From a worktree,
set `GROWSPACE_BACKEND` to your worktree path so it checks your branch instead of
the main checkout.

CI additionally runs hassfest and HACS validation. It also runs Codecov's patch
check, so every line you add needs a test that runs it.
[`AGENTS.md`](AGENTS.md) shows how to measure that locally.

## Pull requests

- Write commit messages and PR titles as
  [Conventional Commits](https://www.conventionalcommits.org/), for example
  `fix(irrigation): …` or `feat(labels): …`.
- Say which issue the PR closes, and how you verified it on a running Home Assistant.
- A change to a service or WebSocket payload is one feature across two repositories.
  The integration lands first, then the card. See the hub's
  [`docs/CONTRACT.md`](https://github.com/Venosta-web/growspace_manager_workspace/blob/main/docs/CONTRACT.md).

By contributing you agree that your work is licensed under this repository's
[MIT License](LICENSE).
