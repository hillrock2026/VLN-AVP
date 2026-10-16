// ============================================================
// Agent Kernel — SessionBuilder
// ============================================================
// Lightweight builder for constructing Session instances.
//
// SessionBuilder abstracts Session construction complexity
// without exposing internal initialization details. It is
// NOT a runtime component — it only configures structural
// properties before the Session is created.
//
// SessionBuilder does NOT:
// - Initialize runtime subsystems
// - Create Scheduler or Executor
// - Register services
// - Start any execution
//
// Usage:
//   auto session = SessionBuilder()
//       .WithID(SessionID::Generate())
//       .WithName("MySession")
//       .WithMaxWorkflows(100)
//       .Build();
// ============================================================

#pragma once

#include <memory>
#include <string>
#include <cstdint>
#include <optional>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/session/session_configuration.hpp>

namespace ak {

// Forward declaration
class Session;

// ============================================================
// SessionBuilder
// ============================================================
class SessionBuilder {
public:
    SessionBuilder() noexcept = default;

    // -- Identity --
    SessionBuilder& WithID(SessionID id) noexcept;
    SessionBuilder& WithName(const std::string& name);

    // -- Capacity --
    SessionBuilder& WithMaxWorkflows(std::uint32_t maxWorkflows) noexcept;

    // -- Metadata (future) --
    // SessionBuilder& WithDescription(const std::string& desc);
    // SessionBuilder& WithTags(std::vector<std::string> tags);

    // -- Build --
    [[nodiscard]] std::unique_ptr<Session> Build();

private:
    std::optional<SessionID> id_;
    SessionConfiguration config_;
};

}  // namespace ak
