# YAML style

The repository's YAML policy lives in [`.yamllint`](../.yamllint). Run the same
all-files check used by CI with:

```bash
pre-commit run yamllint --all-files
```

First-party YAML uses an explicit `---` document start and a maximum line length
of 120 characters. Inline comments have at least two spaces before `#` and one
space after it. These rules apply to Home Assistant service and quality-scale
metadata, test configuration, Docker Compose, and GitHub Actions workflows.

GitHub Actions' `on` key must be quoted as `"on"`. YAML 1.1 parsers otherwise
interpret that key as a boolean even though GitHub's workflow syntax treats it
as a string.

Nothing is excluded: test fixtures and integration metadata are linted too.
Third-party agent skills, whose installer-owned manifests would not pass, are
gitignored rather than committed, so the tracked-file hook never sees them.
