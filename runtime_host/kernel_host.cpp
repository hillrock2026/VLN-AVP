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

#include <cerrno>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#else
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
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
#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_objects.hpp>
#include <agent_kernel/context/context_services.hpp>
#include <agent_kernel/executor/execution_result.hpp>
#include <agent_kernel/runtime_integration/runtime_execution_authority.hpp>
#include <agent_kernel/session.hpp>
#include <agent_kernel/session/session_builder.hpp>
#include <agent_kernel/task.hpp>
#include <agent_kernel/workflow.hpp>

#include <runtime.h>

#include <agent_kernel/planner/planner.hpp>

#include "autoware_adapter.h"
#include "taichu_planning_engine.hpp"

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
constexpr const char* kParkingCarlaProviderId = "vln.parking.carla";
constexpr const char* kAgentIntentContractVersion = "1";
constexpr const char* kParkingOutputVersion = "1";
constexpr const char* kParkingCarlaOutputVersion = "2";
constexpr const char* kParkingStatusStubCompleted = "stub_completed";
constexpr const char* kParkingStatusCarlaCompleted = "carla_completed";
constexpr const char* kParkingExecutionMode = "simulation";
constexpr const char* kParkingCarlaExecutionMode = "carla";

// ---- CARLA execution bridge (M1-VLN-CARLA-02) ----------------------------
// The Kernel host is a C++ process; the CARLA controller is Python. When the
// loopback bridge is configured, the registered parking.move invoker calls it
// synchronously and returns only after the CARLA controller has read the real
// post-execution state. Without the bridge, the frozen simulation stub is
// used unchanged. The bridge is not a Kernel authorization bypass: the host
// still reaches the invoker only through IssueRuntimeExecutionAuthority.
constexpr const char* kBridgeEndpointEnv = "VLN_CARLA_EXEC_BRIDGE";
constexpr const char* kBridgeTokenEnv = "VLN_CARLA_EXEC_TOKEN";
constexpr const char* kBridgeTimeoutEnv = "VLN_CARLA_EXEC_TIMEOUT_MS";
constexpr int kDefaultBridgeTimeoutMs = 180000;
constexpr int kMaxBridgeTimeoutMs = 600000;
constexpr std::size_t kMaxBridgeResponseBytes = 1024u * 1024u;
constexpr const char* kCarlaExecutionMode = "carla";
constexpr const char* kCarlaStatusCompleted = "completed";

// ---- Persistent Session / Context control plane --------------------------
constexpr const char* kSessionCreateCapabilityId = "session.create";
constexpr const char* kSessionGetCapabilityId = "session.get";
constexpr const char* kSessionCloseCapabilityId = "session.close";
// Generic domain-state feedback for a persistent Session Context. It records
// VLN-AVP parking-domain progress; it is not an execution capability and never
// grants motion authorization.
constexpr const char* kSessionContextUpdateCapabilityId =
    "session.context.update";
constexpr const char* kErrSessionNotFound = "session-not-found";
constexpr const char* kErrSessionClosed = "session-closed";
constexpr const char* kErrSessionExists = "session-exists";
constexpr const char* kErrSessionControl = "session-control-error";
constexpr const char* kErrContextRevisionMismatch = "context-revision-mismatch";
constexpr const char* kErrContextUpdateFailed = "context-update-failed";
constexpr std::size_t kMaxSessionIdCodePoints = 128;

// ---- Planner boundary (real TaichuPlanningEngine) ------------------------
// planner.plan is NOT a Runtime execution capability: it is the Kernel
// Planner boundary. The Host owns one Planner per process and injects the
// real Taichu engine; the engine's only job is to transport one validated
// planning input to the Python planner bridge and return the raw model text.
// The model output is a CANDIDATE, never an execution permit.
constexpr const char* kPlannerPlanCapabilityId = "planner.plan";
constexpr const char* kErrPlannerUnavailable = "planner-unavailable";
constexpr const char* kErrPlannerRejected = "planner-rejected";
constexpr const char* kErrPlannerIncomplete = "planner-incomplete";
constexpr const char* kErrPlannerFailed = "planner-failed";
constexpr std::size_t kMaxHistoryEntries = 64;
constexpr std::size_t kMaxPreviewBytes = 2048;

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

ordered_json ParseParkingIntent(const std::string& payload) {
    ordered_json intent;
    try {  // S1: payload is legal JSON
        intent = ordered_json::parse(payload);
    } catch (const ordered_json::exception&) {
        throw std::runtime_error("parking.move: payload is not valid JSON");
    }

    // S2: root is an object
    if (!intent.is_object()) {
        throw std::runtime_error("parking.move: payload must be an object");
    }
    // S3: exact top-level key set (fail-closed)
    if (!HasExactKeys(intent, {"contract_version", "intent_id", "action",
                               "target"})) {
        throw std::runtime_error(
            "parking.move: unexpected top-level field set");
    }
    // S4: contract_version is the string "1"
    if (!intent.at("contract_version").is_string() ||
        intent.at("contract_version").get<std::string>() !=
            kAgentIntentContractVersion) {
        throw std::runtime_error(
            "parking.move: unsupported contract_version");
    }
    // S5: action is "parking.move"
    if (!intent.at("action").is_string() ||
        intent.at("action").get<std::string>() != kParkingCapabilityId) {
        throw std::runtime_error("parking.move: unsupported action");
    }
    // S6: intent_id is a non-blank string (length authority stays in Python)
    const ordered_json& intent_id_node = intent.at("intent_id");
    if (!intent_id_node.is_string()) {
        throw std::runtime_error("parking.move: intent_id must be a string");
    }
    const std::string intent_id = intent_id_node.get<std::string>();
    if (!IsNonBlank(intent_id)) {
        throw std::runtime_error("parking.move: intent_id must be non-blank");
    }
    // S7: target is an object with exactly {x, y, heading}
    const ordered_json& target = intent.at("target");
    if (!HasExactKeys(target, {"x", "y", "heading"})) {
        throw std::runtime_error(
            "parking.move: unexpected target field set");
    }
    // S8: x, y, heading are finite JSON numbers
    for (const char* key : {"x", "y", "heading"}) {
        if (!IsFiniteJsonNumber(target.at(key))) {
            throw std::runtime_error(
                std::string("parking.move: ") + key +
                " must be a finite number");
        }
    }
    return intent;
}

std::string RunParkingMoveStub(const ordered_json& intent) {
    const ordered_json& target = intent.at("target");
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
    output["intent_id"] = intent.at("intent_id");
    output["target"] = std::move(echoed_target);
    return output.dump();
}

// ---- CARLA execution bridge transport ------------------------------------
struct CarlaBridgeConfig {
    std::string host;
    int port = 0;
    std::string token;
    int timeout_ms = kDefaultBridgeTimeoutMs;
};

struct CarlaBridgeLoad {
    bool configured = false;
    bool valid = false;
    CarlaBridgeConfig config;
    std::string error;
};

int ParseBridgeTimeout(const char* text, int fallback) {
    if (text == nullptr || *text == '\0') {
        return fallback;
    }
    try {
        std::size_t consumed = 0;
        const int value = std::stoi(std::string(text), &consumed);
        if (consumed != std::strlen(text) || value < 1 ||
            value > kMaxBridgeTimeoutMs) {
            return -1;
        }
        return value;
    } catch (const std::exception&) {
        return -1;
    }
}

CarlaBridgeLoad LoadCarlaBridgeConfig() {
    CarlaBridgeLoad load;
    const char* endpoint = std::getenv(kBridgeEndpointEnv);
    if (endpoint == nullptr || *endpoint == '\0') {
        return load;
    }
    load.configured = true;
    const std::string text(endpoint);
    const std::size_t colon = text.rfind(':');
    if (colon == std::string::npos || colon == 0 || colon + 1 >= text.size()) {
        load.error = std::string(kBridgeEndpointEnv) + " must be host:port";
        return load;
    }
    const std::string host = text.substr(0, colon);
    int port = 0;
    try {
        std::size_t consumed = 0;
        port = std::stoi(text.substr(colon + 1), &consumed);
        if (consumed != text.size() - colon - 1) {
            load.error = std::string(kBridgeEndpointEnv) + " has a non-numeric port";
            return load;
        }
    } catch (const std::exception&) {
        load.error = std::string(kBridgeEndpointEnv) + " has an invalid port";
        return load;
    }
    if (port < 1 || port > 65535) {
        load.error = std::string(kBridgeEndpointEnv) + " port is out of range";
        return load;
    }
    const char* token = std::getenv(kBridgeTokenEnv);
    if (token == nullptr || !IsNonBlank(std::string(token))) {
        load.error = std::string(kBridgeTokenEnv) + " must be a non-blank token";
        return load;
    }
    const int timeout_ms = ParseBridgeTimeout(
        std::getenv(kBridgeTimeoutEnv), kDefaultBridgeTimeoutMs);
    if (timeout_ms < 1) {
        load.error = std::string(kBridgeTimeoutEnv) + " is not a valid timeout";
        return load;
    }
    load.config = CarlaBridgeConfig{host, port, std::string(token), timeout_ms};
    load.valid = true;
    return load;
}

#if !defined(_WIN32)
int ConnectBridge(const CarlaBridgeConfig& config) {
    addrinfo hints{};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* results = nullptr;
    const std::string port_text = std::to_string(config.port);
    const int lookup =
        getaddrinfo(config.host.c_str(), port_text.c_str(), &hints, &results);
    if (lookup != 0) {
        throw std::runtime_error(
            std::string("carla bridge: cannot resolve host: ") +
            gai_strerror(lookup));
    }
    int fd = -1;
    for (addrinfo* item = results; item != nullptr; item = item->ai_next) {
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        timeval timeout{};
        timeout.tv_sec = config.timeout_ms / 1000;
        timeout.tv_usec = (config.timeout_ms % 1000) * 1000;
        (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                         sizeof(timeout));
        (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout,
                         sizeof(timeout));
        if (connect(fd, item->ai_addr, item->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(results);
    if (fd < 0) {
        throw std::runtime_error(
            "carla bridge: cannot connect to " + config.host + ":" +
            std::to_string(config.port));
    }
    return fd;
}

void SendAll(int fd, const std::string& line) {
    std::size_t sent = 0;
    while (sent < line.size()) {
        const ssize_t written =
            send(fd, line.data() + sent, line.size() - sent,
#if defined(MSG_NOSIGNAL)
                 MSG_NOSIGNAL
#else
                 0
#endif
            );
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw std::runtime_error(
                std::string("carla bridge: send failed: ") +
                std::strerror(errno));
        }
        sent += static_cast<std::size_t>(written);
    }
}

std::string ReadBridgeLine(int fd) {
    std::string received;
    char buffer[4096];
    while (received.find('\n') == std::string::npos) {
        const ssize_t count = recv(fd, buffer, sizeof(buffer), 0);
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw std::runtime_error(
                std::string("carla bridge: receive failed: ") +
                std::strerror(errno));
        }
        if (count == 0) {
            throw std::runtime_error(
                "carla bridge: closed before returning a result");
        }
        received.append(buffer, static_cast<std::size_t>(count));
        if (received.size() > kMaxBridgeResponseBytes) {
            throw std::runtime_error(
                "carla bridge: response exceeds the size limit");
        }
    }
    return received.substr(0, received.find('\n'));
}
#endif

ordered_json CallCarlaBridge(const CarlaBridgeConfig& config,
                             const std::string& request_id,
                             const ordered_json& intent) {
#if defined(_WIN32)
    (void)config;
    (void)request_id;
    (void)intent;
    throw std::runtime_error(
        "carla bridge: not supported by this Windows host build");
#else
    ordered_json request;
    request["protocol_version"] = kProtocolVersion;
    request["request_id"] = request_id;
    request["intent_id"] = intent.at("intent_id");
    request["capability_id"] = kParkingCapabilityId;
    request["token"] = config.token;
    request["payload"] = intent;

    const int fd = ConnectBridge(config);
    std::string line;
    try {
        line = request.dump();
        line.push_back('\n');
        SendAll(fd, line);
        const std::string response_line = ReadBridgeLine(fd);
        close(fd);
        try {
            return ordered_json::parse(response_line);
        } catch (const ordered_json::exception&) {
            throw std::runtime_error(
                "carla bridge: response is not valid JSON");
        }
    } catch (...) {
        close(fd);
        throw;
    }
#endif
}

bool FiniteState(const ordered_json& state) {
    return state.is_object() && state.contains("x") && state.contains("y") &&
           state.contains("speed") && IsFiniteJsonNumber(state.at("x")) &&
           IsFiniteJsonNumber(state.at("y")) &&
           IsFiniteJsonNumber(state.at("speed"));
}

std::string RunParkingMoveCarla(const CarlaBridgeConfig& config,
                                const std::string& request_id,
                                const ordered_json& intent) {
    const ordered_json reply = CallCarlaBridge(config, request_id, intent);

    if (!reply.is_object()) {
        throw std::runtime_error("carla bridge: response must be an object");
    }
    if (!reply.contains("request_id") || !reply.at("request_id").is_string() ||
        reply.at("request_id").get<std::string>() != request_id) {
        throw std::runtime_error(
            "carla bridge: response request_id does not match the request");
    }
    if (!reply.contains("intent_id") || !reply.at("intent_id").is_string() ||
        reply.at("intent_id") != intent.at("intent_id")) {
        throw std::runtime_error(
            "carla bridge: response intent_id does not match the intent");
    }
    if (!reply.contains("execution_mode") ||
        reply.at("execution_mode") != kCarlaExecutionMode) {
        throw std::runtime_error(
            "carla bridge: response is not a CARLA execution result");
    }
    if (!reply.contains("status") || !reply.at("status").is_string()) {
        throw std::runtime_error("carla bridge: response has no status");
    }
    const std::string status = reply.at("status").get<std::string>();
    if (status != kCarlaStatusCompleted) {
        std::string detail = status;
        if (reply.contains("reason") && reply.at("reason").is_string()) {
            detail += ": " + reply.at("reason").get<std::string>();
        }
        throw std::runtime_error(
            "carla execution did not complete (" + detail + ")");
    }
    if (!reply.contains("target") || reply.at("target") != intent.at("target")) {
        throw std::runtime_error(
            "carla bridge: response target does not match the intent");
    }
    if (!reply.contains("vehicle") || !reply.at("vehicle").is_object()) {
        throw std::runtime_error(
            "carla bridge: completed response has no vehicle evidence");
    }
    const ordered_json& vehicle = reply.at("vehicle");
    if (!vehicle.contains("pre_state") ||
        !FiniteState(vehicle.at("pre_state")) ||
        !vehicle.contains("post_state") ||
        !FiniteState(vehicle.at("post_state"))) {
        throw std::runtime_error(
            "carla bridge: vehicle evidence has no finite pre/post state");
    }
    if (!vehicle.contains("stopped") || !vehicle.at("stopped").is_boolean() ||
        !vehicle.at("stopped").get<bool>()) {
        throw std::runtime_error(
            "carla bridge: vehicle was not confirmed stopped after execution");
    }
    if (!vehicle.contains("stop_reason") ||
        !vehicle.at("stop_reason").is_string() ||
        vehicle.at("stop_reason").get<std::string>().empty()) {
        throw std::runtime_error(
            "carla bridge: vehicle evidence has no stop_reason");
    }

    const ordered_json& pre = vehicle.at("pre_state");
    const ordered_json& post = vehicle.at("post_state");
    const double moved =
        std::hypot(post.at("x").get<double>() - pre.at("x").get<double>(),
                   post.at("y").get<double>() - pre.at("y").get<double>());
    if (!std::isfinite(moved)) {
        throw std::runtime_error(
            "carla bridge: computed displacement is not finite");
    }

    // Output v2: the host-owned envelope plus the bridge's vehicle evidence.
    // moved_m is recomputed here from the real pre/post states; the bridge's
    // own value is not trusted.
    ordered_json output;
    output["output_version"] = kParkingCarlaOutputVersion;
    output["status"] = kParkingStatusCarlaCompleted;
    output["execution_mode"] = kCarlaExecutionMode;
    output["action"] = kParkingCapabilityId;
    output["intent_id"] = intent.at("intent_id");
    output["request_id"] = request_id;
    output["target"] = intent.at("target");
    output["vehicle"] = vehicle;
    output["vehicle"]["moved_m"] = moved;

    Log("parking.move: carla bridge completed request_id=" + request_id +
        " moved_m=" + std::to_string(moved));
    return output.dump();
}

std::string RunParkingMove(const std::string& payload,
                           const std::string& request_id,
                           const std::optional<CarlaBridgeConfig>& bridge) {
    const ordered_json intent = ParseParkingIntent(payload);
    if (!bridge.has_value()) {
        return RunParkingMoveStub(intent);
    }
    return RunParkingMoveCarla(*bridge, request_id, intent);
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
    // Optional persistent-session extension fields. Empty session_id keeps the
    // original one-shot path unchanged.
    std::string session_id;
    std::optional<long long> expected_context_revision;
    ordered_json domain = ordered_json::object();
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

    std::string session_id_value;
    const auto session_it = obj.find("session_id");
    if (session_it != obj.end()) {
        if (!session_it->is_string()) {
            err = {kErrInvalidField, "session_id must be a string"};
            return false;
        }
        session_id_value = session_it->get<std::string>();
        if (!IsNonBlank(session_id_value) ||
            CountCodePoints(session_id_value) > kMaxSessionIdCodePoints) {
            err = {kErrInvalidField,
                   "session_id must be non-blank and <= 128 characters"};
            return false;
        }
    }

    std::optional<long long> expected_context_revision;
    const auto revision_it = obj.find("expected_context_revision");
    if (revision_it != obj.end()) {
        if (!revision_it->is_number_integer()) {
            err = {kErrInvalidField,
                   "expected_context_revision must be a non-negative integer"};
            return false;
        }
        const long long value = revision_it->get<long long>();
        if (value < 0 || value > 1000000000000LL) {
            err = {kErrInvalidField,
                   "expected_context_revision is out of range"};
            return false;
        }
        expected_context_revision = value;
    }

    ordered_json domain_value = ordered_json::object();
    const auto domain_it = obj.find("domain");
    if (domain_it != obj.end()) {
        if (!domain_it->is_object()) {
            err = {kErrInvalidField, "domain must be a JSON object"};
            return false;
        }
        domain_value = *domain_it;
    }

    out.request_id = request_id_value;
    out.capability_id = capability_id_value;
    out.payload = payload_value;
    out.session_id = session_id_value;
    out.expected_context_revision = expected_context_revision;
    out.domain = std::move(domain_value);
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

// ---- Persistent Kernel Session + Context Runtime -------------------------
// The Host owns the composition root: one real ak::Session and one real
// ak::context::Context per logical parking session. Each request creates a
// new Runtime (the Runtime remains one-shot) but adds a new Workflow/Task to
// the persistent Session and runs only that Workflow.
struct PersistentSession {
    std::string session_id;
    std::unique_ptr<ak::Session> session;
    std::unique_ptr<ak::context::Context> context;
    ak::context::ContextObjectId context_object_id;
    std::uint64_t revision = 0;
    std::uint64_t turn = 0;
    std::string context_json = "{}";
};

std::unordered_map<std::string, std::unique_ptr<PersistentSession>> g_sessions;
std::unordered_map<std::string, bool> g_closed_sessions;
std::uint64_t g_session_counter = 0;
std::uint64_t g_context_identity_counter = 0;
std::uint64_t g_context_object_counter = 0;

// Engine lifetime must exceed Planner lifetime; declaration order gives the
// reverse destruction order required by the Kernel Planner boundary.
std::unique_ptr<vln::taichu::TaichuPlanningEngine> g_planner_engine;
std::unique_ptr<ak::planner::Planner> g_planner;
std::uint64_t g_planner_request_counter = 0;

const char* KernelStateName(ak::KernelObjectState state) noexcept {
    switch (state) {
        case ak::KernelObjectState::kCreated:
            return "CREATED";
        case ak::KernelObjectState::kInitialized:
            return "INITIALIZED";
        case ak::KernelObjectState::kReady:
            return "READY";
        case ak::KernelObjectState::kRunning:
            return "RUNNING";
        case ak::KernelObjectState::kSuspended:
            return "SUSPENDED";
        case ak::KernelObjectState::kCompleted:
            return "COMPLETED";
        case ak::KernelObjectState::kFailed:
            return "FAILED";
        case ak::KernelObjectState::kDestroyed:
            return "DESTROYED";
    }
    return "UNKNOWN";
}

ordered_json ParseJsonOrString(const std::string& text) {
    try {
        return ordered_json::parse(text);
    } catch (const ordered_json::exception&) {
        return ordered_json{{"raw", text}};
    }
}

PersistentSession* FindPersistentSession(const std::string& session_id,
                                         std::string& code,
                                         std::string& message) {
    if (g_closed_sessions.find(session_id) != g_closed_sessions.end()) {
        code = kErrSessionClosed;
        message = "session " + session_id + " is closed";
        return nullptr;
    }
    const auto it = g_sessions.find(session_id);
    if (it == g_sessions.end()) {
        code = kErrSessionNotFound;
        message = "session " + session_id + " was not found";
        return nullptr;
    }
    return it->second.get();
}

PersistentSession* CreatePersistentSession(const std::string& session_id,
                                           std::string& code,
                                           std::string& message) {
    if (g_closed_sessions.find(session_id) != g_closed_sessions.end()) {
        code = kErrSessionClosed;
        message = "session " + session_id + " is closed";
        return nullptr;
    }
    if (g_sessions.find(session_id) != g_sessions.end()) {
        code = kErrSessionExists;
        message = "session " + session_id + " already exists";
        return nullptr;
    }
    auto session = ak::SessionBuilder()
                       .WithID(ak::SessionID(static_cast<ak::SessionID::ValueType>(
                           ++g_session_counter)))
                       .WithName("vln-parking-" + session_id)
                       .WithMaxWorkflows(4096)
                       .Build();
    session->Initialize();
    session->Activate();

    auto context = std::make_unique<ak::context::Context>(
        ak::context::MakeContextIdentity(++g_context_identity_counter));
    const ak::context::ContextObjectId object_id =
        ak::context::MakeContextObjectId(++g_context_object_counter);
    ordered_json initial_context;
    initial_context["session_id"] = session_id;
    initial_context["turn"] = 0;
    initial_context["context_revision"] = 0;
    initial_context["status"] = "created";
    const std::string initial_context_text = initial_context.dump();
    if (!context->Creation()
             .CreateObject(object_id, "vln.parking", initial_context_text,
                           ak::context::ContextMetadata{})
             .IsSuccess()) {
        code = kErrSessionControl;
        message = "context object creation failed";
        return nullptr;
    }
    if (!context->Creation().InitializeObject(object_id).IsSuccess()) {
        code = kErrSessionControl;
        message = "context object initialization failed";
        return nullptr;
    }
    if (!context->Creation().ActivateObject(object_id).IsSuccess()) {
        code = kErrSessionControl;
        message = "context object activation failed";
        return nullptr;
    }

    auto holder = std::make_unique<PersistentSession>();
    holder->session_id = session_id;
    holder->session = std::move(session);
    holder->context = std::move(context);
    holder->context_object_id = object_id;
    holder->revision = 0;
    holder->turn = 0;
    holder->context_json = initial_context_text;
    PersistentSession* raw = holder.get();
    g_sessions.emplace(session_id, std::move(holder));
    Log("persistent session created session_id=" + session_id);
    return raw;
}

bool ReadPersistentContext(PersistentSession& session,
                           ordered_json& out,
                           std::string& message) {
    const auto view =
        session.context->Access().InspectObject(session.context_object_id);
    if (!view.IsSuccess()) {
        message = "context object read failed";
        return false;
    }
    out = ParseJsonOrString(view.value.content);
    return true;
}

bool UpdatePersistentContext(PersistentSession& session,
                             const ordered_json& content,
                             std::string& message) {
    auto& update = session.context->Update();
    if (!update.BeginUpdate(session.context_object_id).IsSuccess()) {
        message = "context update begin failed";
        return false;
    }
    if (!update.ApplyUpdate(session.context_object_id, content.dump(),
                            ak::context::ContextMetadata{})
             .IsSuccess()) {
        (void)update.CompleteUpdate(session.context_object_id);
        message = "context update apply failed";
        return false;
    }
    if (!update.CompleteUpdate(session.context_object_id).IsSuccess()) {
        message = "context update complete failed";
        return false;
    }
    session.context_json = content.dump();
    ++session.revision;
    return true;
}

ordered_json PersistentSessionInfo(const PersistentSession& session) {
    ordered_json info;
    info["session_id"] = session.session_id;
    info["session_state"] = KernelStateName(session.session->GetState());
    info["context_revision"] = session.revision;
    info["turn"] = session.turn;
    info["workflow_count"] = session.session->GetWorkflowCount();
    ordered_json workflows = ordered_json::array();
    std::size_t task_count = 0;
    for (const ak::WorkflowID workflow_id :
         session.session->Workflows().Enumerate()) {
        ordered_json workflow;
        workflow["workflow_id"] = std::to_string(workflow_id.Value());
        ak::Workflow* wf = session.session->FindWorkflow(workflow_id);
        if (wf != nullptr) {
            workflow["state"] = KernelStateName(wf->GetState());
            workflow["task_count"] = wf->GetTaskCount();
            task_count += wf->GetTaskCount();
            ordered_json tasks = ordered_json::array();
            for (const ak::TaskID task_id : wf->Tasks().Enumerate()) {
                tasks.push_back(std::to_string(task_id.Value()));
            }
            workflow["task_ids"] = tasks;
        }
        workflows.push_back(workflow);
    }
    info["workflows"] = workflows;
    info["task_count"] = task_count;
    info["context"] = ParseJsonOrString(session.context_json);
    return info;
}

void AddSessionFields(ordered_json& response,
                      const PersistentSession& session,
                      const ordered_json& before,
                      const ordered_json& after,
                      const std::string& task_id,
                      const std::string& workflow_id,
                      bool context_updated) {
    response["session_id"] = session.session_id;
    response["session_state"] = KernelStateName(session.session->GetState());
    response["context_revision"] = session.revision;
    response["turn"] = session.turn;
    response["context_before"] = before;
    response["context_after"] = after;
    response["task_id"] =
        task_id.empty() ? ordered_json(nullptr) : ordered_json(task_id);
    response["workflow_id"] = workflow_id.empty()
                                  ? ordered_json(nullptr)
                                  : ordered_json(workflow_id);
    response["context_updated"] = context_updated;
}

std::string PreviewText(const std::string& text, std::size_t limit) {
    if (text.size() <= limit) {
        return text;
    }
    std::size_t cut = limit;
    while (cut > 0 &&
           (static_cast<unsigned char>(text[cut]) & 0xC0u) == 0x80u) {
        --cut;
    }
    return text.substr(0, cut);
}

// Append one compact entry to the Session Context history. The history is the
// cross-turn continuity record: every planning exchange and every Kernel
// execution appends exactly one entry, and later turns read it back through
// Context.
ordered_json AppendHistory(const ordered_json& before,
                           const ordered_json& entry) {
    ordered_json history = ordered_json::array();
    if (before.is_object()) {
        const auto it = before.find("history");
        if (it != before.end() && it->is_array()) {
            history = *it;
        }
    }
    while (history.size() >= kMaxHistoryEntries) {
        history.erase(history.begin());
    }
    history.push_back(entry);
    return history;
}

bool InitializePlanner(const vln::taichu::PlannerBridgeLoad& load,
                       std::string& message) {
    if (!load.valid) {
        message = load.configured
                      ? load.error
                      : "planner bridge is not configured; planner.plan is "
                        "unavailable";
        return false;
    }
    try {
        g_planner_engine =
            std::make_unique<vln::taichu::TaichuPlanningEngine>(load.config);
        ak::planner::PlannerConfiguration configuration;
        configuration.metadata.name = "vln-avp-taichu-planner";
        configuration.metadata.description =
            "VLN-AVP Taichu planner bridge composition";
        g_planner = std::make_unique<ak::planner::Planner>(
            ak::planner::MakePlannerIdentity(1), *g_planner_engine,
            std::move(configuration));
    } catch (const std::exception& error) {
        message = std::string("planner construction failed: ") + error.what();
        g_planner.reset();
        g_planner_engine.reset();
        return false;
    }
    const auto initialized =
        g_planner->LifecycleContract().Lifecycle().Initialize();
    if (!initialized.IsAccepted()) {
        message = std::string("planner Initialize rejected: ") +
                  initialized.message;
        g_planner.reset();
        g_planner_engine.reset();
        return false;
    }
    const auto activated = g_planner->LifecycleContract().Lifecycle().Activate();
    if (!activated.IsAccepted()) {
        message =
            std::string("planner Activate rejected: ") + activated.message;
        g_planner.reset();
        g_planner_engine.reset();
        return false;
    }
    message.clear();
    return true;
}

void ShutdownPlanner() {
    if (g_planner != nullptr) {
        (void)g_planner->LifecycleContract().Lifecycle().Terminate();
    }
    g_planner.reset();
    g_planner_engine.reset();
}

ordered_json HandleSessionControl(const ValidatedRequest& request) {
    ordered_json payload_json;
    try {
        payload_json = ordered_json::parse(request.payload);
    } catch (const ordered_json::exception&) {
        return ErrorResponse(request.request_id, kErrSessionControl,
                             "control payload must be valid JSON");
    }
    if (!payload_json.is_object()) {
        return ErrorResponse(request.request_id, kErrSessionControl,
                             "control payload must be a JSON object");
    }
    std::string session_id;
    const auto sid_it = payload_json.find("session_id");
    if (sid_it != payload_json.end() && sid_it->is_string()) {
        session_id = sid_it->get<std::string>();
    }

    std::string code;
    std::string message;
    if (request.capability_id == kSessionCreateCapabilityId) {
        if (!IsNonBlank(session_id)) {
            session_id = "session-" + std::to_string(++g_session_counter);
        }
        PersistentSession* session =
            CreatePersistentSession(session_id, code, message);
        if (session == nullptr) {
            auto response = ErrorResponse(request.request_id, code, message);
            response["session_id"] = session_id;
            return response;
        }
        ordered_json response = BuildResponse(request.request_id);
        response["accepted"] = true;
        response["submission_status"] = "completed";
        response["observation_status"] = "success";
        response["execution_status"] = nullptr;
        response["output"] = PersistentSessionInfo(*session).dump();
        response["error"] = nullptr;
        AddSessionFields(response, *session, ordered_json(nullptr),
                         ParseJsonOrString(session->context_json), "", "",
                         false);
        return response;
    }

    if (!IsNonBlank(session_id)) {
        return ErrorResponse(request.request_id, kErrSessionControl,
                             "session_id is required");
    }
    PersistentSession* session =
        FindPersistentSession(session_id, code, message);
    if (session == nullptr) {
        auto response = ErrorResponse(request.request_id, code, message);
        response["session_id"] = session_id;
        return response;
    }

    if (request.capability_id == kSessionGetCapabilityId) {
        ordered_json response = BuildResponse(request.request_id);
        response["accepted"] = true;
        response["submission_status"] = "completed";
        response["observation_status"] = "success";
        response["execution_status"] = nullptr;
        response["output"] = PersistentSessionInfo(*session).dump();
        response["error"] = nullptr;
        AddSessionFields(response, *session, ordered_json(nullptr),
                         ParseJsonOrString(session->context_json), "", "",
                         false);
        return response;
    }

    // session.close
    const ordered_json info = PersistentSessionInfo(*session);
    const ordered_json context = ParseJsonOrString(session->context_json);
    ordered_json response = BuildResponse(request.request_id);
    response["accepted"] = true;
    response["submission_status"] = "completed";
    response["observation_status"] = "success";
    response["execution_status"] = nullptr;
    response["output"] = info.dump();
    response["error"] = nullptr;
    AddSessionFields(response, *session, ordered_json(nullptr), context, "", "",
                     false);
    response["session_state"] = "DESTROYED";
    (void)session->context->Release().ReleaseObject(
        session->context_object_id);
    session->session->Shutdown();
    session->session->Destroy();
    g_closed_sessions[session_id] = true;
    g_sessions.erase(session_id);
    Log("persistent session closed session_id=" + session_id);
    return response;
}

// ---- planner.plan (Kernel Planner boundary, real Taichu engine) ----------
// The Host is the composition root for the Planner. One planning exchange
// reads the persistent Session Context, forwards one validated planning input
// through the Planner's Submit/CompletePlanningExchange path, and writes the
// planning outcome back into the Context. The returned text is the model's raw
// candidate output; it is never treated as an execution permit.
ordered_json HandlePlannerPlan(const ValidatedRequest& request) {
    if (request.session_id.empty()) {
        return ErrorResponse(request.request_id, kErrPlannerUnavailable,
                             "planner.plan requires session_id");
    }
    std::string code;
    std::string message;
    PersistentSession* session = nullptr;
    const auto existing = g_sessions.find(request.session_id);
    if (existing != g_sessions.end()) {
        session = existing->second.get();
    } else if (g_closed_sessions.find(request.session_id) !=
               g_closed_sessions.end()) {
        return ErrorResponse(request.request_id, kErrSessionClosed,
                             "session " + request.session_id + " is closed");
    } else {
        session = CreatePersistentSession(request.session_id, code, message);
        if (session == nullptr) {
            auto response = ErrorResponse(request.request_id, code, message);
            response["session_id"] = request.session_id;
            return response;
        }
    }

    ordered_json context_before;
    if (!ReadPersistentContext(*session, context_before, message)) {
        return ErrorResponse(request.request_id, kErrSessionControl, message);
    }
    if (request.expected_context_revision.has_value() &&
        static_cast<unsigned long long>(*request.expected_context_revision) !=
            session->revision) {
        auto response = ErrorResponse(
            request.request_id, kErrContextRevisionMismatch,
            "expected_context_revision does not match the Session Context");
        response["session_id"] = session->session_id;
        response["session_state"] =
            KernelStateName(session->session->GetState());
        response["context_revision"] = session->revision;
        response["turn"] = session->turn;
        response["context_before"] = context_before;
        response["context_updated"] = false;
        return response;
    }

    ordered_json input;
    try {
        input = ordered_json::parse(request.payload);
    } catch (const ordered_json::exception&) {
        return ErrorResponse(request.request_id, kErrInvalidField,
                             "planner payload must be valid JSON");
    }
    if (!input.is_object()) {
        return ErrorResponse(request.request_id, kErrInvalidField,
                             "planner payload must be a JSON object");
    }
    for (const char* key : {"image_path", "instruction"}) {
        const auto it = input.find(key);
        if (it == input.end() || !it->is_string() ||
            !IsNonBlank(it->get<std::string>())) {
            return ErrorResponse(
                request.request_id, kErrInvalidField,
                std::string("planner payload requires a non-blank ") + key);
        }
    }
    const std::string image_path = input.at("image_path").get<std::string>();
    const std::string instruction =
        input.at("instruction").get<std::string>();

    ordered_json domain = request.domain;
    const auto domain_it = input.find("domain");
    if (domain_it != input.end()) {
        if (!domain_it->is_object()) {
            return ErrorResponse(request.request_id, kErrInvalidField,
                                 "planner payload domain must be an object");
        }
        domain = *domain_it;
    }

    if (g_planner == nullptr) {
        auto response = ErrorResponse(request.request_id, kErrPlannerUnavailable,
                                      "planner bridge is not configured");
        response["session_id"] = session->session_id;
        response["session_state"] =
            KernelStateName(session->session->GetState());
        response["context_revision"] = session->revision;
        response["turn"] = session->turn;
        response["context_before"] = context_before;
        response["context_updated"] = false;
        return response;
    }

    const ak::planner::PlannerSessionId planner_session_id =
        g_planner->GetPrimarySessionId();
    if (!planner_session_id.IsValid()) {
        return ErrorResponse(request.request_id, kErrPlannerUnavailable,
                             "planner has no primary session");
    }
    const ak::planner::PlanningRequestId planning_request_id =
        ak::planner::MakePlanningRequestId(++g_planner_request_counter);

    ordered_json goal;
    goal["request_id"] = request.request_id;
    goal["session_id"] = session->session_id;
    goal["context_revision"] = session->revision;
    goal["context"] = context_before;
    goal["image_path"] = image_path;
    goal["instruction"] = instruction;
    goal["domain"] = domain;

    ak::planner::PlanningRequest planning;
    planning.request_id = planning_request_id;
    planning.session_id = planner_session_id;
    planning.metadata.version = 1;
    planning.metadata.strategy = "taichu";
    planning.metadata.annotations.push_back("vln-avp.cap-08b-01");
    planning.goal = goal.dump();

    const ak::planner::PlanningAcceptance acceptance =
        g_planner->AgentContract().Planning().Submit(planning);
    if (!acceptance.IsAccepted()) {
        auto response = ErrorResponse(
            request.request_id, kErrPlannerRejected,
            std::string("planner refused the request: ") + acceptance.message);
        response["session_id"] = session->session_id;
        response["session_state"] =
            KernelStateName(session->session->GetState());
        response["context_revision"] = session->revision;
        response["turn"] = session->turn;
        response["context_before"] = context_before;
        response["context_updated"] = false;
        return response;
    }

    const ak::planner::PlanningCompletionResult completion =
        g_planner->AgentContract().Planning().CompletePlanningExchange(
            planning_request_id);
    const bool linearized = completion.IsSuccess() && completion.HasResult();

    ordered_json bridge_payload = ordered_json::object();
    bool candidate = false;
    std::string raw_output;
    std::string failure_message;
    if (!linearized) {
        failure_message =
            std::string("planning completion did not linearize: ") +
            completion.message;
    } else if (!completion.result.IsSuccess()) {
        failure_message = std::string("planner produced no artifact: ") +
                          completion.result.message;
    } else {
        try {
            bridge_payload =
                ordered_json::parse(completion.result.artifact_view.payload);
        } catch (const ordered_json::exception&) {
            failure_message = "planner artifact is not valid JSON";
        }
        if (failure_message.empty()) {
            const auto status_it = bridge_payload.is_object()
                                       ? bridge_payload.find("status")
                                       : bridge_payload.end();
            if (!bridge_payload.is_object()) {
                failure_message = "planner artifact must be a JSON object";
            } else if (status_it == bridge_payload.end() ||
                       !status_it->is_string()) {
                failure_message =
                    "planner bridge status must be a string";
            } else if (status_it->get<std::string>() != "ok") {
                const auto error_it = bridge_payload.find("error");
                if (error_it != bridge_payload.end() && error_it->is_object()) {
                    if (error_it->contains("message") &&
                        error_it->at("message").is_string()) {
                        failure_message =
                            error_it->at("message").get<std::string>();
                    } else if (error_it->contains("type") &&
                               error_it->at("type").is_string()) {
                        failure_message =
                            error_it->at("type").get<std::string>();
                    } else {
                        failure_message = "planner bridge failure";
                    }
                } else {
                    failure_message = "planner bridge reported status=" +
                                      status_it->get<std::string>();
                }
            } else {
                const auto raw_it = bridge_payload.find("raw_output");
                if (raw_it == bridge_payload.end() || !raw_it->is_string()) {
                    failure_message = "planner bridge omitted raw_output";
                } else {
                    raw_output = raw_it->get<std::string>();
                    candidate = IsNonBlank(raw_output);
                    if (!candidate) {
                        failure_message = "model returned empty output";
                    }
                }
            }
        }
    }

    ordered_json output;
    output["status"] = candidate ? "candidate" : "failed";
    output["is_execution_permit"] = false;
    output["planner_session_id"] =
        std::to_string(planner_session_id.Value());
    output["planner_request_id"] =
        std::to_string(planning_request_id.Value());
    output["planner_lifecycle"] = std::string(
        ak::planner::PlannerLifecycleStateName(g_planner->GetLifecycleState()));
    output["strategy"] = "taichu";
    output["session_id"] = session->session_id;
    output["context_revision_before"] = session->revision;
    if (linearized) {
        output["planning_result_id"] =
            std::to_string(completion.result.result_id.Value());
        output["planning_result_status"] =
            completion.result.IsSuccess() ? "success" : "failed";
        if (completion.result.IsSuccess()) {
            output["planning_artifact_id"] = std::to_string(
                completion.result.artifact_view.artifact_id.Value());
        }
    }
    if (bridge_payload.is_object() && bridge_payload.contains("model")) {
        output["model"] = bridge_payload.at("model");
    }
    if (candidate) {
        output["raw_output"] = raw_output;
        output["image_path"] = bridge_payload.value(
            "image_path", ordered_json(image_path));
        output["image_sha256"] =
            bridge_payload.value("image_sha256", ordered_json(nullptr));
        output["raw_output_sha256"] =
            bridge_payload.value("raw_output_sha256", ordered_json(nullptr));
        output["instruction_sha256"] =
            bridge_payload.value("instruction_sha256", ordered_json(nullptr));
        output["prompt"] =
            bridge_payload.value("prompt", ordered_json(nullptr));
        output["prompt_sha256"] =
            bridge_payload.value("prompt_sha256", ordered_json(nullptr));
        output["prompt_chars"] =
            bridge_payload.value("prompt_chars", ordered_json(nullptr));
        output["context_selection"] =
            bridge_payload.value("context_selection", ordered_json(nullptr));
        output["context_sha256"] =
            bridge_payload.value("context_sha256", ordered_json(nullptr));
        output["server_response"] =
            bridge_payload.value("server_response", ordered_json(nullptr));
        output["bridge_latency_ms"] =
            bridge_payload.value("latency_ms", ordered_json(nullptr));
    } else {
        output["error"] = ordered_json{
            {"type", "planner-failure"},
            {"message", failure_message.empty() ? "model planning failed"
                                                : failure_message}};
        if (bridge_payload.is_object() && !bridge_payload.empty()) {
            output["bridge"] = bridge_payload;
        }
    }

    const std::uint64_t next_turn = session->turn + 1;
    ordered_json history_entry;
    history_entry["kind"] = "planning";
    history_entry["turn"] = next_turn;
    history_entry["revision"] = session->revision + 1;
    history_entry["request_id"] = request.request_id;
    history_entry["status"] = candidate ? "planned" : "failed";
    history_entry["planner_request_id"] =
        std::to_string(planning_request_id.Value());
    history_entry["planner_session_id"] =
        std::to_string(planner_session_id.Value());
    history_entry["model"] =
        output.contains("model") ? output.at("model") : ordered_json(nullptr);
    history_entry["raw_output_preview"] =
        candidate ? ordered_json(PreviewText(raw_output, kMaxPreviewBytes))
                  : ordered_json(nullptr);
    history_entry["domain"] = domain;
    if (!candidate) {
        history_entry["error"] = output["error"];
    }

    ordered_json context;
    context["session_id"] = session->session_id;
    context["turn"] = next_turn;
    context["context_revision"] = session->revision + 1;
    context["phase"] = "planning";
    context["request_id"] = request.request_id;
    context["status"] = candidate ? "planned" : "failed";
    context["planner_session_id"] =
        std::to_string(planner_session_id.Value());
    context["planner_request_id"] =
        std::to_string(planning_request_id.Value());
    context["planner_lifecycle"] = output["planner_lifecycle"];
    context["strategy"] = "taichu";
    context["model"] =
        output.contains("model") ? output.at("model") : ordered_json(nullptr);
    context["raw_output_preview"] =
        candidate ? ordered_json(PreviewText(raw_output, kMaxPreviewBytes))
                  : ordered_json(nullptr);
    context["domain"] = domain;
    if (!candidate) {
        context["error"] = output["error"];
    }
    context["history"] = AppendHistory(context_before, history_entry);

    bool context_updated =
        UpdatePersistentContext(*session, context, message);
    if (context_updated) {
        session->turn = next_turn;
    }

    ordered_json response = BuildResponse(request.request_id);
    response["accepted"] = true;
    response["submission_status"] = linearized ? "completed" : "failed";
    response["observation_status"] = candidate ? "success" : "failure";
    response["execution_status"] = nullptr;
    response["output"] = output.dump();
    if (!candidate) {
        response["error"] = ordered_json{
            {"code", linearized ? kErrPlannerFailed : kErrPlannerIncomplete},
            {"message", failure_message.empty() ? "model planning failed"
                                                : failure_message}};
    } else {
        response["error"] = nullptr;
    }
    if (!context_updated) {
        response["observation_status"] = "failure";
        response["error"] = ordered_json{{"code", kErrContextUpdateFailed},
                                         {"message", message}};
    }
    AddSessionFields(response, *session, context_before,
                     context_updated ? context : ordered_json(nullptr), "", "",
                     context_updated);
    if (!context_updated) {
        response["context_revision"] = session->revision;
    }
    Log("planner.plan request_id=" + request.request_id +
        " planner_request_id=" +
        std::to_string(planning_request_id.Value()) +
        " status=" + (candidate ? "candidate" : "failed") +
        " context_revision=" + std::to_string(session->revision));
    return response;
}

// ---- session.context.update (domain-state feedback only) -----------------
// The Session Context remains authoritative. This control path appends a
// VLN-AVP parking-domain snapshot after a validated stage transition. It never
// creates a Workflow/Task, never invokes a capability and never authorises
// motion.
ordered_json HandleSessionContextUpdate(const ValidatedRequest& request) {
    if (request.session_id.empty()) {
        return ErrorResponse(request.request_id, kErrSessionControl,
                             "session.context.update requires session_id");
    }
    std::string code;
    std::string message;
    PersistentSession* session = nullptr;
    const auto existing = g_sessions.find(request.session_id);
    if (existing != g_sessions.end()) {
        session = existing->second.get();
    } else if (g_closed_sessions.find(request.session_id) !=
               g_closed_sessions.end()) {
        return ErrorResponse(request.request_id, kErrSessionClosed,
                             "session " + request.session_id + " is closed");
    } else {
        return ErrorResponse(request.request_id, kErrSessionControl,
                             "session " + request.session_id + " does not exist");
    }

    ordered_json context_before;
    if (!ReadPersistentContext(*session, context_before, message)) {
        return ErrorResponse(request.request_id, kErrSessionControl, message);
    }
    if (request.expected_context_revision.has_value() &&
        static_cast<unsigned long long>(*request.expected_context_revision) !=
            session->revision) {
        auto response = ErrorResponse(
            request.request_id, kErrContextRevisionMismatch,
            "expected_context_revision does not match the Session Context");
        response["session_id"] = session->session_id;
        response["context_revision"] = session->revision;
        response["turn"] = session->turn;
        response["context_before"] = context_before;
        response["context_updated"] = false;
        return response;
    }

    ordered_json input;
    try {
        input = ordered_json::parse(request.payload);
    } catch (const ordered_json::exception&) {
        return ErrorResponse(request.request_id, kErrInvalidField,
                             "context update payload must be valid JSON");
    }
    if (!input.is_object()) {
        return ErrorResponse(request.request_id, kErrInvalidField,
                             "context update payload must be a JSON object");
    }
    const auto parking_it = input.find("parking");
    if (parking_it == input.end() || !parking_it->is_object()) {
        return ErrorResponse(request.request_id, kErrInvalidField,
                             "context update requires a parking object");
    }
    std::string kind = "stage_transition";
    const auto kind_it = input.find("kind");
    if (kind_it != input.end()) {
        if (!kind_it->is_string()) {
            return ErrorResponse(request.request_id, kErrInvalidField,
                                 "context update kind must be a string");
        }
        kind = kind_it->get<std::string>();
    }
    if (kind != "stage_transition") {
        return ErrorResponse(request.request_id, kErrInvalidField,
                             "context update kind must be stage_transition");
    }
    std::string status = "recorded";
    const auto status_it = input.find("status");
    if (status_it != input.end()) {
        if (!status_it->is_string() ||
            !IsNonBlank(status_it->get<std::string>())) {
            return ErrorResponse(request.request_id, kErrInvalidField,
                                 "context update status must be a non-blank string");
        }
        status = status_it->get<std::string>();
    }

    ordered_json domain = ordered_json::object();
    if (context_before.is_object() && context_before.contains("domain") &&
        context_before.at("domain").is_object()) {
        domain = context_before.at("domain");
    }
    domain["parking"] = *parking_it;

    const std::uint64_t next_turn = session->turn + 1;
    ordered_json history_entry;
    history_entry["kind"] = kind;
    history_entry["turn"] = next_turn;
    history_entry["revision"] = session->revision + 1;
    history_entry["request_id"] = request.request_id;
    history_entry["status"] = status;
    history_entry["domain"] = domain;

    ordered_json context;
    context["session_id"] = session->session_id;
    context["turn"] = next_turn;
    context["context_revision"] = session->revision + 1;
    context["phase"] = "domain";
    context["request_id"] = request.request_id;
    context["status"] = status;
    context["domain"] = domain;
    context["history"] = AppendHistory(context_before, history_entry);

    const bool context_updated =
        UpdatePersistentContext(*session, context, message);
    if (context_updated) {
        session->turn = next_turn;
    }
    ordered_json response = BuildResponse(request.request_id);
    response["accepted"] = true;
    response["submission_status"] = "completed";
    response["observation_status"] = context_updated ? "success" : "failure";
    response["execution_status"] = nullptr;
    response["output"] = context.dump();
    response["error"] =
        context_updated
            ? ordered_json(nullptr)
            : ordered_json{{"code", kErrContextUpdateFailed},
                           {"message", message}};
    AddSessionFields(response, *session, context_before,
                     context_updated ? context : ordered_json(nullptr), "", "",
                     context_updated);
    if (!context_updated) {
        response["context_revision"] = session->revision;
    }
    Log("session.context.update request_id=" + request.request_id +
        " session_id=" + session->session_id + " status=" + status +
        " context_revision=" + std::to_string(session->revision));
    return response;
}

ordered_json ExecutePersistentViaKernel(
    const ValidatedRequest& request,
    const std::optional<CarlaBridgeConfig>& bridge) {
    std::string code;
    std::string message;
    PersistentSession* session = nullptr;
    const auto existing = g_sessions.find(request.session_id);
    if (existing != g_sessions.end()) {
        session = existing->second.get();
    } else if (g_closed_sessions.find(request.session_id) !=
               g_closed_sessions.end()) {
        return ErrorResponse(request.request_id, kErrSessionClosed,
                             "session " + request.session_id + " is closed");
    } else {
        session = CreatePersistentSession(request.session_id, code, message);
        if (session == nullptr) {
            auto response = ErrorResponse(request.request_id, code, message);
            response["session_id"] = request.session_id;
            return response;
        }
    }

    ordered_json context_before;
    if (!ReadPersistentContext(*session, context_before, message)) {
        return ErrorResponse(request.request_id, kErrSessionControl,
                             message);
    }

    if (request.expected_context_revision.has_value() &&
        static_cast<unsigned long long>(
            *request.expected_context_revision) != session->revision) {
        auto response = ErrorResponse(
            request.request_id, kErrContextRevisionMismatch,
            "expected_context_revision does not match the Session Context");
        response["session_id"] = session->session_id;
        response["session_state"] = KernelStateName(session->session->GetState());
        response["context_revision"] = session->revision;
        response["turn"] = session->turn;
        response["context_before"] = context_before;
        response["context_updated"] = false;
        return response;
    }

    const auto workflows_before =
        session->session->Workflows().Enumerate();

    auto runtime = std::make_unique<ak::runtime::Runtime>();
    runtime->RegisterCapability(
        kTestCapabilityId, kTestProviderId,
        [](const std::string& payload) -> std::string {
            return std::string(kEchoPrefix) + payload;
        });
    runtime->RegisterCapability(
        kParkingCapabilityId,
        bridge.has_value() ? kParkingCarlaProviderId : kParkingProviderId,
        [request_id = request.request_id,
         bridge](const std::string& payload) -> std::string {
            try {
                return RunParkingMove(payload, request_id, bridge);
            } catch (const std::exception& exc) {
                Log("parking.move execution failed request_id=" + request_id +
                    ": " + exc.what());
                throw;
            }
        });
    runtime->RegisterCapability(
        vln::autoware::kFollowTrajectoryCapabilityId,
        vln::autoware::kMockProviderId,
        [request_id = request.request_id](const std::string& payload)
            -> std::string {
            try {
                return vln::autoware::RunFollowTrajectory(payload, request_id);
            } catch (const std::exception& exc) {
                Log("autoware.follow_trajectory execution failed request_id=" +
                    request_id + ": " + exc.what());
                throw;
            }
        });

    ak::runtime_integration::RuntimeExecutionAuthorityHandle authority =
        ak::runtime_integration::IssueRuntimeExecutionAuthority(
            *runtime, *session->session, true);
    const ak::agent::RuntimeRequestId request_id(request.request_id);
    const ak::agent::RuntimeInvocationRequest invocation{
        request_id, request.capability_id, request.payload};
    const ak::agent::RuntimeSubmissionResult submission =
        authority.Port().Submit(invocation);
    const ak::agent::RuntimeObservation observation =
        authority.Port().Observe(request_id);

    std::optional<std::string> execution_status;
    if (const std::optional<ak::ExecutionResult> result =
            runtime->GetInvocationResult(request.request_id);
        result.has_value()) {
        execution_status = MapExecutionStatus(result->status);
    }
    runtime->Stop();

    std::string workflow_id_str;
    std::string task_id_str;
    const auto workflows_after = session->session->Workflows().Enumerate();
    if (workflows_after.size() > workflows_before.size()) {
        const ak::WorkflowID workflow_id = workflows_after.back();
        workflow_id_str = std::to_string(workflow_id.Value());
        if (ak::Workflow* wf = session->session->FindWorkflow(workflow_id)) {
            const auto tasks = wf->Tasks().Enumerate();
            if (!tasks.empty()) {
                task_id_str = std::to_string(tasks.back().Value());
            }
        }
    }

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
        const std::string failure = !submission.failure.empty()
                                        ? submission.failure
                                        : observation.failure;
        std::string error_code;
        if (submission.status == ak::agent::SubmissionStatus::kRejected) {
            error_code = kErrInvalidField;
        } else if (submission.status == ak::agent::SubmissionStatus::kFailed) {
            error_code = ClassifyFailure(submission.failure);
        } else {
            error_code = ClassifyFailure(observation.failure);
        }
        response["error"] =
            ordered_json{{"code", error_code}, {"message", failure}};
    }

    ordered_json output_json;
    bool output_parsed = false;
    bool carla_completed = false;
    if (response["output"].is_string()) {
        try {
            output_json =
                ordered_json::parse(response["output"].get<std::string>());
            output_parsed = true;
            carla_completed =
                output_json.value("status", "") == kParkingStatusCarlaCompleted &&
                output_json.contains("vehicle");
        } catch (const ordered_json::exception&) {
            output_parsed = false;
        }
    }
    const bool success =
        observation.status == ak::agent::ObservationStatus::kSuccess &&
        execution_status.has_value() && *execution_status == "completed" &&
        carla_completed;

    const std::uint64_t next_turn = session->turn + 1;
    ordered_json context;
    context["session_id"] = session->session_id;
    context["turn"] = next_turn;
    context["context_revision"] = session->revision + 1;
    context["phase"] = "execution";
    context["request_id"] = request.request_id;
    context["capability_id"] = request.capability_id;
    context["task_id"] = task_id_str.empty() ? ordered_json(nullptr)
                                             : ordered_json(task_id_str);
    context["workflow_id"] = workflow_id_str.empty()
                                 ? ordered_json(nullptr)
                                 : ordered_json(workflow_id_str);
    context["status"] =
        success ? "completed"
                : (submission.status ==
                           ak::agent::SubmissionStatus::kRejected
                       ? "rejected"
                       : "failed");
    context["execution_status"] =
        execution_status.has_value() ? ordered_json(*execution_status)
                                     : ordered_json(nullptr);
    context["observation_status"] = response["observation_status"];
    context["domain"] = request.domain;
    context["request"] = ParseJsonOrString(request.payload);
    context["real_carla_execution"] = carla_completed;
    if (output_parsed) {
        context["observation"] = output_json;
        context["bridge_status"] = output_json.value("status", "");
        if (output_json.contains("vehicle")) {
            const ordered_json& vehicle = output_json.at("vehicle");
            context["vehicle"] = vehicle;
            if (vehicle.contains("pre_state")) {
                context["pre_state"] = vehicle.at("pre_state");
            }
            if (vehicle.contains("post_state")) {
                context["post_state"] = vehicle.at("post_state");
            }
            if (vehicle.contains("moved_m")) {
                context["moved_m"] = vehicle.at("moved_m");
            }
            if (vehicle.contains("stop_reason")) {
                context["stop_reason"] = vehicle.at("stop_reason");
            }
        }
    }
    if (!response["error"].is_null()) {
        context["error"] = response["error"];
    }

    ordered_json execution_history;
    execution_history["kind"] = "execution";
    execution_history["turn"] = next_turn;
    execution_history["revision"] = session->revision + 1;
    execution_history["request_id"] = request.request_id;
    execution_history["capability_id"] = request.capability_id;
    execution_history["status"] = context["status"];
    execution_history["moved_m"] = context.contains("moved_m")
                                       ? context["moved_m"]
                                       : ordered_json(nullptr);
    execution_history["stop_reason"] = context.contains("stop_reason")
                                           ? context["stop_reason"]
                                           : ordered_json(nullptr);
    execution_history["pre_state"] = context.contains("pre_state")
                                         ? context["pre_state"]
                                         : ordered_json(nullptr);
    execution_history["post_state"] = context.contains("post_state")
                                          ? context["post_state"]
                                          : ordered_json(nullptr);
    if (!response["error"].is_null()) {
        execution_history["error"] = response["error"];
    }
    execution_history["domain"] = request.domain;
    context["history"] = AppendHistory(context_before, execution_history);

    bool context_updated =
        UpdatePersistentContext(*session, context, message);
    if (context_updated) {
        session->turn = next_turn;
    } else {
        response["observation_status"] = "failure";
        response["error"] = ordered_json{{"code", kErrContextUpdateFailed},
                                         {"message", message}};
    }

    AddSessionFields(response, *session, context_before,
                     context_updated ? context : ordered_json(nullptr),
                     task_id_str, workflow_id_str, context_updated);
    if (!context_updated) {
        response["context_revision"] = session->revision;
    }
    return response;
}

void CloseAllPersistentSessions() {
    for (auto& entry : g_sessions) {
        if (!entry.second || !entry.second->session) {
            continue;
        }
        try {
            if (entry.second->context) {
                (void)entry.second->context->Release().ReleaseObject(
                    entry.second->context_object_id);
            }
            entry.second->session->Shutdown();
            entry.second->session->Destroy();
            Log("closed persistent session at host shutdown session_id=" +
                entry.first);
        } catch (...) {
            Log("persistent session cleanup exception session_id=" +
                entry.first);
        }
    }
    g_sessions.clear();
}

ordered_json ExecuteViaKernel(
    const ValidatedRequest& request,
    const std::optional<CarlaBridgeConfig>& bridge) {
    if (!request.session_id.empty()) {
        return ExecutePersistentViaKernel(request, bridge);
    }
    // One Runtime per request: the Runtime lifecycle is one-shot.
    auto runtime = std::make_unique<ak::runtime::Runtime>();
    runtime->RegisterCapability(
        kTestCapabilityId, kTestProviderId,
        [](const std::string& payload) -> std::string {
            return std::string(kEchoPrefix) + payload;
        });
    // parking.move is registered on the Runtime like any other capability, so
    // it is reached only through the same submission/observation path. With a
    // configured CARLA bridge the invoker performs real execution; otherwise
    // it retains the frozen simulation-only stub behavior.
    runtime->RegisterCapability(
        kParkingCapabilityId,
        bridge.has_value() ? kParkingCarlaProviderId : kParkingProviderId,
        [request_id = request.request_id,
         bridge](const std::string& payload) -> std::string {
            try {
                return RunParkingMove(payload, request_id, bridge);
            } catch (const std::exception& exc) {
                Log("parking.move execution failed request_id=" + request_id +
                    ": " + exc.what());
                throw;
            }
        });
    // autoware.follow_trajectory is registered on the same Runtime and reached
    // through the same submit/observe/authorization path. The invoker is a
    // contract adapter with a deterministic mock backend; it does not connect
    // to ROS 2, Autoware, CARLA or a vehicle.
    runtime->RegisterCapability(
        vln::autoware::kFollowTrajectoryCapabilityId,
        vln::autoware::kMockProviderId,
        [request_id = request.request_id](const std::string& payload)
            -> std::string {
            try {
                return vln::autoware::RunFollowTrajectory(payload, request_id);
            } catch (const std::exception& exc) {
                Log("autoware.follow_trajectory execution failed request_id=" +
                    request_id + ": " + exc.what());
                throw;
            }
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
ordered_json HandleRequestLine(
    const std::string& line,
    const std::optional<CarlaBridgeConfig>& bridge) {
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

    if (request.capability_id == kPlannerPlanCapabilityId) {
        return HandlePlannerPlan(request);
    }

    if (request.capability_id == kSessionCreateCapabilityId ||
        request.capability_id == kSessionGetCapabilityId ||
        request.capability_id == kSessionCloseCapabilityId) {
        return HandleSessionControl(request);
    }

    if (request.capability_id == kSessionContextUpdateCapabilityId) {
        return HandleSessionContextUpdate(request);
    }

    return ExecuteViaKernel(request, bridge);
}

}  // namespace

int main() {
#if defined(_WIN32)
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif

    const CarlaBridgeLoad bridge_load = LoadCarlaBridgeConfig();
    if (bridge_load.configured && !bridge_load.valid) {
        // Fail closed: never silently fall back to the simulation stub when a
        // CARLA bridge was explicitly configured but is unusable.
        Log("fatal: invalid CARLA execution bridge configuration: " +
            bridge_load.error);
        return 3;
    }
    const std::optional<CarlaBridgeConfig> bridge =
        bridge_load.valid
            ? std::optional<CarlaBridgeConfig>(bridge_load.config)
            : std::nullopt;
    if (bridge.has_value()) {
        Log("carla execution bridge configured at " + bridge->host + ":" +
            std::to_string(bridge->port));
    } else {
        Log("no CARLA execution bridge configured; parking.move uses the "
            "simulation stub");
    }

    const vln::taichu::PlannerBridgeLoad planner_load =
        vln::taichu::LoadPlannerBridgeConfig();
    if (planner_load.configured && !planner_load.valid) {
        Log("fatal: invalid Taichu planner bridge configuration: " +
            planner_load.error);
        return 4;
    }
    if (planner_load.valid) {
        std::string planner_message;
        if (!InitializePlanner(planner_load, planner_message)) {
            Log("fatal: Taichu planner initialization failed: " +
                planner_message);
            return 4;
        }
        Log("Taichu planner bridge configured at " + planner_load.config.host +
            ":" + std::to_string(planner_load.config.port));
    } else {
        Log("no Taichu planner bridge configured; planner.plan is unavailable");
    }

    Log("ready (kernel host; real Agent-Kernel runtime integration)");

    while (true) {
        const LineReadResult line = ReadBoundedLine(std::cin);
        if (line.drain_exceeded) {
            Log("fatal: oversize line exceeded drain cap; exiting");
            ShutdownPlanner();
            CloseAllPersistentSessions();
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
        WriteResponse(HandleRequestLine(line.bytes, bridge));
    }

    Log("stdin closed; exiting");
    ShutdownPlanner();
    CloseAllPersistentSessions();
    return 0;
}
