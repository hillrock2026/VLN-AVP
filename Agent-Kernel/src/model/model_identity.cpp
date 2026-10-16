// ============================================================
// Agent Kernel - ModelId implementation (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapter 7. Construction rejects empty or
// whitespace-only identity values with std::invalid_argument,
// following the canonical identity convention (TOL-111).
// ============================================================

#include <agent_kernel/model/model_identity.hpp>

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <utility>

namespace ak::model {
namespace {

bool HasNonWhitespace(const std::string& value) noexcept {
    return std::any_of(value.begin(), value.end(), [](unsigned char c) {
        return !std::isspace(c);
    });
}

}  // namespace

ModelId::ModelId(std::string value) : value_(std::move(value)) {
    if (!HasNonWhitespace(value_)) {
        throw std::invalid_argument(
            "ModelId value must be non-empty and contain at least one "
            "non-whitespace character");
    }
}

}  // namespace ak::model
