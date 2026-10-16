// ============================================================
// Agent Kernel - Prompt Identity (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 8 - Canonical Prompt identity.
//
// - PromptId is a strongly typed immutable value (PRM-001).
// - Construction is explicit and rejects empty or
//   whitespace-only values with std::invalid_argument
//   (Chapter 25.1 - empty Prompt identity).
// - Prompt owns identity semantics; the Foundation provides no
//   Prompt identity authority (PRM-002).
// - PromptId SHALL NOT encode provider-specific model identity
//   (PRM-016); it is model-neutral.
//
// NON-responsibilities:
// - PromptId is not a Runtime identity and references no
//   Runtime type (PRM-008).
// ============================================================

#pragma once

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string>
#include <utility>

namespace ak::prompt {

namespace detail {

// Prompt identity values must be non-empty and contain at
// least one non-whitespace character (Chapter 8.1).
inline bool IsValidPromptIdentityValue(const std::string& value) noexcept {
    return std::any_of(value.begin(), value.end(),
                       [](unsigned char c) { return !std::isspace(c); });
}

inline void ValidatePromptIdentityValue(const std::string& value) {
    if (!IsValidPromptIdentityValue(value)) {
        throw std::invalid_argument(
            "Prompt identity value must be non-empty and contain "
            "at least one non-whitespace character");
    }
}

}  // namespace detail

// Canonical Prompt architectural identity (Chapter 8.1).
class PromptId {
public:
    PromptId() = delete;
    explicit PromptId(std::string value) : value_(std::move(value)) {
        detail::ValidatePromptIdentityValue(value_);
    }

    [[nodiscard]] const std::string& Value() const noexcept { return value_; }
    [[nodiscard]] bool Empty() const noexcept { return false; }

    friend bool operator==(const PromptId&, const PromptId&) = default;

private:
    std::string value_;
};

}  // namespace ak::prompt