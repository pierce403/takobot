---
summary: "Feature release checklist for Takobot"
read_when:
  - You added a feature and need to release
title: "Release Process"
---

# Release Process

Takobot follows feature-first release discipline.

## Required sequence

1. Implement feature + tests.
2. Update docs and website:
   - `README.md`
   - `FEATURES.md`
   - `index.html`
   - `docs/**` when relevant
3. Bump version:
   - `pyproject.toml`
   - `takobot/__init__.py`
4. Commit and push to `main`.
5. Tag release: `vX.Y.Z`.
6. Push tag.
7. Verify GitHub publish workflow success.
8. Verify PyPI shows the new version.

## Validation baseline

- Run focused tests for changed modules.
- Run full test suite before tagging.
- Ensure `git status` is clean after push/tag.
