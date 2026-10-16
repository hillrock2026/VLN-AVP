# Documentation Index

This index classifies the repository's documentation by status so a contributor can
immediately find the current authoritative information versus historical or superseded
records.

Status tags used below:

- **current** — governs work right now.
- **verified** — reflects a reproduced build/test result.
- **superseded** — replaced by a newer document.
- **historical** — retained as record; no longer governs.
- **reserved** — placeholder for a future phase; not active.

---

## 1. Current / Authority

| Document | Status |
|---|---|
| `../Agent-Kernel-Production-Readiness-Development-Program-Plan.md` | current (program baseline) |
| `../README.md` | current (verified build state) |
| `../Current-Repository-Map.md` | current / verified |
| `../B0-01-Owner-Decision-Packet.md` | current (Owner decisions) |
| `architecture/AK00*` (e.g. `AK0011` … `AK0030`) | current (closed authority specs) |

## 2. Engineering Baseline Evidence (Workstream B)

| Document | Status |
|---|---|
| `../B0-01-Repository-Baseline-Classification-and-Initial-Commit-Scope.md` | verified (baseline classification) |
| `../B1-01-Root-CMake-Reconstruction-and-Testable-Repair-Plan.md` | verified (reviewed plan) |
| `../B1-02-Implementation-Report.md` | verified (CMake/.gitignore repair) |
| `../B2-01-Ubuntu-Toolchain-Preparation.md` | verified (toolchain assessment) |
| `../B2-02-Ubuntu-Toolchain-Installation-and-Verification.md` | verified (install + verify) |
| `../B3-01-Clean-GCC-Build-and-Full-CTest-Baseline.md` | verified (baseline run) |
| `../B3-01-Correction-Report.md` | verified (baseline repair, 36/36 green) |
| `../B3-02-Ubuntu-CI-Baseline.md` | verified (CI workflow) |

Independent review reports for the above (`B0-01-*`, `B1-01-*`, `B1-02-*`, `B2-*`, `B3-01-*`,
`B3-02-*` review reports at the repo root) are **review/evidence** records.

## 3. Architecture & Planning

| Document | Status |
|---|---|
| `architecture/` (AK00xx specs, P0R0006) | current (closed authority) |
| `project/Baseline-v0.1.md` | **superseded** (historical Phase-0 bootstrap baseline; superseded by the current engineering baseline) |

## 4. Historical / Superseded

| Group | Status |
|---|---|
| `../Agent Runtime Integration — TASK 1` … `TASK 3.5` reports/reviews | historical (runtime-integration work) |
| `../P1-IS*` implementation and review reports | historical (Phase-1 subsystem implementation) |
| `../PHASE-*` / `../TASK-*` (First Working Agent) | historical (FWA sprint) |
| `../Production Model Provider Integration — *` | mixed — see §5 |
| `../*_reference.txt` | historical (reference material, large) |
| `../FWA-Evidence-Digest.md`, `../AK0039-*`, `../AK0044*`, `../AK0046-*` | historical (archival audits / reconciliation) |

## 5. Provider Governance (Workstream P) — status note

The active provider governance documents are the most recent S0 chain
(`Production Model Provider Integration — S0-R-001 Governance Resolution Decision.md`,
`Production Model Provider Integration — Owner Authorization S0 Re-baselining.md`, and the
`TASK 3-S0 Rev1.3` discovery/assessment). Earlier `TASK 1`/`TASK 2`/`SC-08` provider documents
are **historical**. Workstream P implementation has **not** started.

## 6. Reserved (future phases)

| Path | Status |
|---|---|
| `docs/api/`, `docs/rfc/`, `docs/coding-standard/`, `docs/developer-guide/`, `docs/review-guide/` | reserved |
| `../.github/workflows/test.yml`, `review.yml`, `release.yml` | reserved / not active (see `../.github/README.md`) |

---

For build/test commands and the verified baseline result, see the root `README.md`.
