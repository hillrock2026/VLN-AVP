#include <agent_kernel/foundation/kernel_observer.hpp>
#include <algorithm>
#include <vector>

namespace ak {

ObserverRegistry::ObserverRegistry(ObserverRegistry&&) noexcept = default;
ObserverRegistry& ObserverRegistry::operator=(ObserverRegistry&&) noexcept = default;

void ObserverRegistry::Attach(std::shared_ptr<KernelObserver> observer) {
    observers_.push_back(std::move(observer));
}

void ObserverRegistry::Detach(KernelObserver* observer) {
    observers_.erase(
        std::remove_if(observers_.begin(), observers_.end(),
            [observer](const std::weak_ptr<KernelObserver>& wp) {
                return wp.lock().get() == observer;
            }),
        observers_.end());
}

void ObserverRegistry::NotifyStateChange(uint64_t objectId, uint8_t newState) {
    for (auto& wp : observers_) {
        if (auto sp = wp.lock()) {
            sp->OnStateChanged(objectId, newState);
        }
    }
}

void ObserverRegistry::NotifyError(uint64_t objectId, uint8_t state,
                                    const char* message) {
    for (auto& wp : observers_) {
        if (auto sp = wp.lock()) {
            sp->OnError(objectId, state, message);
        }
    }
}

}  // namespace ak
