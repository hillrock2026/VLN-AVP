#include <agent_kernel/session/session_builder.hpp>
#include <agent_kernel/session.hpp>

namespace ak {

SessionBuilder& SessionBuilder::WithID(SessionID id) noexcept {
    id_ = id;
    return *this;
}

SessionBuilder& SessionBuilder::WithName(const std::string& name) {
    config_.name = name;
    return *this;
}

SessionBuilder& SessionBuilder::WithMaxWorkflows(std::uint32_t maxWorkflows) noexcept {
    config_.maxWorkflows = maxWorkflows;
    return *this;
}

std::unique_ptr<Session> SessionBuilder::Build() {
    auto id = id_.value_or(SessionID(static_cast<SessionID::ValueType>(std::rand())));
    return std::make_unique<Session>(id, std::move(config_));
}

}  // namespace ak