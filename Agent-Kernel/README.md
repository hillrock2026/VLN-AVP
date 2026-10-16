# Agent Kernel

**Modular runtime for AI Agents.**

---

## Status

The repository is in the **Engineering Baseline** stage (Workstream B: repository engineering
baseline).

- Root CMake and repository hygiene repaired and reviewed (B1).
- Ubuntu toolchain established and verified (B2).
- Clean GCC build/test baseline is **green**: **36/36 tests pass** (B3-01, corrected and
  re-verified).
- Ubuntu CI workflow configured (`build.yml`); the local command path is verified and the
  first GitHub run is pending (B3-02).

Primary engineering baseline: **Ubuntu 24.04 + GCC 13.3.0 + CMake 3.28.3 + GTest 1.14.0**.

---

## Build

### Requirements

| Dependency | Purpose |
|---|---|
| CMake >= 3.22 | build system |
| GCC 13 (g++ 13.3.0) | C++20 compiler |
| GTest (`libgtest-dev`) | test framework |

### Install dependencies

```bash
sudo apt-get update
sudo apt-get install -y cmake build-essential libgtest-dev
```

### Configure, build, test

```bash
cmake -S . -B build -DAK_BUILD_TESTS=ON -DAK_BUILD_EXAMPLES=OFF -DAK_BUILD_PROTOTYPE=OFF -DCMAKE_BUILD_TYPE=Debug
cmake --build build -j
ctest --test-dir build --output-on-failure
```

Verified result: `100% tests passed, 0 tests failed out of 36`.

### Options

| Option | Default | Description |
|---|---|---|
| `AK_BUILD_TESTS` | ON | Build unit and integration tests (requires GTest) |
| `AK_BUILD_EXAMPLES` | ON | Build example programs |
| `AK_BUILD_PROTOTYPE` | ON | Build the archival AVP0000/AVP0001 prototypes |
| `AK_ENABLE_INSTALL` | OFF | Generate install and export targets (minimal `agent_kernel` + `agent_kernel_foundation` package) |

> The archival AVP0000/AVP0001 prototypes do not compile on Ubuntu (a pre-existing prototype
> source include-path defect, recorded as residual R-001 in B1-02). The verified baseline sets
> `-DAK_BUILD_PROTOTYPE=OFF`; the prototypes remain present but are excluded from the default
> green build path.

Warnings are treated as errors (`-Wall -Wextra -Wpedantic -Werror` on GCC/Clang; `/W4 /WX`
on MSVC).

---

## Directory Layout

| Directory | Purpose |
|---|---|
| `include/` | Public headers under the `ak/` / `agent_kernel/` namespaces |
| `src/` | Library sources (kernel model, agent, planner, prompt, model, tool, memory, context, foundation, runtime integration compositions) |
| `runtime/` | C Runtime (scheduler, executor, resolver, event bus, lifecycle) |
| `tests/` | Unit, integration, and boundary-check test suites (CTest + GTest) |
| `examples/` | Example programs |
| `docs/` | Architecture, project, and documentation index (see `docs/README.md`) |
| `prototype/` | Archival AVP0000/AVP0001 architecture-validation prototypes |
| `cmake/` | CMake package-config template |
| `third_party/` | Third-party dependencies |
| `.github/` | CI/CD workflow definitions (see `.github/README.md`) |

---

## Documentation

See `docs/README.md` for the classified documentation index (current authority vs. historical
vs. superseded).

---

## Roadmap

The program plan (`Agent-Kernel-Production-Readiness-Development-Program-Plan.md`) defines the
current workstreams. After Workstream B (engineering baseline) is closed, the next workstreams
are:

- **Workstream P** — Production Model Provider.
- **Workstream R** — Runtime Multi-Invocation.
- **Workstream C** — Production Composition.

No provider/backend implementation or runtime multi-invocation work begins before Workstream B
is closed.

---

## License

TBD
