// ============================================================
// taichu_planning_engine.hpp - Kernel IPlanningEngine over the Taichu bridge
// ============================================================
// The engine is deliberately a planner boundary only: it forwards one already
// validated planning input to the Python planner bridge (which reuses the
// existing ZDTaichuServerBackend) and returns the bridge's raw model response
// as the Kernel PlanningOutcome artifact. It never executes a vehicle, never
// validates a route and never turns a model failure into a successful plan.

#pragma once

#include <string>

#include <agent_kernel/planner/planning_engine.hpp>

namespace vln::taichu {

struct PlannerBridgeConfig {
    std::string host;
    int port = 0;
    std::string token;
    int timeout_ms = 180000;
};

struct PlannerBridgeLoad {
    bool configured = false;
    bool valid = false;
    PlannerBridgeConfig config;
    std::string error;
};

// Reads VLN_TAICHU_PLANNER_BRIDGE, VLN_TAICHU_PLANNER_TOKEN and
// VLN_TAICHU_PLANNER_TIMEOUT_MS. No endpoint/token is invented.
PlannerBridgeLoad LoadPlannerBridgeConfig();

class TaichuPlanningEngine final : public ak::planner::IPlanningEngine {
public:
    explicit TaichuPlanningEngine(PlannerBridgeConfig config);

    [[nodiscard]] bool HasOutcome(
        const ak::planner::PlannerSessionId& session_id,
        const ak::planner::PlanningRequestId& request_id) const noexcept override;

    [[nodiscard]] ak::planner::PlanningOutcome Outcome(
        const ak::planner::PlannerSessionId& session_id,
        const ak::planner::PlanningRequest& request) noexcept override;

private:
    PlannerBridgeConfig config_;
};

}  // namespace vln::taichu
