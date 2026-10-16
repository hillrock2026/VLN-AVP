// ============================================================
// test_doubles.hpp - P1-IS004 Context test doubles
// ============================================================
// Phase 2 test doubles for Context extensions. The doubles
// carry no Context lifecycle/state reference: they cannot own
// Context state and cannot coordinate peers.
//
// This file intentionally includes NO Runtime header and NO
// Agent/Memory/Planner/Tool header.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_extensions.hpp>

namespace ak::context {
namespace test {

// ------------------------------------------------------------
// Context extension double
// ------------------------------------------------------------
class ContextExtensionDouble : public IContextExtension {
public:
    ContextExtensionDouble(std::string name, ContextExtensionVersion version,
                           ContextExtensionDomain domain =
                               ContextExtensionDomain::kContext,
                           bool self_check = true)
        : name_(std::move(name)),
          version_(version),
          domain_(domain),
          self_check_(self_check) {}

    ~ContextExtensionDouble() noexcept override = default;

    std::string_view Name() const noexcept override { return name_; }
    ContextExtensionDomain Domain() const noexcept override { return domain_; }
    ContextExtensionVersion Version() const noexcept override { return version_; }
    bool SelfCheck() const noexcept override { return self_check_; }

private:
    std::string name_;
    ContextExtensionVersion version_;
    ContextExtensionDomain domain_;
    bool self_check_;
};

// ------------------------------------------------------------
// Helpers
// ------------------------------------------------------------

inline ContextMetadata MakeMetadata(const char* name,
                                    std::uint64_t version = 1) {
    ContextMetadata metadata;
    metadata.core.name = name;
    metadata.version = version;
    metadata.classification = "test";
    return metadata;
}

// Drives a Context Object to the fully active state through the
// Context-owned service boundary:
// lifecycle Created->Initialized->Active and operational
// Uninitialized->Ready->Active.
inline bool CreateAndActivate(Context& context, ContextObjectId id,
                              const char* category = "working_state") {
    if (!context.Creation()
             .CreateObject(id, category, "payload", MakeMetadata("obj"))
             .IsSuccess()) {
        return false;
    }
    return context.Creation().InitializeObject(id).IsSuccess() &&
           context.Creation().ActivateObject(id).IsSuccess();
}

}  // namespace test
}  // namespace ak::context
