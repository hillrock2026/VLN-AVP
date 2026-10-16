// ============================================================
// Agent Kernel - KernelRegistry (Foundation Layer)
// ============================================================
// Owner-scoped registration mechanics.
//
// P1-IS001 Kernel Foundation scope:
// - OwnerScopedRegistry is a generic container that ONE
//   architectural owner instantiates inside its own boundary
//   to register and look up its own values by key.
// - Registration is mechanical containment. It does NOT
//   transfer architectural ownership to the registry: the
//   owning subsystem remains the architectural owner of the
//   registered values and controls their lifecycle.
//
// NON-responsibilities (P1-IS001):
// - OwnerScopedRegistry is NOT a Runtime Capability Resolver:
//   it has no capability, binding, or resolution semantics.
// - It is NOT a coordinator of multiple subsystems.
// - It is NOT a universal architectural object repository.
// - It is NOT a global mutable registry or service locator.
// ============================================================

#pragma once

#include <cstddef>
#include <memory>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ak {

// ============================================================
// OwnerScopedRegistry
// ============================================================
// Key must be equality-comparable and hashable (std::hash).
// Value is stored under mechanical containment
// (std::unique_ptr) on behalf of the owning subsystem.
template <typename Key, typename Value>
class OwnerScopedRegistry {
public:
    using KeyType = Key;
    using ValueType = Value;

    OwnerScopedRegistry() = default;
    ~OwnerScopedRegistry() noexcept = default;

    OwnerScopedRegistry(const OwnerScopedRegistry&) = delete;
    OwnerScopedRegistry& operator=(const OwnerScopedRegistry&) = delete;
    OwnerScopedRegistry(OwnerScopedRegistry&&) noexcept = default;
    OwnerScopedRegistry& operator=(OwnerScopedRegistry&&) noexcept = default;

    // -- Registration --
    void Register(const Key& key, std::unique_ptr<Value> value) {
        entries_[key] = std::move(value);
    }

    // Returns ownership of the unregistered value to the caller
    // (the owning subsystem). Returns nullptr when absent.
    std::unique_ptr<Value> Unregister(const Key& key) {
        auto it = entries_.find(key);
        if (it == entries_.end()) {
            return nullptr;
        }
        auto value = std::move(it->second);
        entries_.erase(it);
        return value;
    }

    // -- Lookup (non-owning) --
    [[nodiscard]] Value* Find(const Key& key) const noexcept {
        auto it = entries_.find(key);
        return (it != entries_.end()) ? it->second.get() : nullptr;
    }

    // -- Query --
    [[nodiscard]] bool Contains(const Key& key) const noexcept {
        return entries_.find(key) != entries_.end();
    }

    [[nodiscard]] std::size_t Count() const noexcept { return entries_.size(); }

    // -- Enumeration --
    [[nodiscard]] std::vector<Key> Enumerate() const {
        std::vector<Key> keys;
        keys.reserve(entries_.size());
        for (const auto& [key, _] : entries_) {
            keys.push_back(key);
        }
        return keys;
    }

    // -- Clear --
    void Clear() noexcept { entries_.clear(); }

private:
    std::unordered_map<Key, std::unique_ptr<Value>> entries_;
};

}  // namespace ak