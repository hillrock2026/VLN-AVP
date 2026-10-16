# Agent-Kernel snapshot provenance

`Agent-Kernel/` in this repository is a **plain source snapshot**, not a nested
Git repository and not a submodule/subtree. It contains no `.git` directory, so
every Kernel file is an ordinary trackable file of VLN-AVP.

## Pinned source

| Field | Value |
|---|---|
| Upstream repository | `https://github.com/hillrock2026/Agent-Kernel.git` |
| Upstream branch | `main` |
| **Published baseline (export base)** | `dcd1341d768cacd50af640fb47ab627dbf3e1f5e` (also `curated-baseline`) |
| **Local patch target (effective content)** | `a1ea295f0b6da95ccd9140ac7433d8d3bde9b5a2` — **local commit, NOT published upstream** (see below) |
| Export tool | `git archive --format=tar <sha> \| tar -x` (committed tree only) |
| Base exported on | 2026-10-12 |
| Local patch applied on | 2026-10-12 (M1-02A) |
| Excluded | `.git/`, build directories, logs and any untracked/working-tree-only file |
| File count | 438 tracked files at the base; **440** after the local patch |

## Update rules

1. Never edit this snapshot by copying another clone's working tree. Re-export
   from the pinned commit with `git archive` (see the export tool above).
2. Re-pin by changing the baseline commit above and re-exporting; record the new
   commit and date here.
3. VLN-AVP-specific Kernel changes belong to **VLN-AVP** and live in this
   snapshot. They must **not** be pushed to the upstream Agent-Kernel repository.
4. The separate clone at `../Agent-Kernel` keeps its own Git history for other
   development tasks. VLN-AVP must not write to, commit to, or clean that clone,
   and must not push to the upstream Agent-Kernel remote.

## Local patch: runtime execution authority factory (M1-02A, 2026-10-12)

`runtime_host/CMakeLists.txt` (line 41) requires the Kernel to expose
`include/agent_kernel/runtime_integration/runtime_execution_authority.hpp`, and
`runtime_host/README.md` documents the required baseline as
`a1ea295f0b6da95ccd9140ac7433d8d3bde9b5a2`. That commit is **one commit ahead of
the published upstream `dcd1341d` and is NOT published to the upstream
Agent-Kernel remote**. To unblock the real `kernel_host` build, the change was
applied to this snapshot as a local patch on top of the published base.

| Field | Value |
|---|---|
| Patch | `archive/vln-avp-m1-00/patches/0001-feat-kernel-add-runtime-execution-authority-factory.patch` (relative to `Agentic_Program/`; absolute `/home/gaosong/Agentic_Program/archive/vln-avp-m1-00/patches/0001-feat-kernel-add-runtime-execution-authority-factory.patch`) |
| Patch SHA-256 | `a1c218dab4379df10936adcb37af909081f854c4d6a24606813f05a953d52ccb` |
| Base → target | `dcd1341d768cacd50af640fb47ab627dbf3e1f5e` → `a1ea295f0b6da95ccd9140ac7433d8d3bde9b5a2` |
| Total diff | +345 / −0 lines, 4 files, no deletions or renames |

Changed files and their post-patch git blob SHAs (content identity):

| Status | File | Blob SHA (after) |
|---|---|---|
| added | `include/agent_kernel/runtime_integration/runtime_execution_authority.hpp` | `bd8ad04e492667d89389348f3641f48f6fb315ef` |
| modified | `src/runtime_integration/runtime_public_api_adapter.cpp` | `9d106f8d02eda2eed436cf120ba6a3f89567082a` |
| modified | `tests/runtime_integration/CMakeLists.txt` | `566b8fe6a44f51473073d8629bd824231c5e477e` |
| added | `tests/runtime_integration/k0_execution_authority_factory_test.cpp` | `209d96e08e77de4823b450bc47a5d5b732f16289` |

Pre-patch blob SHAs (the base, for comparison):
`src/runtime_integration/runtime_public_api_adapter.cpp` =
`1e23af744a789fa87861c1dd38a57c9a4c8d39d5`;
`tests/runtime_integration/CMakeLists.txt` =
`070ff36fecbb7dd89ac2578891040b4af4b427d8`.

### How it was applied and verified

1. Verified both pre-image files against the published base
   (`git hash-object <file>` == the base blob SHA above).
2. Dry-ran the patch in place (`patch -p1 --dry-run`), then applied it with
   `patch -p1 --no-backup-if-mismatch` from `Agent-Kernel/`.
3. Verified each changed file's blob SHA with `git hash-object` against the
   `a1ea295f` values above (all 4 match), and that the other files are
   byte-identical to `dcd1341d`. The snapshot content set equals `a1ea295f`
   exactly (440/440 files).
4. **Do not push** this change to the upstream Agent-Kernel remote. The
   `a1ea295f` commit remains unpublished; this snapshot intentionally diverges
   from the published base until that commit is published upstream and the pin
   above is advanced.

### Backup and rollback

- Pre-patch copies (the two modified files) are archived at
  `/home/gaosong/Agentic_Program/m1-02a-backup/pre-patch/`:
  - `src/runtime_integration/runtime_public_api_adapter.cpp`
    (sha256 `e68950695be917cf8215b33e1ad36b63f8ba77303357bd065dee2e9ebc107c2c`)
  - `tests/runtime_integration/CMakeLists.txt`
    (sha256 `3bbcb8c03305cf4d4394d189d08bf63b0594474653310ff1a01ecc7aae9ec67c`)
- Rollback: restore those two files from the backup directory, and delete the
  two added files (`include/agent_kernel/runtime_integration/runtime_execution_authority.hpp`
  and `tests/runtime_integration/k0_execution_authority_factory_test.cpp`);
  alternatively re-export the snapshot from the base `dcd1341d` with
  `git archive` (see Update rules).
- Build output for this task lives **outside** the source tree at
  `/home/gaosong/Agentic_Program/m1-02a-build/` (not committed, not tracked).
