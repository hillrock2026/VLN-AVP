# runtime_host/

The host process that owns the execution boundary between the Python
Intelligence side (VLN-AVP) and the C++ Agent-Kernel runtime. Two hosts live
here; they are deliberately different and must not be confused:

| Host | File | `host_kind` | Executes Agent-Kernel? |
|------|------|-------------|------------------------|
| Real Kernel host | `kernel_host.cpp` (C++20) | `"kernel"` | **Yes** - real `Runtime` + `test.echo` |
| Test-only stub | `stub_host.py` (Python) | `"stub"` | No - protocol/process tests only |

Both speak the same contract (`protocol/v1`, `src/vln/ipc/envelope.py`) and
both are driven by the same Python `HostClient`.

## Real Kernel host (`kernel_host.cpp`, Phase 3B-3B)

The real host owns an `ak::runtime::Runtime` and executes each valid IPC v1
request through the sanctioned authorization path:

```
IssueRuntimeExecutionAuthority(Runtime&)
  -> RuntimeExecutionAuthorityHandle::Port()
  -> RuntimeInteractionPort::Submit / Observe
  -> Runtime::Run -> capability invoker -> ak::ExecutionResult
```

It emits `"host_kind": "kernel"` and a real `execution_status` derived from
the Kernel's own `ak::ExecutionResult`, not a fabricated value.

### Scope of this first loop

- Executes **only** the test-domain capability `test.echo`, which returns
  `"[kernel-echo]:" + payload` after passing through the Runtime's
  capability-registration, submission and observation path.
- The host does NOT bypass authorization: it obtains its port only through
  `IssueRuntimeExecutionAuthority`. It never constructs
  `RuntimePublicApiAdapter` directly.
- No navigation, `NAVIGATE_TO`, robot, model or hardware capability exists.
- This proves the **first real Kernel integration loop only**. It is NOT
  evidence that the K0 gate is closed, that arbitrary consumers can no longer
  bypass authorization, or that anything is production-safe.

### Known limits (do not overstate)

- `Runtime` has a one-shot lifecycle, so the host creates a **new Runtime per
  request**, is single-threaded, and handles **one request at a time**.
- No concurrency, cancellation, timeout, deduplication, retry or
  exactly-once guarantee is provided. A `request_id` is not an idempotency
  key.
- The authorization handle makes the factory the *intended* integration path;
  it is not a universal type-level boundary (`RuntimePublicApiAdapter` still
  has a public constructor and `Runtime::Run` remains publicly reachable).
- Capability permission/resource constraints are not yet comprehensively
  enforced by the Kernel.

### Building

The build consumes a **clean** Agent-Kernel source tree via
`git archive <sha>` (never the dirty working tree), and a JSON library. This
CMake file hardcodes no machine path; both inputs are supplied by the caller:

```
cmake -S runtime_host -B <build-dir> -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DAGENT_KERNEL_SOURCE_DIR=<clean-agent-kernel-tree> \
  -DNLOHMANN_JSON_INCLUDE_DIR=<dir-containing/nlohmann/json.hpp>
cmake --build <build-dir> --target kernel_host
```

- `AGENT_KERNEL_SOURCE_DIR` must expose
  `include/agent_kernel/runtime_integration/runtime_execution_authority.hpp`
  (baseline `a1ea295f0b6da95ccd9140ac7433d8d3bde9b5a2`, obtained with
  `git archive`).
- `NLOHMANN_JSON_INCLUDE_DIR` must contain `<nlohmann/json.hpp>`
  (nlohmann/json, MIT). No new third-party dependency is added by VLN-AVP.
- Build requirements: C++20 compiler, CMake >= 3.22, Ninja. On MSVC the host
  is compiled with `/W4 /WX /utf-8`. Build artifacts must stay **outside**
  both repositories; the Kernel is added with `EXCLUDE_FROM_ALL` and only the
  `kernel_host` target is built.
- Only these existing Kernel targets are linked:
  `agent_kernel_runtime_integration`, `agent_kernel_runtime`, `agent_kernel`.

The host reads one NDJSON request per line on stdin and writes one NDJSON
response line per request to stdout. **stdout carries protocol responses
only**; all diagnostics go to stderr (`kernel-host: ...`).

### Running the Kernel-host tests

The compiled executable is a machine-specific, out-of-repo artifact, so the
integration tests locate it through an environment variable and skip when it
is absent:

```bash
set VLN_KERNEL_HOST_EXE=<build-dir>\kernel_host.exe
python -m pytest tests/integration/test_kernel_host.py -v
```

## Test-only stub (`stub_host.py`, Phase 3B-1)

`stub_host.py` remains a **TEST-ONLY STUB** and is intentionally kept:

- It does NOT load, construct or invoke Agent-Kernel.
- It identifies itself with `"host_kind": "stub"` and leaves
  `execution_status` null.
- It implements the same single `test.echo` behavior
  (`"[stub-echo]:" + payload`) purely for protocol/process testing.

A passing stub-host test proves the **protocol, client and process behavior**
only; it is not evidence of Kernel integration. It must never be represented
as real Kernel execution.

```bash
python runtime_host/stub_host.py
```

## Contract

See `protocol/README.md` and `protocol/v1/messages.md` for the wire contract.
`src/vln/ipc/envelope.py` is the single source of truth for envelope rules;
the C++ host mirrors its constants, error codes and validation order.
