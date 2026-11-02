// ============================================================
// autoware_adapter.cpp - contract validation + mock execution
// ============================================================
// The adapter is deliberately a narrow translation layer:
//
//   payload JSON -> validation -> FollowTrajectoryRequest
//     -> FollowTrajectoryBackend (mock here)
//     -> structured capability output JSON
//
// It creates no Runtime, registry, event bus, scheduler, authorization path,
// ROS 2 transport, or background task system. The Host owns the Runtime and
// the sanctioned authorization path. The mock result is marked as mock.
// ============================================================

#include "autoware_adapter.h"

#include <cmath>
#include <cstddef>
#include <initializer_list>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace vln::autoware {
namespace {

using ordered_json = nlohmann::ordered_json;

constexpr const char* kContractVersion = "1";
constexpr const char* kOutputVersion = "1";
constexpr const char* kExecutionMode = "mock";
constexpr std::size_t kMaxPoints = 256;
constexpr std::size_t kMaxTaskIdBytes = 128;
constexpr double kMaxTimeoutS = 30.0;
constexpr double kMaxSpeedMps = 30.0;
constexpr double kPi = 3.14159265358979323846;

struct ValidationFailure {
    std::string reason;
    std::string detail;
};

bool IsFiniteNumber(const ordered_json& value) {
    return value.is_number() && std::isfinite(value.get<double>());
}

bool IsNonBlankString(const ordered_json& value) {
    return value.is_string() && !value.get<std::string>().empty() &&
           value.get<std::string>().find_first_not_of(" \t\r\n") !=
               std::string::npos;
}

bool HasExactKeys(const ordered_json& object,
                  std::initializer_list<const char*> keys) {
    if (!object.is_object() || object.size() != keys.size()) {
        return false;
    }
    for (const char* key : keys) {
        if (!object.contains(key)) {
            return false;
        }
    }
    return true;
}

bool HasOnlyKeys(const ordered_json& object,
                 std::initializer_list<const char*> required,
                 std::initializer_list<const char*> optional) {
    if (!object.is_object()) {
        return false;
    }
    for (auto it = object.begin(); it != object.end(); ++it) {
        const std::string key = it.key();
        bool allowed = false;
        for (const char* candidate : required) {
            if (key == candidate) {
                allowed = true;
                break;
            }
        }
        if (!allowed) {
            for (const char* candidate : optional) {
                if (key == candidate) {
                    allowed = true;
                    break;
                }
            }
        }
        if (!allowed) {
            return false;
        }
    }
    return true;
}

std::optional<ValidationFailure> ValidatePoint(const ordered_json& point,
                                               std::size_t index,
                                               double previous_timestamp,
                                               double timeout_s,
                                               TrajectoryPoint& out) {
    if (!HasExactKeys(point, {"x", "y", "heading_rad", "speed_mps",
                              "timestamp_s"})) {
        return ValidationFailure{
            "invalid_point",
            "point[" + std::to_string(index) +
                "] must have exactly x, y, heading_rad, speed_mps, timestamp_s"};
    }
    for (const char* key : {"x", "y", "heading_rad", "speed_mps",
                            "timestamp_s"}) {
        if (!IsFiniteNumber(point.at(key))) {
            return ValidationFailure{
                "non_finite_value",
                "point[" + std::to_string(index) + "]." + key +
                    " must be a finite number"};
        }
    }
    out.x = point.at("x").get<double>();
    out.y = point.at("y").get<double>();
    out.heading_rad = point.at("heading_rad").get<double>();
    out.speed_mps = point.at("speed_mps").get<double>();
    out.timestamp_s = point.at("timestamp_s").get<double>();
    if (out.heading_rad < -kPi || out.heading_rad > kPi) {
        return ValidationFailure{
            "invalid_heading",
            "point[" + std::to_string(index) +
                "].heading_rad must be in [-pi, pi]"};
    }
    if (out.speed_mps < 0.0 || out.speed_mps > kMaxSpeedMps) {
        return ValidationFailure{
            "invalid_speed",
            "point[" + std::to_string(index) +
                "].speed_mps must be in [0, 30]"};
    }
    if (out.timestamp_s < 0.0 || out.timestamp_s <= previous_timestamp) {
        return ValidationFailure{
            "non_monotonic_time",
            "point[" + std::to_string(index) +
                "].timestamp_s must be non-negative and strictly increasing"};
    }
    if (out.timestamp_s > timeout_s) {
        return ValidationFailure{
            "trajectory_duration_exceeds_timeout",
            "point[" + std::to_string(index) +
                "].timestamp_s exceeds timeout_s"};
    }
    return std::nullopt;
}

std::optional<ValidationFailure> ValidateRequest(
    const ordered_json& root, FollowTrajectoryRequest& out,
    std::optional<std::string>& task_id) {
    if (!root.is_object()) {
        return ValidationFailure{"invalid_json", "payload root must be an object"};
    }
    if (!HasOnlyKeys(root,
                     {"contract_version", "task_id", "operation",
                      "trajectory", "vehicle_state", "timeout_s"},
                     {"mock_mode"})) {
        return ValidationFailure{
            "unknown_field",
            "top-level fields must be contract_version, task_id, operation, "
            "trajectory, vehicle_state, timeout_s and optional mock_mode"};
    }
    for (const char* key : {"contract_version", "task_id", "operation",
                            "trajectory", "vehicle_state", "timeout_s"}) {
        if (!root.contains(key)) {
            return ValidationFailure{"missing_field",
                                     std::string("missing ") + key};
        }
    }
    if (!root.at("contract_version").is_string() ||
        root.at("contract_version").get<std::string>() != kContractVersion) {
        return ValidationFailure{"invalid_contract_version",
                                 "contract_version must be the string \"1\""};
    }
    if (!IsNonBlankString(root.at("task_id"))) {
        return ValidationFailure{"invalid_task_id",
                                 "task_id must be a non-blank string"};
    }
    const std::string task_id_value = root.at("task_id").get<std::string>();
    if (task_id_value.size() > kMaxTaskIdBytes) {
        return ValidationFailure{"invalid_task_id",
                                 "task_id exceeds 128 bytes"};
    }
    out.task_id = task_id_value;
    task_id = task_id_value;

    if (!root.at("operation").is_string()) {
        return ValidationFailure{"invalid_operation",
                                 "operation must be a string"};
    }
    const std::string operation = root.at("operation").get<std::string>();
    if (operation != "execute") {
        return ValidationFailure{
            "unsupported_operation",
            "operation '" + operation +
                "' is not supported by the synchronous capability; stop/cancel "
                "must be handled outside this adapter"};
    }

    if (!IsFiniteNumber(root.at("timeout_s"))) {
        return ValidationFailure{"invalid_timeout",
                                 "timeout_s must be a finite number"};
    }
    out.timeout_s = root.at("timeout_s").get<double>();
    if (out.timeout_s <= 0.0 || out.timeout_s > kMaxTimeoutS) {
        return ValidationFailure{"invalid_timeout",
                                 "timeout_s must be in (0, 30]"};
    }

    if (!HasExactKeys(root.at("trajectory"), {"frame_id", "points"})) {
        return ValidationFailure{
            "invalid_trajectory",
            "trajectory must contain exactly frame_id and points"};
    }
    const ordered_json& trajectory = root.at("trajectory");
    if (!IsNonBlankString(trajectory.at("frame_id"))) {
        return ValidationFailure{"invalid_frame_id",
                                 "trajectory.frame_id must be non-blank"};
    }
    out.frame_id = trajectory.at("frame_id").get<std::string>();
    if (!trajectory.at("points").is_array()) {
        return ValidationFailure{"empty_trajectory",
                                 "trajectory.points must be an array"};
    }
    const ordered_json& points = trajectory.at("points");
    if (points.size() < 2) {
        return ValidationFailure{"empty_trajectory",
                                 "trajectory.points needs at least two points"};
    }
    if (points.size() > kMaxPoints) {
        return ValidationFailure{"too_many_points",
                                 "trajectory.points exceeds 256 points"};
    }
    out.points.reserve(points.size());
    double previous_timestamp = -1.0;
    for (std::size_t i = 0; i < points.size(); ++i) {
        TrajectoryPoint point;
        if (const auto failure =
                ValidatePoint(points.at(i), i, previous_timestamp,
                              out.timeout_s, point)) {
            return failure;
        }
        previous_timestamp = point.timestamp_s;
        out.points.push_back(point);
    }

    if (!HasExactKeys(root.at("vehicle_state"),
                      {"frame_id", "x", "y", "heading_rad", "speed_mps"})) {
        return ValidationFailure{
            "invalid_vehicle_state",
            "vehicle_state must contain exactly frame_id, x, y, heading_rad, "
            "speed_mps"};
    }
    const ordered_json& vehicle = root.at("vehicle_state");
    if (!IsNonBlankString(vehicle.at("frame_id"))) {
        return ValidationFailure{"invalid_vehicle_state",
                                 "vehicle_state.frame_id must be non-blank"};
    }
    for (const char* key : {"x", "y", "heading_rad", "speed_mps"}) {
        if (!IsFiniteNumber(vehicle.at(key))) {
            return ValidationFailure{
                "non_finite_value",
                std::string("vehicle_state.") + key +
                    " must be a finite number"};
        }
    }
    out.vehicle_state.frame_id = vehicle.at("frame_id").get<std::string>();
    out.vehicle_state.x = vehicle.at("x").get<double>();
    out.vehicle_state.y = vehicle.at("y").get<double>();
    out.vehicle_state.heading_rad =
        vehicle.at("heading_rad").get<double>();
    out.vehicle_state.speed_mps = vehicle.at("speed_mps").get<double>();
    if (out.vehicle_state.heading_rad < -kPi ||
        out.vehicle_state.heading_rad > kPi) {
        return ValidationFailure{"invalid_heading",
                                 "vehicle_state.heading_rad must be in [-pi, pi]"};
    }
    if (out.vehicle_state.speed_mps < 0.0 ||
        out.vehicle_state.speed_mps > kMaxSpeedMps) {
        return ValidationFailure{"invalid_speed",
                                 "vehicle_state.speed_mps must be in [0, 30]"};
    }
    if (out.vehicle_state.frame_id != out.frame_id) {
        return ValidationFailure{"frame_mismatch",
                                 "trajectory.frame_id and "
                                 "vehicle_state.frame_id must match"};
    }

    out.mock_mode = "complete";
    if (root.contains("mock_mode")) {
        if (!root.at("mock_mode").is_string()) {
            return ValidationFailure{"invalid_mock_mode",
                                     "mock_mode must be a string"};
        }
        const std::string mode = root.at("mock_mode").get<std::string>();
        if (mode != "complete" && mode != "fail" && mode != "timeout" &&
            mode != "exception") {
            return ValidationFailure{
                "invalid_mock_mode",
                "mock_mode must be complete, fail, timeout or exception"};
        }
        out.mock_mode = mode;
    }
    return std::nullopt;
}

FollowTrajectoryResult Rejected(const std::string& reason,
                                const std::string& detail) {
    FollowTrajectoryResult result;
    result.state = "rejected";
    result.accepted = false;
    result.reason_code = reason;
    result.diagnostics = detail;
    result.state_history = {"rejected"};
    result.backend_called = false;
    return result;
}

std::string BuildOutput(const FollowTrajectoryResult& result,
                        const std::optional<std::string>& task_id,
                        const std::string& request_id) {
    ordered_json out;
    out["output_version"] = kOutputVersion;
    out["state"] = result.state;
    out["accepted"] = result.accepted;
    out["task_id"] = task_id.has_value() ? ordered_json(*task_id)
                                         : ordered_json(nullptr);
    out["request_id"] = request_id;
    out["reason_code"] = result.reason_code;
    out["diagnostics"] = result.diagnostics;
    out["state_history"] = ordered_json::array();
    for (const std::string& state : result.state_history) {
        out["state_history"].push_back(state);
    }
    out["backend_called"] = result.backend_called;
    out["execution_mode"] = kExecutionMode;
    out["mock"] = true;
    if (result.has_execution) {
        ordered_json execution;
        execution["mock"] = true;
        execution["points_executed"] = result.points_executed;
        execution["trajectory_duration_s"] =
            result.trajectory_duration_s;
        execution["tracking_error_m"] = result.tracking_error_m;
        if (result.timeout_s > 0.0) {
            execution["timeout_s"] = result.timeout_s;
        }
        out["execution"] = std::move(execution);
    } else {
        out["execution"] = nullptr;
    }
    return out.dump();
}

class MockFollowTrajectoryBackend final : public FollowTrajectoryBackend {
public:
    FollowTrajectoryResult Execute(
        const FollowTrajectoryRequest& request) override {
        FollowTrajectoryResult result;
        result.accepted = true;
        result.backend_called = true;
        result.state_history = {"accepted", "running"};
        if (request.mock_mode == "fail") {
            result.state = "failed";
            result.reason_code = "mock_backend_failed";
            result.diagnostics =
                "mock backend returned a deterministic failure; no real "
                "Autoware execution";
            result.state_history.push_back("failed");
            return result;
        }
        if (request.mock_mode == "timeout") {
            result.state = "failed";
            result.reason_code = "timeout";
            result.diagnostics =
                "mock backend reached timeout_s; no real Autoware execution";
            result.state_history.push_back("failed");
            result.has_execution = true;
            result.timeout_s = request.timeout_s;
            return result;
        }
        if (request.mock_mode == "exception") {
            throw std::runtime_error(
                "mock backend exception: simulated transport failure");
        }
        result.state = "completed";
        result.reason_code = "mock_completed";
        result.diagnostics =
            "mock backend completed; no real Autoware/ROS 2/vehicle/CARLA "
            "execution";
        result.state_history.push_back("completed");
        result.has_execution = true;
        result.points_executed = request.points.size();
        result.trajectory_duration_s =
            request.points.back().timestamp_s -
            request.points.front().timestamp_s;
        result.tracking_error_m = 0.0;
        return result;
    }
};

}  // namespace

FollowTrajectoryAdapter::FollowTrajectoryAdapter(
    FollowTrajectoryBackend& backend)
    : backend_(backend) {}

std::string FollowTrajectoryAdapter::Run(const std::string& payload,
                                         const std::string& request_id) {
    std::optional<std::string> task_id;
    ordered_json root;
    try {
        root = ordered_json::parse(payload);
    } catch (const ordered_json::exception&) {
        return BuildOutput(
            Rejected("invalid_json", "payload is not valid JSON"),
            task_id, request_id);
    }
    if (root.is_object() && root.contains("task_id") &&
        root.at("task_id").is_string()) {
        task_id = root.at("task_id").get<std::string>();
    }

    FollowTrajectoryRequest request;
    if (const auto failure = ValidateRequest(root, request, task_id)) {
        return BuildOutput(Rejected(failure->reason, failure->detail),
                           task_id, request_id);
    }

    FollowTrajectoryResult result;
    try {
        result = backend_.Execute(request);
    } catch (const std::exception& exc) {
        result = FollowTrajectoryResult{};
        result.state = "failed";
        result.accepted = true;
        result.reason_code = "backend_exception";
        result.diagnostics =
            std::string("backend exception: ") + exc.what();
        result.state_history = {"accepted", "running", "failed"};
        result.backend_called = true;
    } catch (...) {
        result = FollowTrajectoryResult{};
        result.state = "failed";
        result.accepted = true;
        result.reason_code = "backend_exception";
        result.diagnostics = "backend exception: unknown exception";
        result.state_history = {"accepted", "running", "failed"};
        result.backend_called = true;
    }
    return BuildOutput(result, task_id, request_id);
}

std::string RunFollowTrajectory(const std::string& payload,
                                const std::string& request_id) {
    MockFollowTrajectoryBackend backend;
    FollowTrajectoryAdapter adapter(backend);
    return adapter.Run(payload, request_id);
}

}  // namespace vln::autoware
