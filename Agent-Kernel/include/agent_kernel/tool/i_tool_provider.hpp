// ============================================================
// Agent Kernel - IToolProvider (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapter 14 - Tool Provider abstraction.
//
// A Provider is subordinate to Tool ownership (TOL-037).
// DescribeCapabilities() and PrepareInvocation() are pure
// description/preparation operations; they SHALL NOT execute
// the capability, submit Runtime work, or mutate Tool state
// (TOL-038).
//
// The Tool root SHALL invoke Provider callbacks OUTSIDE the
// Tool-owned synchronization domain (TOL-106).
//
// NON-responsibilities:
// - IToolProvider SHALL NOT expose Execute/Run/Schedule/
//   CompleteTask/ResolveRuntimeCapability/PublishRuntimeEvent
//   or any equivalent Runtime execution operation.
// ============================================================

#pragma once

#include <vector>

#include <agent_kernel/tool/tool_capability.hpp>
#include <agent_kernel/tool/tool_identity.hpp>
#include <agent_kernel/tool/tool_result.hpp>

namespace ak::tool {

struct InvocationRequest;  // defined in tool.hpp (TOL-090)

// The canonical Tool Provider abstraction (Chapter 14).
class IToolProvider {
public:
    virtual ~IToolProvider() = default;

    [[nodiscard]] virtual ProviderId Id() const noexcept = 0;

    [[nodiscard]] virtual std::vector<ToolCapability> DescribeCapabilities() const = 0;

    [[nodiscard]] virtual bool IsAvailable() const noexcept = 0;

    [[nodiscard]] virtual InvocationPreparationResult PrepareInvocation(
        const CapabilityId& capability,
        const InvocationRequest& request) const = 0;
};

}  // namespace ak::tool