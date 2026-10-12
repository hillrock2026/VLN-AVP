# AGENTS.md — working agreement for VLN-AVP

This repository is the Intelligence-side VLN-AVP pipeline layered on the
independently maintained **Agent-Kernel**. Automated agents must follow the
rules below.

## Absolute constraints

- Do **not** run `git reset --hard`, `git clean`, `git push --force`, or any
  history rewrite.
- Do **not** clean, reset, overwrite, delete, commit, or push the
  `Agent-Kernel/` work tree. It contains separately maintained, uncommitted
  work. Treat it as read-only unless a human explicitly authorizes a change.
- Do **not** commit or push this repository without explicit authorization.
- Do **not** fabricate model inference results, test results, repository state,
  or interfaces. Every claim must be grounded in a file you actually read or a
  command you actually ran.
- Never present single-executor experimental results as production safety
  certification.

## Method

- Inspect the current state before modifying anything.
- Implement in phases; report the result of each phase and wait for
  confirmation before starting the next.
- Prefer verifiable functionality over resolving every known K0 concurrency
  issue first; record known concurrency/lifecycle risks instead.

## Layout

| Path | Purpose |
|---|---|
| `src/vln/` | VLN-AVP Python package (Intelligence side). |
| `tests/vln/` | Tests for `src/vln`. |
| `configs/` | Configuration. |
| `docs/` | Public architecture and project documentation. |
| `Agent-Kernel/` | Optional independent local checkout; not tracked by this repository. |

## Build and test

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

The Kernel is built by its own project, not by this repository.
