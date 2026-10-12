# VLN-AVP IPC protocol

The versioned wire contract between the Python Intelligence side (VLN-AVP)
and a host process that owns the execution boundary.

## Transport

- **Framing:** newline-delimited JSON (NDJSON). One compact JSON object per
  line, terminated by `\n`.
- **Channels:** requests and responses travel on the host's **stdin** and
  **stdout**. Diagnostics travel on the host's **stderr** only. A line on
  stdout that is not a valid v1 response envelope is a protocol violation.
- **Encoding:** UTF-8, no BOM.

## Model

- The host is a **long-lived process**.
- **Exactly one request is handled at a time**; there is no concurrent
  request handling in v1.
- The protocol is **synchronous**: one valid request produces exactly one
  **terminal** response line, in order. There is no `pending` state.

## Versioning

- The current version is `"1"` (`"protocol_version": "1"`).
- Both request and response always carry `protocol_version`.
- A request with an unknown version is rejected with `unsupported-version`.
- A version is required in every message; a missing field is `missing-field`.

## Contract documents

- Field-level contract and error semantics: [`v1/messages.md`](v1/messages.md).
- Machine-readable envelope: [`v1/envelope.schema.json`](v1/envelope.schema.json).

## Limits (v1, proposed)

| Limit | Value |
|---|---|
| Maximum encoded request line | 64 KiB (65536 bytes, excluding `\n`) |
| Maximum `request_id` length | 128 characters |
| Maximum `payload` length | 1 MiB (1,048,576 bytes) |
| Requests in flight | 1 |

These are **new protocol-level limits**, not Agent-Kernel limits. In v1 the
1 MiB payload cap is in practice also bounded by the 64 KiB line cap.

## Error semantics (summary)

Every response carries a `status`-like pair plus an optional structured
`error` object (`{"code", "message"}`). The distinction between categories:

- **Malformed IPC** (invalid JSON, missing/invalid fields, oversized line,
  unknown version, unknown type): rejected by the host **before** any
  execution path is touched.
- **Valid but rejected submission:** `"submission_status": "rejected"`.
- **Accepted submission:** `"accepted": true`.
- **Execution failure:** `"submission_status": "failed"` and/or
  `"observation_status": "failure"`.
- **Terminal success:** `"submission_status": "completed"` and
  `"observation_status": "success"`.

## Host identity

Every response carries `host_kind`:

- `"stub"` - the test-only stub host (`runtime_host/stub_host.py`). It never
  performs Kernel execution and always reports `execution_status: null`.
- `"kernel"` - a host backed by the real Agent-Kernel runtime (Phase 3B-2+).

## Non-guarantees

`request_id` is a correlation identity. It does **not** provide
deduplication, idempotency, or exactly-once execution. Sending the same
`request_id` twice is not defined to be safe in v1.
