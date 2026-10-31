# Superseded CAP-08A Mission draft

This directory contains the removed CAP-08A Mission core, the CAP-08C-01
Mission wrapper draft and its test/report. They are kept only as historical
material for audit.

**They are not part of the active source tree, build, imports or development
plan.** The current architecture is Session-centric; see
`docs/ARCHITECTURE-DECISION-SESSION-CENTRIC.md`.

Do not restore or extend these files. The active driver is
`scripts/carla_cap08c01_session_parking.py`, and parking-domain progress is
stored in the Agent-Kernel Context under `domain.parking`.
