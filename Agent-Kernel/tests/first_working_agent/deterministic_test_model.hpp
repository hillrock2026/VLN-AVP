// ============================================================
// deterministic_test_model.hpp - First Working Agent Sprint
// ============================================================
// TEST ONLY (TASK 6 Rev2 §12, §28). Deterministic Model double:
// maps a fixed prompt expectation to a fixed ModelAction
// sequence. Never compiled into a production target (OBS-03).
//
// FWA-T7 / TASK-6-Rev2 / STEP-08 / AC-006
// ============================================================

#pragma once

#include <cstddef>
#include <string>

#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::agent {
namespace test {

// Behavior modes of the deterministic test model.
enum class DeterministicModelMode {
    kToolThenComplete,  // FWA-001: kToolInvoke, then kComplete after the
                        // tool observation reaches the Context -> Prompt material
    kInvalid,           // FWA-002: kInvalid with a stable reason
    kCompleteFirst,     // FWA-004: kComplete on the first call
    kAlwaysTool         // max-cycles exhaustion verification
};

// Deterministic Model boundary double (TEST ONLY).
class DeterministicTestModel {
public:
    DeterministicTestModel(ak::tool::CapabilityId capability,
                           std::string arguments,
                           DeterministicModelMode mode,
                           std::string invalid_reason =
                               "model output is not interpretable")
        : capability_(std::move(capability)),
          arguments_(std::move(arguments)),
          mode_(mode),
          invalid_reason_(std::move(invalid_reason)) {}

    // Marker written by the deterministic test executor; when it
    // reaches the Prompt material, the model completes.
    static constexpr const char* kToolResultMarker = "[tool-result]";

    ak::agent::ModelAction operator()(const ak::prompt::PromptResult& result) {
        last_prompt_material_.clear();
        for (const ak::prompt::AssembledComponent& component :
             result.Components()) {
            last_prompt_material_ += component.content;
        }
        ++call_count_;
        switch (mode_) {
            case DeterministicModelMode::kInvalid:
                return ak::agent::ModelAction::Invalid(invalid_reason_);
            case DeterministicModelMode::kCompleteFirst:
                return ak::agent::ModelAction::Complete();
            case DeterministicModelMode::kAlwaysTool:
                return ak::agent::ModelAction::InvokeTool(capability_,
                                                          arguments_);
            case DeterministicModelMode::kToolThenComplete:
                if (last_prompt_material_.find(kToolResultMarker) !=
                    std::string::npos) {
                    return ak::agent::ModelAction::Complete();
                }
                return ak::agent::ModelAction::InvokeTool(capability_,
                                                          arguments_);
        }
        return ak::agent::ModelAction::Invalid("unknown deterministic model mode");
    }

    [[nodiscard]] std::size_t call_count() const noexcept { return call_count_; }
    [[nodiscard]] const std::string& last_prompt_material() const noexcept {
        return last_prompt_material_;
    }

private:
    ak::tool::CapabilityId capability_;
    std::string arguments_;
    DeterministicModelMode mode_;
    std::string invalid_reason_;
    std::size_t call_count_ = 0;
    std::string last_prompt_material_;
};

}  // namespace test
}  // namespace ak::agent
