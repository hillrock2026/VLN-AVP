// ============================================================
// Agent Kernel - Capability Contract (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapter 13 - Tool-owned capability contract.
//
// CapabilityContract represents capability identity, input
// contract, output contract, constraints, metadata,
// availability, permission information, Provider association,
// and compatibility requirements.
//
// Runtime Contract Isolation (TOL-036): CapabilityContract
// SHALL NOT define Runtime scheduling, Runtime capability
// resolution, Runtime lifecycle, Runtime event semantics,
// Runtime execution semantics, or Runtime object ownership.
//
// NON-responsibilities:
// - This contract is Tool-owned capability information only.
// ============================================================

#pragma once

#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/tool/tool_capability.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::tool {

// Tool-owned permission requirements (Chapter 13).
struct PermissionContract {
    std::vector<std::string> required_permissions;  // Tool-owned permission requirements
    std::string policy_scope;                       // Tool-owned scope description
};

// The canonical Tool-owned capability contract (Chapter 13).
// Immutable value type.
class CapabilityContract {
public:
    CapabilityId capability_id;
    CapabilityInputContract input;
    CapabilityOutputContract output;
    CapabilityConstraintSet constraints;
    CapabilityMetadata metadata;
    CapabilityAvailability availability;
    PermissionContract permissions;
    ProviderId provider;
    std::string compatibility;

    CapabilityContract(CapabilityId capability_id_value,
                       CapabilityInputContract input_value,
                       CapabilityOutputContract output_value,
                       CapabilityConstraintSet constraints_value,
                       CapabilityMetadata metadata_value,
                       CapabilityAvailability availability_value,
                       PermissionContract permissions_value,
                       ProviderId provider_value,
                       std::string compatibility_value)
        : capability_id(std::move(capability_id_value)),
          input(std::move(input_value)),
          output(std::move(output_value)),
          constraints(std::move(constraints_value)),
          metadata(std::move(metadata_value)),
          availability(availability_value),
          permissions(std::move(permissions_value)),
          provider(std::move(provider_value)),
          compatibility(std::move(compatibility_value)) {}
};

}  // namespace ak::tool