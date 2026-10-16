// ============================================================
// Agent Kernel - Tool Capability (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapter 12 - Tool Capability Contract.
//
// ToolCapability is the canonical Tool-owned capability
// representation (TOL-032). Every capability has a unique
// CapabilityId within its owning Tool (TOL-033). A published
// ToolCapability is immutable: capability modification SHALL
// occur through Tool-owned mutation operations that replace
// the published value (TOL-034).
//
// Tool capability SHALL NOT be represented as a Runtime
// capability (TOL-035): ToolCapability and CapabilityAvailability
// are Tool-owned information and never express Runtime
// execution readiness.
//
// NON-responsibilities:
// - No type here references Runtime, Scheduler, Executor,
//   CapabilityResolver, EventBus, Workflow, or Task.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::tool {

// Tool-owned input contract description (Chapter 12.3).
struct CapabilityInputContract {
    std::string schema;  // Tool-owned input contract description
    std::string format;  // e.g. "json"
    std::string description;
};

// Tool-owned output contract description (Chapter 12.4).
struct CapabilityOutputContract {
    std::string schema;  // Tool-owned output contract description
    std::string format;  // e.g. "json"
    std::string description;
};

// Tool-owned constraint conditions (Chapter 12.5).
struct CapabilityConstraintSet {
    std::vector<std::string> constraints;  // Tool-owned constraint conditions
    bool constrained = false;  // true when a Tool-owned condition constrains the capability
};

// Tool-owned capability metadata (Chapter 12.6).
struct CapabilityMetadata {
    std::string name;
    std::string author;
    std::vector<std::string> tags;
    std::string notes;
};

// Tool-owned availability information (Chapter 12.7).
// It SHALL NOT represent Runtime execution readiness.
enum class CapabilityAvailability : std::uint8_t {
    kAvailable = 0,
    kConstrained,
    kUnavailable
};

// The canonical Tool capability object (Chapter 12.2).
// Immutable value type: once published by the Tool root, no
// member SHALL mutate.
class ToolCapability {
public:
    CapabilityId id;
    std::string description;
    std::string category;
    CapabilityInputContract input;
    CapabilityOutputContract output;
    CapabilityConstraintSet constraints;
    CapabilityMetadata metadata;
    CapabilityAvailability availability;
    ProviderId provider;
    std::string version;

    ToolCapability(CapabilityId id_value,
                   std::string description_value,
                   std::string category_value,
                   CapabilityInputContract input_value,
                   CapabilityOutputContract output_value,
                   CapabilityConstraintSet constraints_value,
                   CapabilityMetadata metadata_value,
                   CapabilityAvailability availability_value,
                   ProviderId provider_value,
                   std::string version_value)
        : id(std::move(id_value)),
          description(std::move(description_value)),
          category(std::move(category_value)),
          input(std::move(input_value)),
          output(std::move(output_value)),
          constraints(std::move(constraints_value)),
          metadata(std::move(metadata_value)),
          availability(availability_value),
          provider(std::move(provider_value)),
          version(std::move(version_value)) {}
};

}  // namespace ak::tool