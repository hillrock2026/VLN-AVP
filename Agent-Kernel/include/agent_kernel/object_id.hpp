// ============================================================
// Agent Kernel 鈥?KernelObjectID
// ============================================================
// Immutable identity for all Kernel Objects.
//
// KernelObjectID is a value type assigned at object creation
// and never modified. It supports comparison, hashing, and
// string serialization.
//
// Each Kernel Object type (Session, Workflow, Task) has a
// typed ID to prevent accidental cross-type assignment.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <functional>

namespace ak {

// ============================================================
// KernelObjectID 鈥?base identity type
// ============================================================
class KernelObjectID {
public:
    using ValueType = std::uint64_t;

    KernelObjectID() noexcept = default;
    explicit KernelObjectID(ValueType value) noexcept;

    // Comparison
    auto operator<=>(const KernelObjectID&) const = default;

    // Serialization
    [[nodiscard]] std::string ToString() const;

    // Access
    [[nodiscard]] ValueType Value() const noexcept;

private:
    ValueType value_;
};

// ============================================================
// Typed IDs 鈥?type-safe specializations
// ============================================================
class SessionID : public KernelObjectID {
    using KernelObjectID::KernelObjectID;
};

class WorkflowID : public KernelObjectID {
    using KernelObjectID::KernelObjectID;
};

class TaskID : public KernelObjectID {
    using KernelObjectID::KernelObjectID;
};

}  // namespace ak

// ============================================================
// std::hash specialization
// ============================================================
namespace std {
template <>
struct hash<ak::KernelObjectID> {
    size_t operator()(const ak::KernelObjectID& id) const noexcept;
};

template <>
struct hash<ak::SessionID> {
    size_t operator()(const ak::SessionID& id) const noexcept;
};

template <>
struct hash<ak::WorkflowID> {
    size_t operator()(const ak::WorkflowID& id) const noexcept;
};

template <>
struct hash<ak::TaskID> {
    size_t operator()(const ak::TaskID& id) const noexcept;
};
}  // namespace std

