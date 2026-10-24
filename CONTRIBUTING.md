# Contributing

## Commit convention

Commits follow the Angular convention. The `release` workflow reads them on every push to `main` and tags the next semantic version.

| Prefix | Bump | Example |
|---|---|---|
| `fix:` · `perf:` | patch | `fix: handle an empty claim list` |
| `feat:` | minor | `feat: add a judge route` |
| `feat!:` or a `BREAKING CHANGE:` footer | major | `feat!: drop the v1 API` |
| `docs:` `chore:` `test:` `refactor:` `style:` `ci:` | none | — |

Before opening a PR run `make ci` (lint, types, offline tests with the coverage gate, audits, build).
