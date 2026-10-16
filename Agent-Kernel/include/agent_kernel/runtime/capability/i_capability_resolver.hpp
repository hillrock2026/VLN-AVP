// ============================================================
// Agent Kernel - ICapabilityResolver
// ============================================================
// Capability Resolver interface.
//
// Converts TaskExecutionDescriptor into ExecutionBinding.
// Answers: Which Runtime capability should execute this Task?
//
// Design principles:
// - Uses value types only (no Core Domain pointers)
// - Stateless between calls
// - Does not execute capabilities (Executor responsibility)
// - Does not manage Plugin lifecycle (Plugin Runtime responsibility)
//
// AK0023 Chapter 11 - API Contract
// ============================================================

#pragma once

#include <memory>
#include <string>

#include <agent_kernel/task/task_execution_descriptor.hpp>
#include <agent_kernel/runtime/capability/capability_resolution_result.hpp>
#include <agent_kernel/runtime/capability/execution_binding.hpp>

namespace ak {

// ============================================================
// ICapabilityResolver
// ============================================================
class ICapabilityResolver {
public:
    virtual ~ICapabilityResolver() noexcept = default;

    // Resolve a TaskExecutionDescriptor into an ExecutionBinding.
    [[nodiscard]] virtual CapabilityResolution Resolve(
        const TaskExecutionDescriptor& descriptor) = 0;

    // Check if the resolver supports a given capability name.
    [[nodiscard]] virtual bool Supports(
        const std::string& capabilityName) const = 0;

    // Validate that a descriptor can be resolved without
    // performing the full resolution.
    [[nodiscard]] virtual bool Validate(
        const TaskExecutionDescriptor& descriptor) const = 0;

    // Lifecycle control.
    virtual void Initialize() = 0;
    virtual void Shutdown() = 0;
};

}  // namespace ak