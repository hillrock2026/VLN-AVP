#pragma once

// ============================================================
// P0R0001 — Runtime Lifecycle Manager
// ============================================================

#include <string>
#include <runtime_state_machine.h>
#include <runtime_configuration.h>

namespace ak::runtime {

class RuntimeLifecycleManager {
public:
    explicit RuntimeLifecycleManager(RuntimeStateMachine& stateMachine) noexcept;

    RuntimeLifecycleManager(const RuntimeLifecycleManager&) = delete;
    RuntimeLifecycleManager& operator=(const RuntimeLifecycleManager&) = delete;
    RuntimeLifecycleManager(RuntimeLifecycleManager&&) = delete;
    RuntimeLifecycleManager& operator=(RuntimeLifecycleManager&&) = delete;

    [[nodiscard]] bool Initialize() noexcept;
    void Shutdown() noexcept;
    void Fail(const std::string& reason) noexcept;
    [[nodiscard]] const std::string& GetFailureReason() const noexcept;
    [[nodiscard]] bool HasFailed() const noexcept;

private:
    RuntimeStateMachine& stateMachine_;
    std::string failureReason_;
    bool hasFailed_;
};

}  // namespace ak::runtime