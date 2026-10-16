# Changelog

All notable changes to the Agent Kernel project are recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-07-08

### Added

- **P0-01 Project Bootstrap:** Initial project skeleton with CMake build system, C++20 configuration, directory structure, `.clang-format`, `.clang-tidy`, `.gitignore`
- **P0-02 Engineering Standards:** Complete 20-chapter engineering standards document at `standards/EngineeringStandards.md`
- **P0-03 AI Engineering Kit:** 32 reusable prompt templates in 8 categories under `prompt/`, prompt template specification at `templates/prompt/PromptTemplateSpec.md`

### Changed

- **CR-0001 Resolution:** Corrected build graph wiring (target export, install, package configuration); simplified version metadata (removed Version struct, namespace globals, AK_VERSION_STR macro); replaced CI workflow files with pure placeholders; fixed README Markdown formatting

### Fixed

- Root CMake missing `add_subdirectory(src)` — library target now properly wired into build graph
- `src/CMakeLists.txt` broken generator expressions — corrected BUILD_INTERFACE and INSTALL_INTERFACE paths
- `cmake/Config.cmake.in` variable interpolation — fixed @PACKAGE_INIT@ placement, include path, package prefix resolution
- README.md corrupted Markdown — repaired backtick code fences, normalized whitespace, directory paths in backticks

### Removed

- Temporary Phase prompt `.txt` files from `prompt/` directory
- `include/ak/version.hpp`: `Version` struct, `ak::current_version` global variable, `AK_VERSION_STR` macro
- All executable CI workflow logic (replaced with comment-only placeholders)

### Security

- No runtime code exists in Phase 0 — no security considerations apply

### Known Issues

- INTERFACE library target — no compiled artifact produced until Phase 1
- No test framework linked — tests cannot execute until Phase 1
- CMake status messages show concatenated multi-byte text (cosmetic)

[0.1.0]: https://github.com/agent-kernel/agent-kernel/releases/tag/v0.1.0
