#include <agent_kernel/object_id.hpp>
#include <sstream>

namespace ak {

KernelObjectID::KernelObjectID(ValueType value) noexcept : value_(value) {}

std::string KernelObjectID::ToString() const {
    return std::to_string(value_);
}

KernelObjectID::ValueType KernelObjectID::Value() const noexcept {
    return value_;
}

}  // namespace ak

namespace std {
size_t hash<ak::KernelObjectID>::operator()(const ak::KernelObjectID& id) const noexcept {
    return hash<ak::KernelObjectID::ValueType>()(id.Value());
}
size_t hash<ak::SessionID>::operator()(const ak::SessionID& id) const noexcept {
    return hash<ak::KernelObjectID::ValueType>()(id.Value());
}
size_t hash<ak::WorkflowID>::operator()(const ak::WorkflowID& id) const noexcept {
    return hash<ak::KernelObjectID::ValueType>()(id.Value());
}
size_t hash<ak::TaskID>::operator()(const ak::TaskID& id) const noexcept {
    return hash<ak::KernelObjectID::ValueType>()(id.Value());
}
}  // namespace std


