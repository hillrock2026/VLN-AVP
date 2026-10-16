# CI/CD Workflows

| Workflow | Status | Trigger | Purpose |
|----------|--------|---------|---------|
| `build.yml` | **active** | `push`, `pull_request` | Ubuntu GCC configure, build, and CTest (36/36 baseline) |
| `test.yml` | reserved (not active) | — | future dedicated test matrix |
| `review.yml` | reserved (not active) | — | future automated code review |
| `release.yml` | reserved (not active) | — | future release automation |

`build.yml` is the current executable CI workflow; it installs `cmake build-essential
libgtest-dev`, then runs configure/build/`ctest` on `ubuntu-24.04`, matching the verified
local GCC baseline. The other three workflow files are reserved placeholders and are **not**
active CI.
