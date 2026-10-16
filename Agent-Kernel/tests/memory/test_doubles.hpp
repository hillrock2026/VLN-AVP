// ============================================================
// test_doubles.hpp - P1-IS003 Memory test doubles
// ============================================================
// Phase 2 test doubles for Memory providers and extensions.
// The doubles carry no Memory lifecycle/state reference: they
// cannot own Memory state and cannot coordinate peers.
//
// This file intentionally includes NO Runtime header and NO
// Agent/Context/Planner/Tool header.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>

#include <agent_kernel/memory/memory.hpp>

namespace ak::memory {
namespace test {

// ------------------------------------------------------------
// Memory extension double
// ------------------------------------------------------------
class MemoryExtensionDouble : public IMemoryExtension {
public:
    MemoryExtensionDouble(std::string name, MemoryExtensionVersion version,
                          MemoryExtensionDomain domain = MemoryExtensionDomain::kMemory,
                          bool self_check = true)
        : name_(std::move(name)),
          version_(version),
          domain_(domain),
          self_check_(self_check) {}

    ~MemoryExtensionDouble() noexcept override = default;

    std::string_view Name() const noexcept override { return name_; }
    MemoryExtensionDomain Domain() const noexcept override { return domain_; }
    MemoryExtensionVersion Version() const noexcept override { return version_; }
    bool SelfCheck() const noexcept override { return self_check_; }

private:
    std::string name_;
    MemoryExtensionVersion version_;
    MemoryExtensionDomain domain_;
    bool self_check_;
};

// ------------------------------------------------------------
// Failing provider - returns provider-level failures on demand
// ------------------------------------------------------------
class FailingMemoryProvider : public IMemoryProvider {
public:
    FailingMemoryProvider(bool fail_store, bool fail_load, bool fail_remove)
        : fail_store_(fail_store),
          fail_load_(fail_load),
          fail_remove_(fail_remove) {}

    ~FailingMemoryProvider() noexcept override = default;

    ProviderResult StoreObject(MemoryObjectId, std::string_view,
                               const MemoryMetadata&) override {
        if (fail_store_) {
            return {ProviderStatus::kFailure, "provider store failure"};
        }
        return {ProviderStatus::kSuccess, "stored"};
    }

    ProviderResult LoadObject(MemoryObjectId, std::string&,
                              MemoryMetadata&) override {
        if (fail_load_) {
            return {ProviderStatus::kFailure, "provider load failure"};
        }
        return {ProviderStatus::kSuccess, "loaded"};
    }

    ProviderResult RemoveObject(MemoryObjectId) override {
        if (fail_remove_) {
            return {ProviderStatus::kFailure, "provider remove failure"};
        }
        return {ProviderStatus::kSuccess, "removed"};
    }

    std::string_view TechnologyName() const noexcept override {
        return "failing";
    }

private:
    bool fail_store_;
    bool fail_load_;
    bool fail_remove_;
};

// ------------------------------------------------------------
// Recording provider - records calls below the service boundary
// ------------------------------------------------------------
class RecordingMemoryProvider : public IMemoryProvider {
public:
    RecordingMemoryProvider() = default;
    ~RecordingMemoryProvider() noexcept override = default;

    ProviderResult StoreObject(MemoryObjectId id, std::string_view content,
                               const MemoryMetadata& metadata) override {
        ++store_calls;
        stored_[id] = {std::string(content), metadata};
        return {ProviderStatus::kSuccess, "stored"};
    }

    ProviderResult LoadObject(MemoryObjectId id, std::string& out_content,
                              MemoryMetadata& out_metadata) override {
        ++load_calls;
        const auto it = stored_.find(id);
        if (it == stored_.end()) {
            return {ProviderStatus::kNotFound, "not present"};
        }
        out_content = it->second.first;
        out_metadata = it->second.second;
        return {ProviderStatus::kSuccess, "loaded"};
    }

    ProviderResult RemoveObject(MemoryObjectId id) override {
        ++remove_calls;
        stored_.erase(id);
        return {ProviderStatus::kSuccess, "removed"};
    }

    std::string_view TechnologyName() const noexcept override {
        return "recording";
    }

    std::size_t store_calls = 0;
    std::size_t load_calls = 0;
    std::size_t remove_calls = 0;

private:
    std::unordered_map<MemoryObjectId, std::pair<std::string, MemoryMetadata>>
        stored_;
};

// ------------------------------------------------------------
// Helpers
// ------------------------------------------------------------

// Drives Memory to the fully available state:
// lifecycle Registered->Initializing->Active and operational
// Unavailable->Ready->Available.
inline bool ActivateAndMakeAvailable(Memory& memory) {
    return memory.InitializeLifecycle().IsSuccess() &&
           memory.CompleteInitialization().IsSuccess() &&
           memory.MarkReady().IsSuccess() &&
           memory.MarkAvailable().IsSuccess();
}

inline MemoryMetadata MakeMetadata(const char* name, std::uint64_t version = 1) {
    MemoryMetadata metadata;
    metadata.core.name = name;
    metadata.version = version;
    metadata.classification = "test";
    return metadata;
}

}  // namespace test
}  // namespace ak::memory