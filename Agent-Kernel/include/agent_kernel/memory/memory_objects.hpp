// ============================================================
// Agent Kernel - MemoryObjects (Memory boundary)
// ============================================================
// Memory-owned object model representations.
//
// P1-IS003 scope (Chapter 7 - Memory Objects, Chapter 16):
// - MemoryDomain is a logical partition of retained knowledge;
//     no fixed taxonomy is required.
// - MemoryObject is opaque at the architectural boundary; its
//     internal representation is implementation-specific.
// - MemoryEntry belongs to exactly one Domain and references
//     exactly one Memory Object.
// - MemoryMetadata is extensible and implementation-
//     independent.
// - MemoryReference carries only architectural identity; it
//     never exposes database ids, addresses, indexes, or
//     provider handles.
//
// NON-responsibilities:
// - These are Memory-owned value representations; they do not
//   coordinate peers and reference no Runtime type.
// - No C++ inheritance is implied by the object model.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/memory/memory_identity.hpp>

namespace ak::memory {

// ------------------------------------------------------------
// MemoryMetadata - extensible, implementation-independent
// ------------------------------------------------------------
struct MemoryMetadata {
    // Neutral core (Foundation value mechanics only).
    ak::KernelMetadata core;
    // Version identifier.
    std::uint64_t version = 1;
    // Optional classification.
    std::string classification;
    // Optional retention policy.
    std::string retention_policy;
    // Extensible, implementation-independent annotations.
    std::vector<std::string> annotations;

    // Structural equality for verification (field-wise).
    [[nodiscard]] bool operator==(const MemoryMetadata& other) const noexcept;
    [[nodiscard]] bool operator!=(const MemoryMetadata& other) const noexcept {
        return !(*this == other);
    }
};

// ------------------------------------------------------------
// MemoryDomain - logical knowledge partition
// ------------------------------------------------------------
class MemoryDomain {
public:
    MemoryDomain() = default;
    MemoryDomain(MemoryDomainId id, std::string name, MemoryMetadata metadata)
        : id_(id), name_(std::move(name)), metadata_(std::move(metadata)) {}

    [[nodiscard]] MemoryDomainId GetId() const noexcept { return id_; }
    [[nodiscard]] const std::string& GetName() const noexcept { return name_; }
    [[nodiscard]] const MemoryMetadata& GetMetadata() const noexcept {
        return metadata_;
    }

private:
    MemoryDomainId id_;
    std::string name_;
    MemoryMetadata metadata_;

    friend class MemoryService;
};

// ------------------------------------------------------------
// MemoryObject - opaque unit of retained knowledge
// ------------------------------------------------------------
class MemoryObject {
public:
    MemoryObject() = default;
    MemoryObject(MemoryObjectId id, std::string content, MemoryMetadata metadata)
        : id_(id), content_(std::move(content)), metadata_(std::move(metadata)) {}

    [[nodiscard]] MemoryObjectId GetId() const noexcept { return id_; }
    [[nodiscard]] const MemoryMetadata& GetMetadata() const noexcept {
        return metadata_;
    }

    // Read-only view of the implementation-specific content.
    // External consumers cannot mutate the retained object.
    [[nodiscard]] const std::string& Content() const noexcept { return content_; }

private:
    MemoryObjectId id_;
    std::string content_;
    MemoryMetadata metadata_;

    friend class MemoryService;
};

// ------------------------------------------------------------
// MemoryEntry - belongs to one Domain, references one Object
// ------------------------------------------------------------
class MemoryEntry {
public:
    MemoryEntry() = default;
    MemoryEntry(MemoryEntryId id, MemoryDomainId domain, MemoryObjectId object,
                MemoryMetadata metadata)
        : id_(id),
          domain_(domain),
          object_(object),
          metadata_(std::move(metadata)) {}

    [[nodiscard]] MemoryEntryId GetId() const noexcept { return id_; }
    [[nodiscard]] MemoryDomainId GetDomainId() const noexcept { return domain_; }
    [[nodiscard]] MemoryObjectId GetObjectId() const noexcept { return object_; }
    [[nodiscard]] const MemoryMetadata& GetMetadata() const noexcept {
        return metadata_;
    }

private:
    MemoryEntryId id_;
    MemoryDomainId domain_;
    MemoryObjectId object_;
    MemoryMetadata metadata_;

    friend class MemoryService;
};

// ------------------------------------------------------------
// MemoryReference - implementation-independent object reference
// ------------------------------------------------------------
class MemoryReference {
public:
    MemoryReference() = default;
    MemoryReference(MemoryDomainId domain, MemoryObjectId object) noexcept
        : domain_(domain), object_(object) {}

    [[nodiscard]] MemoryDomainId GetDomainId() const noexcept { return domain_; }
    [[nodiscard]] MemoryObjectId GetObjectId() const noexcept { return object_; }

    // Implementation independence: no storage id, address,
    // index, or provider handle is exposed.
    [[nodiscard]] bool IsValid() const noexcept {
        return domain_.IsValid() && object_.IsValid();
    }

private:
    MemoryDomainId domain_;
    MemoryObjectId object_;
};

}  // namespace ak::memory