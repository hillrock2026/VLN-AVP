// ============================================================
// autoware_adapter.h - minimal Autoware follow-trajectory boundary
// ============================================================
// This is a capability invoker boundary, not a Kernel replacement:
//
//   Host IPC -> Agent-Kernel Runtime -> registered invoker
//     -> FollowTrajectoryAdapter (validation/translation)
//     -> FollowTrajectoryBackend (mock now; real ROS 2 later)
//
// The adapter validates a versioned JSON contract and returns a structured
// JSON result. The mock backend is explicitly marked as mock; it does not
// claim that Autoware, ROS 2, a vehicle, or CARLA moved anything.
// ============================================================

#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace vln::autoware {

constexpr const char* kFollowTrajectoryCapabilityId =
    "autoware.follow_trajectory";
constexpr const char* kMockProviderId = "vln.autoware.mock";

struct TrajectoryPoint {
    double x = 0.0;
    double y = 0.0;
    double heading_rad = 0.0;
    double speed_mps = 0.0;
    double timestamp_s = 0.0;
};

struct VehicleState {
    std::string frame_id;
    double x = 0.0;
    double y = 0.0;
    double heading_rad = 0.0;
    double speed_mps = 0.0;
};

struct FollowTrajectoryRequest {
    std::string task_id;
    std::string frame_id;
    std::vector<TrajectoryPoint> points;
    VehicleState vehicle_state;
    double timeout_s = 0.0;
    // Mock-only selector. A real backend may ignore it.
    std::string mock_mode;
};

struct FollowTrajectoryResult {
    std::string state;             // completed | failed | rejected
    bool accepted = false;
    std::string reason_code;
    std::string diagnostics;
    std::vector<std::string> state_history;
    bool backend_called = false;
    bool has_execution = false;
    std::size_t points_executed = 0;
    double trajectory_duration_s = 0.0;
    double tracking_error_m = 0.0;
    double timeout_s = 0.0;
};

class FollowTrajectoryBackend {
public:
    virtual ~FollowTrajectoryBackend() = default;
    virtual FollowTrajectoryResult Execute(
        const FollowTrajectoryRequest& request) = 0;
};

class FollowTrajectoryAdapter {
public:
    explicit FollowTrajectoryAdapter(FollowTrajectoryBackend& backend);

    // Returns a compact JSON capability output string. Invalid input is a
    // structured rejected result; backend failures are structured failed
    // results. The adapter does not throw for expected input/backend errors.
    std::string Run(const std::string& payload, const std::string& request_id);

private:
    FollowTrajectoryBackend& backend_;
};

// Host-facing convenience entry point. It constructs a fresh mock backend and
// adapter for one invocation. The Host remains the only authorization path.
std::string RunFollowTrajectory(const std::string& payload,
                                const std::string& request_id);

}  // namespace vln::autoware
