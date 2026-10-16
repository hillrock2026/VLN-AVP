// ============================================================
// Agent Kernel - KernelMetadata (Foundation Layer)
// ============================================================
// Neutral descriptive metadata representation.
//
// P1-IS001 Kernel Foundation scope:
// - KernelMetadata is a value type that may be composed into
//   owner-specific representations for human-readable
//   identification and categorization.
// - Metadata carries no runtime behavior and no architectural
//   semantics.
//
// NON-responsibilities (P1-IS001):
// - KernelMetadata is NOT Memory, Context, Planner, Tool, or
//   Runtime-owned semantic state.
// - It does NOT own or redefine any architectural state model.
// - It does NOT grant architectural ownership to the object
//   that composes it.
// ============================================================

#pragma once

#include <chrono>
#include <string>
#include <vector>

namespace ak {

// ============================================================
// KernelMetadata
// ============================================================
struct KernelMetadata {
    // Human-readable name (e.g., "Agent-42", "DataFetchTask")
    std::string name;

    // Short label for UI/log display
    std::string label;

    // Optional description
    std::string description;

    // Categorization tags for filtering and discovery
    std::vector<std::string> tags;

    // Creation timestamp
    std::chrono::system_clock::time_point creationTime;

    // Future: key-value properties map for extensibility
    // std::unordered_map<std::string, std::string> properties;
};

}  // namespace ak