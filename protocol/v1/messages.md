# VLN-AVP IPC v1 - message contract

All fields below are **adapter-level protocol fields**. They are named to
mirror the Agent-Kernel integration types that the future Kernel-backed host
will use (see the mapping table), but they are **not** existing Agent-Kernel
JSON types, and this protocol does not by itself prove any Kernel behavior.

## 1. Request

Exactly one request object per line.

| Field | Type | Required | Notes |
|---|---|---|---|
| `protocol_version` | string | yes | Must equal `"1"`. |
| `request_id` | string | yes | 1-128 characters, non-blank. Correlation identity only. |
| `type` | string | yes | `"submit"` is the only supported type in v1. |
| `capability_id` | string | yes | Non-blank capability name. |
| `payload` | string | yes | Non-blank string; opaque to the protocol. |

Example:

```json
{"protocol_version":"1","request_id":"test-0001","type":"submit","capability_id":"test.echo","payload":"{\"text\":\"hello\"}"}
```

### Field mapping to the Kernel integration types

| Protocol field | Kernel integration type (future host) |
|---|---|
| `request_id` | `ak::agent::RuntimeRequestId` / `RuntimeInvocationRequest::request_id` |
| `capability_id` | `RuntimeInvocationRequest::capability_id` -> `TaskExecutionDescriptor::capability.name` |
| `payload` | `RuntimeInvocationRequest::payload` -> `TaskExecutionDescriptor::payload` |
| `type` | **New** adapter-level field (no Kernel equivalent) |
| `protocol_version` | **New** adapter-level field (distinct from the K0 contract version) |

The Kernel additionally requires `capability_id` and `payload` to be
non-blank; v1 enforces the same at the envelope boundary.

## 2. Response

Exactly one response object per request line, always emitted, always terminal.

| Field | Type | Notes |
|---|---|---|
| `protocol_version` | string | Always `"1"`. |
| `request_id` | string or null | Echoed when recoverable; `null` when the request was too malformed to identify. |
| `host_kind` | string | `"stub"` or `"kernel"`. |
| `accepted` | boolean | Whether the submission was accepted for execution. |
| `submission_status` | string or null | `"completed"`, `"rejected"`, `"failed"`, or null. |
| `observation_status` | string or null | `"success"`, `"failure"`, or null. |
| `execution_status` | string or null | Kernel execution status string when available; always `null` for the stub. |
| `output` | string or null | Present only for a terminal success. |
| `error` | object or null | `{"code": string, "message": string}` when the request failed at any layer. |

Success example:

```json
{"protocol_version":"1","request_id":"test-0001","host_kind":"stub","accepted":true,"submission_status":"completed","observation_status":"success","execution_status":null,"output":"[stub-echo]:{\"text\":\"hello\"}","error":null}
```

Rejection example (unknown protocol version):

```json
{"protocol_version":"1","request_id":null,"host_kind":"stub","accepted":false,"submission_status":null,"observation_status":null,"execution_status":null,"output":null,"error":{"code":"unsupported-version","message":"unsupported protocol_version: '2'"}}
```

Accepted-then-failed example (unknown capability):

```json
{"protocol_version":"1","request_id":"test-0002","host_kind":"stub","accepted":true,"submission_status":"failed","observation_status":"failure","execution_status":null,"output":null,"error":{"code":"capability-not-found","message":"stub host has no capability: 'nav.go'"}}
```

## 3. Error codes

| Code | Layer | Meaning |
|---|---|---|
| `malformed-json` | envelope | The line is not valid JSON (or not valid UTF-8). |
| `oversize-line` | envelope | The encoded request line exceeds 64 KiB. |
| `missing-field` | envelope | A required field is absent. |
| `invalid-field` | envelope | A field has the wrong type or is blank/invalid. |
| `unsupported-version` | envelope | `protocol_version` is not `"1"`. |
| `unsupported-type` | envelope | `type` is not a supported message type. |
| `invalid-request-id` | envelope | `request_id` is too long or blank. |
| `payload-too-large` | envelope | `payload` exceeds 1 MiB. |
| `capability-not-found` | execution | The host has no such capability (accepted, then failed). |
| `capability-invocation-failed` | execution | The capability ran and failed. |
| `internal-error` | host | An unexpected host-side failure. |
| `invalid-response` | client | Client-side: the host returned a non-v1 response envelope. |

## 4. Guarantees and non-guarantees

- Malformed input is rejected at the envelope boundary and never reaches an
  execution path.
- Each valid request yields exactly one terminal response in v1; there is no
  `pending` status.
- `request_id` is not an idempotency key. No deduplication or exactly-once
  guarantee exists.
