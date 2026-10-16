// ============================================================
// kernel_host.cpp - real Agent-Kernel-backed NDJSON host (VLN-AVP IPC v1)
// ============================================================
// This is the REAL host: it owns an Agent-Kernel Runtime and executes each
// valid IPC request through the sanctioned authorization path:
//
//   IssueRuntimeExecutionAuthority(Runtime&)
//     -> RuntimeExecutionAuthorityHandle::Port()
//     -> RuntimeInteractionPort::Submit / Observe
//     -> Runtime::Run -> capability invoker -> ak::ExecutionResult
//
// Scope (deliberately minimal):
//   * Executes the test-domain capability "test.echo".
//   * Executes a SIMULATION-ONLY "parking.move" stub that validates the
//     AgentIntent v1 defensive subset and echoes the target; it controls no
//     vehicle and proves nothing about real parking.
//   * Defines NO navigation / robot / model capability.
//   * Reuses the existing protocol contract (protocol/v1); it does not
//     define a second, incompatible schema.
//
// stdout carries protocol responses ONLY. All diagnostics go to stderr.
//
// Known limits (do not overstate):
//   * Runtime has a one-shot lifecycle, so one Runtime is created per
//     request; this host is single-threaded and handles one request at a
//     time. No concurrency, cancellation, timeout, dedup, retry or
//     exactly-once guarantee is provided.
//   * The authorization handle makes the factory the intended integration
//     path; it is NOT a universal type-level boundary (RuntimePublicApiAdapter
//     still has a public constructor and Runtime::Run is publicly reachable).
// ============================================================

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif

#if defined(_MSC_VER)
#pragma warning(push)
#pragma warning(disable : 4127)  // conditional expression is constant
#pragma warning(disable : 4324)  // structure padded due to alignment
#pragma warning(disable : 4459)  // declaration hides global declaration
#pragma warning(disable : 4702)  // unreachable code
#pragma warning(disable : 4996)  // deprecated
#endif
#include <nlohmann/json.hpp>
#if defined(_MSC_VER)
#pragma warning(pop)
#endif

#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>
#include <agent_kernel/agent/runtime/runtime_observation.hpp>
#include <agent_kernel/agent/runtime/runtime_submission_result.hpp>
#include <agent_kernel/executor/execution_result.hpp>
#include <agent_kernel/runtime_integration/runtime_execution_authority.hpp>

#include <runtime.h>

namespace {

using nlohmann::ordered_json;

// ---- Protocol constants (MUST match src/vln/ipc/envelope.py) -------------
constexpr const char* kProtocolVersion = "1";
constexpr std::size_t kMaxRequestLineBytes = 64u * 1024u;
constexpr std::size_t kMaxRequestIdCodePoints = 128u;
constexpr std::size_t kMaxPayloadBytes = 1024u * 1024u;
constexpr std::size_t kOversizeDrainCap = 16u * 1024u * 1024u;

// ---- Stable error codes (MUST match envelope.ErrorCode) ------------------
constexpr const char* kErrMalformedJson = "malformed-json";
constexpr const char* kErrOversizeLine = "oversize-line";
constexpr const char* kErrMissingField = "missing-field";
constexpr const char* kErrInvalidField = "invalid-field";
constexpr const char* kErrUnsupportedVersion = "unsupported-version";
constexpr const char* kErrUnsupportedType = "unsupported-type";
constexpr const char* kErrInvalidRequestId = "invalid-request-id";
constexpr const char* kErrPayloadTooLarge = "payload-too-large";
constexpr const char* kErrCapabilityNotFound = "capability-not-found";
constexpr const char* kErrCapabilityInvocationFailed =
    "capability-invocation-failed";
constexpr const char* kErrInternalError = "internal-error";

constexpr const char* kHostKind = "kernel";
constexpr const char* kTestCapabilityId = "test.echo";
constexpr const char* kTestProviderId = "vln.test.host";
constexpr const char* kEchoPrefix = "[kernel-echo]:";

// ---- parking.move stub constants (M1-04B0 §3/§5, frozen v1) --------------
// The payload contract is AgentIntent v1 (src/vln/intent/agent_intent.py); the
// stub validates only the defensive subset S1-S8 (M1-04B0 §4.2), a strict
// subset of the Python-authoritative contract. This is a SIMULATION ONLY:
// "stub_completed" does not mean a real vehicle reached the target.
constexpr const char* kParkingCapabilityId = "parking.move";
constexpr const char* kParkingProviderId = "vln.parking.stub";
constexpr const char* kAgentIntentContractVersion = "1";
constexpr const char* kParkingOutputVersion = "1";
constexpr const char* kParkingStatusStubCompleted = "stub_completed";
constexpr const char* kParkingExecutionMode = "simulation";

void Log(const std::string& message) {
    std::cerr << "kernel-host: " << message << '\n';
    std::cerr.flush();
}

// ---- UTF-8 helpers -------------------------------------------------------
// Decodes the next UTF-8 code point; assumes well-formed UTF-8 (nlohmann
// rejects ill-formed UTF-8 while parsing).
std::uint32_t NextCodePoint(const std::string& text, std::size_t& index) noexcept {
    const auto c0 = static_cast<unsigned char>(text[index]);
    if (c0 < 0x80u) {
        ++index;
        return c0;
    }
    std::size_t extra = 0;
    std::uint32_t cp = 0;
    if ((c0 & 0xE0u) == 0xC0u) {
        extra = 1;
        cp = static_cast<std::uint32_t>(c0 & 0x1Fu);
    } else if ((c0 & 0xF0u) == 0xE0u) {
        extra = 2;
        cp = static_cast<std::uint32_t>(c0 & 0x0Fu);
    } else {
        extra = 3;
        cp = static_cast<std::uint32_t>(c0 & 0x07u);
    }
    for (std::size_t i = 0; i < extra; ++i) {
        if (index + 1 >= text.size()) {
            break;
        }
        ++index;
        cp = (cp << 6) | (static_cast<unsigned char>(text[index]) & 0x3Fu);
    }
    ++index;
    return cp;
}

std::size_t CountCodePoints(const std::string& text) noexcept {
    std::size_t count = 0;
    std::size_t i = 0;
    while (i < text.size()) {
        (void)NextCodePoint(text, i);
        ++count;
    }
    return count;
}

// Unicode White_Space, mirroring Python str.isspace() so that the host and
// the Python client agree on what "blank" means.
bool IsUnicodeSpace(std::uint32_t cp) noexcept {
    if (cp == 0x20u || (cp >= 0x09u && cp <= 0x0Du) ||
        (cp >= 0x1Cu && cp <= 0x1Fu)) {
        return true;
    }
    if (cp == 0x85u || cp == 0xA0u || cp == 0x1680u) {
        return true;
    }
    if (cp >= 0x2000u && cp <= 0x200Au) {
        return true;
    }
    if (cp == 0x2028u || cp == 0x2029u || cp == 0x202Fu || cp == 0x205Fu) {
        return true;
    }
    return cp == 0x3000u;
}

bool IsNonBlank(const std::string& text) noexcept {
    std::size_t i = 0;
    while (i < text.size()) {
        if (!IsUnicodeSpace(NextCodePoint(text, i))) {
            return true;
        }
    }
    return false;
}

// ---- parking.move stub (M1-04B0 §4.2 S1-S8, §5 output v1) -----------------
// The stub exists so the VLN-AVP chain can be exercised end to end without a
// real vehicle. Every rejection path throws, which the Executor turns into a
// deterministic invocation failure (no synthetic success is ever produced).
bool HasExactKeys(const ordered_json& obj,
                  std::initializer_list<const char*> keys) {
    if (!obj.is_object() || obj.size() != keys.size()) {
        return false;
    }
    for (const char* key : keys) {
        if (obj.find(key) == obj.end()) {
            return false;
        }
    }
    return true;
}

// S8: JSON number and finite. nlohmann reports bool/null/string as non-numbers,
// so `true`, `null` and `"1"` are rejected without an explicit type list.
bool IsFiniteJsonNumber(const ordered_json& value) {
    if (value.is_number_float()) {
        return std::isfinite(value.get<double>());
    }
    return value.is_number_integer();
}

std::string RunParkingMoveStub(const std::string& payload) {
    ordered_json intent;
    try {  // S1: payload is legal JSON
        intent = ordered_json::parse(payload);
    } catch (const ordered_json::exception&) {
        throw std::runtime_error("parking.move stub: payload is not valid JSON");
    }

    // S2: root is an object
    if (!intent.is_object()) {
        throw std::runtime_error("parking.move stub: payload must be an object");
    }
    // S3: exact top-level key set (fail-closed)
    if (!HasExactKeys(intent, {"contract_version", "intent_id", "action",
                               "target"})) {
        throw std::runtime_error(
            "parking.move stub: unexpected top-level field set");
    }
    // S4: contract_version is the string "1"
    if (!intent.at("contract_version").is_string() ||
        intent.at("contract_version").get<std::string>() !=
            kAgentIntentContractVersion) {
        throw std::runtime_error(
            "parking.move stub: unsupported contract_version");
    }
    // S5: action is "parking.move"
    if (!intent.at("action").is_string() ||
        intent.at("action").get<std::string>() != kParkingCapabilityId) {
        throw std::runtime_error("parking.move stub: unsupported action");
    }
    // S6: intent_id is a non-blank string (length authority stays in Python)
    const ordered_json& intent_id_node = intent.at("intent_id");
    if (!intent_id_node.is_string()) {
        throw std::runtime_error("parking.move stub: intent_id must be a string");
    }
    const std::string intent_id = intent_id_node.get<std::string>();
    if (!IsNonBlank(intent_id)) {
        throw std::runtime_error("parking.move stub: intent_id must be non-blank");
    }
    // S7: target is an object with exactly {x, y, heading}
    const ordered_json& target = intent.at("target");
    if (!HasExactKeys(target, {"x", "y", "heading"})) {
        throw std::runtime_error(
            "parking.move stub: unexpected target field set");
    }
    // S8: x, y, heading are finite JSON numbers
    for (const char* key : {"x", "y", "heading"}) {
        if (!IsFiniteJsonNumber(target.at(key))) {
            throw std::runtime_error(
                std::string("parking.move stub: ") + key +
                " must be a finite number");
        }
    }

    // Deterministic output v1 (M1-04B0 §5): no request_id, no positional or
    // arrival facts. Target values are echoed as parsed (not recomputed).
    ordered_json echoed_target;
    echoed_target["x"] = target.at("x");
    echoed_target["y"] = target.at("y");
    echoed_target["heading"] = target.at("heading");

    ordered_json output;
    output["output_version"] = kParkingOutputVersion;
    output["status"] = kParkingStatusStubCompleted;
    output["execution_mode"] = kParkingExecutionMode;
    output["action"] = kParkingCapabilityId;
    output["intent_id"] = intent_id;
    output["target"] = std::move(echoed_target);
    return output.dump();
}

// ---- Response construction ----------------------------------------------
ordered_json BuildResponse(const std::optional<std::string>& request_id) {
    ordered_json response;
    response["protocol_version"] = kProtocolVersion;
    response["request_id"] = request_id.has_value()
                                 ? ordered_json(*request_id)
                                 : ordered_json(nullptr);
    response["host_kind"] = kHostKind;
    response["accepted"] = false;
    response["submission_status"] = nullptr;
    response["observation_status"] = nullptr;
    response["execution_status"] = nullptr;
    response["output"] = nullptr;
    response["error"] = nullptr;
    return response;
}

ordered_json ErrorResponse(const std::optional<std::string>& request_id,
                           const std::string& code,
                           const std::string& message) {
    ordered_json response = BuildResponse(request_id);
    response["error"] = ordered_json{{"code", code}, {"message", message}};
    return response;
}

void WriteResponse(const ordered_json& response) {
    std::cout << response.dump(-1, ' ', false,
                               ordered_json::error_handler_t::replace)
              << '\n';
    std::cout.flush();
}

// ---- Bounded line reader -------------------------------------------------
struct LineReadResult {
    std::string bytes;
    bool oversize = false;
    bool eof = false;
    bool drain_exceeded = false;
};

LineReadResult ReadBoundedLine(std::istream& in) {
    LineReadResult result;
    std::size_t drained = 0;
    char ch = 0;
    while (true) {
        if (!in.get(ch)) {
            result.eof = true;
            return result;
        }
        if (ch == '\n') {
            return result;
        }
        if (result.oversize) {
            ++drained;
            if (drained > kOversizeDrainCap) {
                result.drain_exceeded = true;
                result.eof = true;
                return result;
            }
            continue;
        }
        result.bytes.push_back(ch);
        if (result.bytes.size() > kMaxRequestLineBytes) {
            result.oversize = true;
            result.bytes.clear();
        }
    }
}

// ---- Request validation --------------------------------------------------
struct ValidatedRequest {
    std::string request_id;
    std::string capability_id;
    std::string payload;
};

struct ValidationError {
    std::string code;
    std::string message;
};

std::optional<std::string> PeekRequestId(const ordered_json& obj) {
    if (!obj.is_object()) {
        return std::nullopt;
    }
    const auto it = obj.find("request_id");
    if (it == obj.end() || !it->is_string()) {
        return std::nullopt;
    }
    const std::string value = it->get<std::string>();
    if (CountCodePoints(value) > kMaxRequestIdCodePoints || !IsNonBlank(value)) {
        return std::nullopt;
    }
    return value;
}

bool ValidateRequestObject(const ordered_json& obj, ValidatedRequest& out,
                           ValidationError& err) {
    if (!obj.is_object()) {
        err = {kErrInvalidField, "request must be a JSON object"};
        return false;
    }

    static const char* const kRequired[] = {"protocol_version", "request_id",
                                            "type", "capability_id", "payload"};
    for (const char* field : kRequired) {
        if (obj.find(field) == obj.end()) {
            err = {kErrMissingField,
                   std::string("missing required field: ") + field};
            return false;
        }
    }

    const auto& version = obj.at("protocol_version");
    if (!version.is_string()) {
        err = {kErrInvalidField, "protocol_version must be a string"};
        return false;
    }
    const std::string version_value = version.get<std::string>();
    if (version_value != kProtocolVersion) {
        err = {kErrUnsupportedVersion,
               "unsupported protocol_version: '" + version_value + "'"};
        return false;
    }

    const auto& request_id = obj.at("request_id");
    if (!request_id.is_string()) {
        err = {kErrInvalidField, "request_id must be a string"};
        return false;
    }
    const std::string request_id_value = request_id.get<std::string>();
    if (CountCodePoints(request_id_value) > kMaxRequestIdCodePoints) {
        err = {kErrInvalidRequestId, "request_id exceeds 128 characters"};
        return false;
    }
    if (!IsNonBlank(request_id_value)) {
        err = {kErrInvalidRequestId,
               "request_id must be non-empty and non-blank"};
        return false;
    }

    const auto& message_type = obj.at("type");
    if (!message_type.is_string()) {
        err = {kErrInvalidField, "type must be a string"};
        return false;
    }
    const std::string type_value = message_type.get<std::string>();
    if (type_value != "submit") {
        err = {kErrUnsupportedType, "unsupported type: '" + type_value + "'"};
        return false;
    }

    const auto& capability_id = obj.at("capability_id");
    if (!capability_id.is_string()) {
        err = {kErrInvalidField, "capability_id must be a string"};
        return false;
    }
    const std::string capability_id_value = capability_id.get<std::string>();
    if (!IsNonBlank(capability_id_value)) {
        err = {kErrInvalidField,
               "capability_id must be non-empty and non-blank"};
        return false;
    }

    const auto& payload = obj.at("payload");
    if (!payload.is_string()) {
        err = {kErrInvalidField, "payload must be a string"};
        return false;
    }
    const std::string payload_value = payload.get<std::string>();
    if (payload_value.size() > kMaxPayloadBytes) {
        err = {kErrPayloadTooLarge, "payload exceeds 1048576 bytes"};
        return false;
    }
    if (!IsNonBlank(payload_value)) {
        err = {kErrInvalidField, "payload must be non-empty and non-blank"};
        return false;
    }

    out.request_id = request_id_value;
    out.capability_id = capability_id_value;
    out.payload = payload_value;
    return true;
}

// ---- Kernel-backed execution --------------------------------------------
const char* MapExecutionStatus(ak::ExecutionStatus status) noexcept {
    switch (status) {
        case ak::ExecutionStatus::kCompleted:
            return "completed";
        case ak::ExecutionStatus::kFailed:
            return "failed";
        case ak::ExecutionStatus::kCancelled:
            return "cancelled";
        case ak::ExecutionStatus::kUnresolvable:
            return "unresolvable";
        case ak::ExecutionStatus::kInternalError:
            return "internal-error";
    }
    return "internal-error";
}

std::string ClassifyFailure(const std::string& failure) {
    if (failure.rfind("capability-not-found:", 0) == 0) {
        return kErrCapabilityNotFound;
    }
    if (failure.rfind("capability-invocation-failed:", 0) == 0) {
        return kErrCapabilityInvocationFailed;
    }
    if (failure.rfind("result-not-found:", 0) == 0) {
        return kErrCapabilityInvocationFailed;
    }
    if (failure.rfind("invalid-invocation:", 0) == 0) {
        return kErrInvalidField;
    }
    return kErrInternalError;
}

ordered_json ExecuteViaKernel(const ValidatedRequest& request) {
    // One Runtime per request: the Runtime lifecycle is one-shot.
    auto runtime = std::make_unique<ak::runtime::Runtime>();
    runtime->RegisterCapability(
        kTestCapabilityId, kTestProviderId,
        [](const std::string& payload) -> std::string {
            return std::string(kEchoPrefix) + payload;
        });
    // parking.move stub: registered on the Runtime like any other capability,
    // so it is reached only through the same submission/observation path.
    runtime->RegisterCapability(kParkingCapabilityId, kParkingProviderId,
                                [](const std::string& payload) -> std::string {
                                    return RunParkingMoveStub(payload);
                                });

    // The sanctioned authorization path: the handle owns a
    // RuntimePublicApiAdapter bound to this Runtime.
    ak::runtime_integration::RuntimeExecutionAuthorityHandle authority =
        ak::runtime_integration::IssueRuntimeExecutionAuthority(*runtime);

    const ak::agent::RuntimeRequestId request_id(request.request_id);
    const ak::agent::RuntimeInvocationRequest invocation{
        request_id, request.capability_id, request.payload};

    const ak::agent::RuntimeSubmissionResult submission =
        authority.Port().Submit(invocation);
    const ak::agent::RuntimeObservation observation =
        authority.Port().Observe(request_id);

    // The host owns this Runtime, so it may read the authoritative
    // per-invocation ExecutionResult directly for execution_status.
    std::optional<std::string> execution_status;
    if (const std::optional<ak::ExecutionResult> result =
            runtime->GetInvocationResult(request.request_id);
        result.has_value()) {
        execution_status = MapExecutionStatus(result->status);
    }
    runtime->Stop();

    ordered_json response = BuildResponse(request.request_id);
    response["accepted"] = submission.accepted;

    if (submission.status == ak::agent::SubmissionStatus::kCompleted) {
        response["submission_status"] = "completed";
    } else if (submission.status == ak::agent::SubmissionStatus::kRejected) {
        response["submission_status"] = "rejected";
    } else {
        response["submission_status"] = "failed";
    }

    if (observation.status == ak::agent::ObservationStatus::kSuccess) {
        response["observation_status"] = "success";
    } else {
        response["observation_status"] = "failure";
    }

    if (execution_status.has_value()) {
        response["execution_status"] = *execution_status;
    }

    if (observation.status == ak::agent::ObservationStatus::kSuccess) {
        response["output"] = observation.output;
    } else {
        const std::string message = !submission.failure.empty()
                                        ? submission.failure
                                        : observation.failure;
        std::string code;
        if (submission.status == ak::agent::SubmissionStatus::kRejected) {
            code = kErrInvalidField;
        } else if (submission.status == ak::agent::SubmissionStatus::kFailed) {
            code = ClassifyFailure(submission.failure);
        } else {
            code = ClassifyFailure(observation.failure);
        }
        response["error"] = ordered_json{{"code", code}, {"message", message}};
    }
    return response;
}

// ---- One request line ----------------------------------------------------
ordered_json HandleRequestLine(const std::string& line) {
    if (line.size() > kMaxRequestLineBytes) {
        return ErrorResponse(std::nullopt, kErrOversizeLine,
                             "request line exceeds 65536 bytes");
    }

    ordered_json obj;
    try {
        obj = ordered_json::parse(line);
    } catch (const ordered_json::exception&) {
        // Malformed JSON: never reaches any execution path.
        return ErrorResponse(std::nullopt, kErrMalformedJson, "invalid JSON");
    }

    const std::optional<std::string> peeked = PeekRequestId(obj);

    ValidatedRequest request;
    ValidationError err;
    if (!ValidateRequestObject(obj, request, err)) {
        return ErrorResponse(peeked, err.code, err.message);
    }

    return ExecuteViaKernel(request);
}

}  // namespace

int main() {
#if defined(_WIN32)
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    Log("ready (kernel host; real Agent-Kernel runtime integration)");

    while (true) {
        const LineReadResult line = ReadBoundedLine(std::cin);
        if (line.drain_exceeded) {
            Log("fatal: oversize line exceeded drain cap; exiting");
            return 2;
        }
        if (line.oversize) {
            Log("rejected request: oversize-line");
            WriteResponse(ErrorResponse(std::nullopt, kErrOversizeLine,
                                        "request line exceeds 65536 bytes"));
            continue;
        }
        if (line.eof && line.bytes.empty()) {
            break;
        }
        WriteResponse(HandleRequestLine(line.bytes));
    }

    Log("stdin closed; exiting");
    return 0;
}
