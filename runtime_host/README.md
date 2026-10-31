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

### Scope of this host

- Executes the test-domain capability `test.echo` and the `parking.move`
  capability declared by `AgentIntent` v1.
- `parking.move` is simulation-only by default: it validates the intent and
  echoes it as `stub_completed`. With the optional CARLA execution bridge
  below it executes a real CARLA segment and returns the measured pre/post
  vehicle state.
- The host does NOT bypass authorization: it obtains its port only through
  `IssueRuntimeExecutionAuthority`. It never constructs
  `RuntimePublicApiAdapter` directly.
- No `NAVIGATE_TO`, robot, model or other hardware capability exists. The
  model, route arbitration and safety gate remain outside the Kernel.
- This is a minimal integration. It is NOT evidence that the K0 gate is
  closed, that arbitrary consumers can no longer bypass authorization, or
  that anything is production-safe.

### Optional CARLA execution bridge (M1-VLN-CARLA-02)

The C++ host cannot import the CARLA Python API. When real CARLA execution is
required, the host is started with a loopback execution bridge:

| Variable | Meaning |
|---|---|
| `VLN_CARLA_EXEC_BRIDGE` | `host:port` of the CARLA execution bridge (`127.0.0.1:<ephemeral>`). |
| `VLN_CARLA_EXEC_TOKEN` | Required non-blank bridge token. Never logged. |
| `VLN_CARLA_EXEC_TIMEOUT_MS` | Per-execution timeout, default `180000`, max `600000`. |

With the bridge configured, the registered `parking.move` invoker calls the
bridge synchronously and returns only after the CARLA controller has stopped
the vehicle and the real post-execution state was read. The response is output
v2 (`execution_mode="carla"`) and the host recomputes `moved_m` from the real
pre/post states. Without the bridge, the original simulation-only stub is used
unchanged. An invalid bridge configuration makes the host exit with code `3`
instead of silently falling back to the stub.

The bridge is an execution transport, not an authorization bypass: the host
still reaches the invoker only through `IssueRuntimeExecutionAuthority` →
`Port().Submit/Observe` → `Runtime::Run`. The bridge additionally requires a
token and a single-use, round-scoped execution permit. The POSIX build is
supported; a Windows host build returns a deterministic failure if a bridge is
configured.

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
