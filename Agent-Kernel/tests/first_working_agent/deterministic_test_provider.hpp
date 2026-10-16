// ============================================================
// deterministic_test_provider.hpp - First Working Agent Sprint
// ============================================================
// TEST ONLY (TASK 6 Rev2 §19.2, §28; TASK 6.2 Review OBS-002).
// Deterministic Tool provider double that satisfies the
// production ak::tool::IToolProvider contract and registers the
// FWA capability. It is TEST-SCOPED and MUST NOT be written as,
// or promoted to, a production Tool provider implementation.
//
// FWA-T7 / TASK-6-Rev2 / STEP-09 / AC-008 / AC-009
// ============================================================

#pragma once

#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/tool/i_tool_provider.hpp>
#include <agent_kernel/tool/tool_capability.hpp>
#include <agent_kernel/tool/tool_identity.hpp>
#include <agent_kernel/tool/tool_result.hpp>

namespace ak::agent {
namespace test {

// Deterministic Tool provider double (TEST ONLY).
class DeterministicTestProvider final : public ak::tool::IToolProvider {
public:
    DeterministicTestProvider(std::string provider_id,
                              std::string capability_id,
                              bool report_unavailable = false)
        : provider_id_(std::move(provider_id)),
          capability_id_(std::move(capability_id)),
          report_unavailable_(report_unavailable) {
        capabilities_.push_back(MakeCapability());
    }

    ak::tool::ProviderId Id() const noexcept override { return provider_id_; }

    std::vector<ak::tool::ToolCapability> DescribeCapabilities()
        const override {
        return capabilities_;
    }

    bool IsAvailable() const noexcept override { return !report_unavailable_; }

    ak::tool::InvocationPreparationResult PrepareInvocation(
        const ak::tool::CapabilityId& capability,
        const ak::tool::InvocationRequest& request) const override {
        (void)request;
        if (report_unavailable_) {
            return {ak::tool::InvocationPreparationStatus::kUnavailable,
                    capability, provider_id_, "",
                    "deterministic provider reports unavailable"};
        }
        if (capability == capability_id_) {
            return {ak::tool::InvocationPreparationStatus::kPrepared,
                    capability, provider_id_, "fwa-prepared-token",
                    "deterministic provider prepared"};
        }
        return {ak::tool::InvocationPreparationStatus::kNotFound, capability,
                provider_id_, "", "capability not provided"};
    }

private:
    ak::tool::ToolCapability MakeCapability() const {
        ak::tool::CapabilityInputContract input{"schema-input", "json",
                                                "input description"};
        ak::tool::CapabilityOutputContract output{"schema-output", "json",
                                                  "output description"};
        ak::tool::CapabilityConstraintSet constraints;
        ak::tool::CapabilityMetadata metadata{"fwa-capability", "fwa-author",
                                              {"fwa"}, "fwa notes"};
        return ak::tool::ToolCapability(
            capability_id_, "description", "category", input, output,
            constraints, metadata,
            ak::tool::CapabilityAvailability::kAvailable, provider_id_,
            "1.0");
    }

    ak::tool::ProviderId provider_id_;
    ak::tool::CapabilityId capability_id_;
    bool report_unavailable_ = false;
    std::vector<ak::tool::ToolCapability> capabilities_;
};

}  // namespace test
}  // namespace ak::agent
