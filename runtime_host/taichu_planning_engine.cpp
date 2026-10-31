#include "taichu_planning_engine.hpp"

#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>

#if !defined(_WIN32)
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#endif

#include <nlohmann/json.hpp>

namespace vln::taichu {

namespace {

using nlohmann::ordered_json;

constexpr const char* kBridgeEndpointEnv = "VLN_TAICHU_PLANNER_BRIDGE";
constexpr const char* kBridgeTokenEnv = "VLN_TAICHU_PLANNER_TOKEN";
constexpr const char* kBridgeTimeoutEnv = "VLN_TAICHU_PLANNER_TIMEOUT_MS";
constexpr int kDefaultTimeoutMs = 180000;
constexpr int kMaxTimeoutMs = 600000;
constexpr std::size_t kMaxResponseBytes = 2u * 1024u * 1024u;
constexpr const char* kProtocolVersion = "1";

bool IsNonBlank(const std::string& value) {
    for (const char c : value) {
        if (c != ' ' && c != '\t' && c != '\n' && c != '\r') {
            return true;
        }
    }
    return false;
}

int ParseTimeout(const char* text, int fallback) {
    if (text == nullptr || *text == '\0') {
        return fallback;
    }
    try {
        std::size_t consumed = 0;
        const int value = std::stoi(std::string(text), &consumed);
        if (consumed != std::strlen(text) || value < 1 ||
            value > kMaxTimeoutMs) {
            return -1;
        }
        return value;
    } catch (const std::exception&) {
        return -1;
    }
}

ordered_json FailurePayload(const std::string& type,
                            const std::string& message) {
    ordered_json payload;
    payload["status"] = "failed";
    payload["error"] = ordered_json{{"type", type}, {"message", message}};
    return payload;
}

#if !defined(_WIN32)
int ConnectBridge(const PlannerBridgeConfig& config) {
    addrinfo hints{};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* results = nullptr;
    const std::string port_text = std::to_string(config.port);
    const int lookup =
        getaddrinfo(config.host.c_str(), port_text.c_str(), &hints, &results);
    if (lookup != 0) {
        throw std::runtime_error(std::string("planner bridge: cannot resolve: ") +
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
            "planner bridge: cannot connect to " + config.host + ":" +
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
            throw std::runtime_error(std::string("planner bridge: send failed: ") +
                                     std::strerror(errno));
        }
        sent += static_cast<std::size_t>(written);
    }
}

std::string ReadLine(int fd) {
    std::string received;
    char buffer[4096];
    while (received.find('\n') == std::string::npos) {
        const ssize_t count = recv(fd, buffer, sizeof(buffer), 0);
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw std::runtime_error(
                std::string("planner bridge: receive failed: ") +
                std::strerror(errno));
        }
        if (count == 0) {
            throw std::runtime_error(
                "planner bridge: closed before returning a result");
        }
        received.append(buffer, static_cast<std::size_t>(count));
        if (received.size() > kMaxResponseBytes) {
            throw std::runtime_error(
                "planner bridge: response exceeds the size limit");
        }
    }
    return received.substr(0, received.find('\n'));
}
#endif

ordered_json CallBridge(const PlannerBridgeConfig& config,
                        const ordered_json& request) {
#if defined(_WIN32)
    (void)config;
    (void)request;
    throw std::runtime_error(
        "planner bridge is not supported by this Windows host build");
#else
    const int fd = ConnectBridge(config);
    try {
        std::string line = request.dump();
        line.push_back('\n');
        SendAll(fd, line);
        const std::string response_line = ReadLine(fd);
        close(fd);
        return ordered_json::parse(response_line);
    } catch (...) {
        close(fd);
        throw;
    }
#endif
}

ordered_json BuildBridgeRequest(
    const PlannerBridgeConfig& config,
    const ak::planner::PlannerSessionId& planner_session_id,
    const ak::planner::PlanningRequest& request) {
    ordered_json input;
    try {
        input = ordered_json::parse(request.goal);
    } catch (const ordered_json::exception&) {
        throw std::runtime_error("planning goal is not valid JSON");
    }
    if (!input.is_object()) {
        throw std::runtime_error("planning goal must be a JSON object");
    }
    for (const char* key : {"image_path", "instruction"}) {
        if (!input.contains(key) || !input.at(key).is_string() ||
            input.at(key).get<std::string>().empty()) {
            throw std::runtime_error(std::string("planning input is missing ") +
                                     key);
        }
    }
    ordered_json request_json;
    request_json["protocol_version"] = kProtocolVersion;
    request_json["request_id"] = request.request_id.Value() != 0
                                     ? std::to_string(request.request_id.Value())
                                     : "planner-request";
    request_json["planner_session_id"] =
        std::to_string(planner_session_id.Value());
    request_json["session_id"] =
        input.value("session_id", std::string(""));
    request_json["context_revision"] =
        input.value("context_revision", ordered_json(nullptr));
    request_json["context"] =
        input.value("context", ordered_json::object());
    request_json["image_path"] = input.at("image_path");
    request_json["instruction"] = input.at("instruction");
    request_json["domain"] = input.value("domain", ordered_json::object());
    request_json["token"] = config.token;
    return request_json;
}

ak::planner::PlanningOutcome SuccessOutcome(const ordered_json& payload) {
    ak::planner::PlanningOutcome outcome;
    outcome.status = ak::planner::PlanningOutcomeStatus::kSuccess;
    outcome.metadata.version = 1;
    outcome.metadata.strategy = "taichu";
    outcome.metadata.annotations.push_back("real_taichu_http_bridge");
    outcome.execution_plan_steps.push_back("taichu.plan");
    outcome.artifact_payload = payload.dump();
    outcome.message = "taichu planning transport completed";
    return outcome;
}

}  // namespace

PlannerBridgeLoad LoadPlannerBridgeConfig() {
    PlannerBridgeLoad load;
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
            load.error = std::string(kBridgeEndpointEnv) +
                         " has a non-numeric port";
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
    const int timeout_ms =
        ParseTimeout(std::getenv(kBridgeTimeoutEnv), kDefaultTimeoutMs);
    if (timeout_ms < 1) {
        load.error = std::string(kBridgeTimeoutEnv) + " is not a valid timeout";
        return load;
    }
    load.config = PlannerBridgeConfig{host, port, std::string(token), timeout_ms};
    load.valid = true;
    return load;
}

TaichuPlanningEngine::TaichuPlanningEngine(PlannerBridgeConfig config)
    : config_(std::move(config)) {}

bool TaichuPlanningEngine::HasOutcome(
    const ak::planner::PlannerSessionId&,
    const ak::planner::PlanningRequestId&) const noexcept {
    // The bridge call is synchronous; the outcome is available at the first
    // completion attempt. The Host remains single-threaded.
    return true;
}

ak::planner::PlanningOutcome TaichuPlanningEngine::Outcome(
    const ak::planner::PlannerSessionId& session_id,
    const ak::planner::PlanningRequest& request) noexcept {
    try {
        const ordered_json request_json =
            BuildBridgeRequest(config_, session_id, request);
        ordered_json reply = CallBridge(config_, request_json);
        if (!reply.is_object()) {
            return SuccessOutcome(
                FailurePayload("BridgeProtocolError",
                               "planner bridge response must be an object"));
        }
        if (reply.contains("request_id") && reply.at("request_id").is_string() &&
            reply.at("request_id").get<std::string>() !=
                request_json.at("request_id").get<std::string>()) {
            return SuccessOutcome(
                FailurePayload("BridgeProtocolError",
                               "planner bridge request_id mismatch"));
        }
        return SuccessOutcome(reply);
    } catch (const std::exception& error) {
        return SuccessOutcome(
            FailurePayload("PlannerBridgeError", error.what()));
    } catch (...) {
        return SuccessOutcome(
            FailurePayload("PlannerBridgeError", "unknown planner bridge failure"));
    }
}

}  // namespace vln::taichu
