// ============================================================
// model_result_interpreter.cpp - TASK 3.4
// ============================================================
// Deterministic Agent-owned ModelResult -> ModelAction
// interpretation (TASK 3.4 Contract section 6; Implementation
// Plan section 11.2).
//
// Domain: kSuccess / kInvalidResult ONLY (M-001).
// ModelResult::kFailure is NOT an interpreter input: the
// composition Status() gate intercepts it before interpretation,
// so no ModelAction of any kind is produced on the Model-failure
// path and no Runtime invocation occurs. The defensive
// non-success fallback at the end of this function exists only
// for direct misuse of the free function; the composition
// guarantees the Model-failure path never reaches it.
// ============================================================

#include <agent_kernel/model_to_runtime/model_result_interpreter.hpp>

#include <cstddef>
#include <stdexcept>
#include <string>
#include <string_view>

#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::model_to_runtime {

ak::agent::ModelAction InterpretModelResult(
    const ak::model::ModelResult& result) {
    // kInvalidResult -> deterministic Agent rejection
    // (invalid / unsupported / malformed / no-action input
    // interpretation problem; NOT a Model inference failure).
    if (result.IsInvalidResult()) {
        return ak::agent::ModelAction::Invalid(result.Diagnostic());
    }

    // kSuccess -> payload-driven deterministic interpretation.
    if (result.IsSuccess() && result.Payload().has_value()) {
        const std::string& payload = result.Payload().value();

        if (payload == "complete") {
            return ak::agent::ModelAction::Complete();
        }

        constexpr std::string_view kToolPrefix = "tool:";
        if (payload.rfind(kToolPrefix, 0) != 0) {
            return ak::agent::ModelAction::Invalid(
                "unsupported-model-output");
        }

        const std::size_t capability_begin = kToolPrefix.size();
        const std::size_t capability_end = payload.find(':', capability_begin);
        if (capability_end == std::string::npos) {
            return ak::agent::ModelAction::Invalid("malformed-tool-output");
        }
        const std::string capability =
            payload.substr(capability_begin, capability_end - capability_begin);
        const std::string arguments = payload.substr(capability_end + 1);
        if (capability.empty() || arguments.empty()) {
            return ak::agent::ModelAction::Invalid("malformed-tool-output");
        }
        try {
            return ak::agent::ModelAction::InvokeTool(
                ak::tool::CapabilityId(capability), arguments);
        } catch (const std::invalid_argument&) {
            return ak::agent::ModelAction::Invalid(
                "invalid-capability-identity");
        }
    }

    // Defensive fallback for direct misuse only (M-001): a
    // non-success status other than kInvalidResult must never be
    // routed here by the composition Status() gate. The branch
    // never fabricates an action and never executes anything.
    return ak::agent::ModelAction::Invalid("invalid-model-result");
}

}  // namespace ak::model_to_runtime