// ============================================================
// Agent Kernel - MemoryProvider (Memory boundary)
// ============================================================
// Memory Provider abstraction.
//
// P1-IS003 scope (Chapter 11 - Provider Abstraction, Chapter
// 16.1):
// - A Provider is an implementation abstraction that realizes
//     Memory Services below the Memory architectural boundary.
// - Providers SHALL NOT own Memory lifecycle, mutate Memory
//     operational state, coordinate peers, or access Runtime.
// - Provider failure returns provider-level information to
//     Memory; Memory decides the Memory-owned consequence.
// - Provider technology does not define Memory architectural
//     identity.
//
// NON-responsibilities:
// - Provider results never expose storage keys, addresses, or
//   internal structures (the interface uses architectural
//   object identity only).
// - No provider becomes a Memory coordinator or a Runtime
//   adapter.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>

#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/memory/memory_objects.hpp>

namespace ak::memory {

// Provider-level outcome. Provider code returns provider-level
// failure information only; Memory translates it into
// Memory-owned results and operational-state consequences.
enum class ProviderStatus : std::uint8_t {
    kSuccess = 0,
    kNotFound,
    kFailure
};

struct ProviderResult {
    ProviderStatus status = ProviderStatus::kFailure;
    const char* message = "";

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == ProviderStatus::kSuccess;
    }
};

class IMemoryProvider {
public:
    virtual ~IMemoryProvider() noexcept = default;

    // Stores the provider-mediated representation of an object.
    virtual ProviderResult StoreObject(MemoryObjectId id,
                                       std::string_view content,
                                       const MemoryMetadata& metadata) = 0;

    // Loads the provider-mediated representation of an object.
    virtual ProviderResult LoadObject(MemoryObjectId id,
                                      std::string& out_content,
                                      MemoryMetadata& out_metadata) = 0;

    // Removes the provider-mediated representation of an object.
    virtual ProviderResult RemoveObject(MemoryObjectId id) = 0;

    // Implementation technology name (e.g., "in-process"). The
    // technology is a mechanism, not Memory architectural
    // identity.
    [[nodiscard]] virtual std::string_view TechnologyName() const noexcept = 0;
};

// Minimal in-process provider for tests and minimal Phase 2
// operation. It holds no Memory references: it cannot own
// Memory lifecycle or state and cannot coordinate peers.
class InProcessMemoryProvider : public IMemoryProvider {
public:
    InProcessMemoryProvider() = default;

    ProviderResult StoreObject(MemoryObjectId id, std::string_view content,
                               const MemoryMetadata& metadata) override;
    ProviderResult LoadObject(MemoryObjectId id, std::string& out_content,
                              MemoryMetadata& out_metadata) override;
    ProviderResult RemoveObject(MemoryObjectId id) override;

    [[nodiscard]] std::string_view TechnologyName() const noexcept override {
        return "in-process";
    }

    [[nodiscard]] std::size_t StoredCount() const noexcept { return objects_.size(); }

private:
    struct StoredObject {
        std::string content;
        MemoryMetadata metadata;
    };

    std::unordered_map<MemoryObjectId, StoredObject> objects_;
};

}  // namespace ak::memory