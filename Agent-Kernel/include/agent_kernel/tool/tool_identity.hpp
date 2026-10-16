// ============================================================
// Agent Kernel - Tool Identity (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapter 8 - Canonical Identity Model.
//
// - ToolId / CapabilityId / ProviderId are immutable value
//   types (TOL-013, TOL-014, TOL-015).
// - Construction rejects empty or whitespace-only values with
//   std::invalid_argument (TOL-111).
// - Tool owns identity semantics; the Foundation provides no
//   Tool identity authority (TOL-016).
//
// NON-responsibilities:
// - These identities are not Runtime identities and reference
//   no Runtime type.
// - One Tool root equals one Tool Object equals one ToolId
//   (TOL-081); no multi-Tool registry exists.
// ============================================================

#pragma once

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string>

namespace ak::tool {

namespace detail {

// Tool identity values must be non-empty and contain at least
// one non-whitespace character (TOL-111).
inline bool IsValidIdentityValue(const std::string& value) noexcept {
    return std::any_of(value.begin(), value.end(),
                       [](unsigned char c) { return !std::isspace(c); });
}

inline void ValidateIdentityValue(const std::string& value) {
    if (!IsValidIdentityValue(value)) {
        throw std::invalid_argument(
            "Tool identity value must be non-empty and contain "
            "at least one non-whitespace character (TOL-111)");
    }
}

}  // namespace detail

// Canonical Tool architectural identity (TOL-013).
class ToolId {
public:
    ToolId() = delete;
    explicit ToolId(std::string value) : value_(std::move(value)) {
        detail::ValidateIdentityValue(value_);
    }

    [[nodiscard]] const std::string& Value() const noexcept { return value_; }
    [[nodiscard]] bool Empty() const noexcept { return false; }

    friend bool operator==(const ToolId&, const ToolId&) = default;

private:
    std::string value_;
};

// Canonical capability identity (TOL-014). Same immutable value
// semantics and construction failure semantics as ToolId.
class CapabilityId {
public:
    CapabilityId() = delete;
    explicit CapabilityId(std::string value) : value_(std::move(value)) {
        detail::ValidateIdentityValue(value_);
    }

    [[nodiscard]] const std::string& Value() const noexcept { return value_; }
    [[nodiscard]] bool Empty() const noexcept { return false; }

    friend bool operator==(const CapabilityId&, const CapabilityId&) = default;

private:
    std::string value_;
};

// Canonical Provider identity (TOL-015). Same immutable value
// semantics and construction failure semantics as ToolId.
class ProviderId {
public:
    ProviderId() = delete;
    explicit ProviderId(std::string value) : value_(std::move(value)) {
        detail::ValidateIdentityValue(value_);
    }

    [[nodiscard]] const std::string& Value() const noexcept { return value_; }
    [[nodiscard]] bool Empty() const noexcept { return false; }

    friend bool operator==(const ProviderId&, const ProviderId&) = default;

private:
    std::string value_;
};

}  // namespace ak::tool
