// ============================================================
// Agent Kernel - ModelResult implementation (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapter 8. ModelResult is the Model-owned
// inference result crossing the Model boundary. Factories
// enforce the Chapter 8 validity semantics: Success carries a
// non-empty payload; InvalidResult and Failure carry a
// non-empty diagnostic. Exceptions are construction-time
// validation only; inference control flow returns typed
// results.
// ============================================================

#include <agent_kernel/model/model_result.hpp>

#include <stdexcept>
#include <utility>

namespace ak::model {

ModelResult ModelResult::Success(std::string payload) {
    if (payload.empty()) {
        throw std::invalid_argument(
            "ModelResult::Success requires a non-empty payload");
    }
    ModelResult result;
    result.status_ = ModelStatus::kSuccess;
    result.category_ = ModelErrorCategory::kNone;
    result.payload_ = std::move(payload);
    return result;
}

ModelResult ModelResult::InvalidResult(std::string diagnostic) {
    if (diagnostic.empty()) {
        throw std::invalid_argument(
            "ModelResult::InvalidResult requires a non-empty diagnostic");
    }
    ModelResult result;
    result.status_ = ModelStatus::kInvalidResult;
    result.category_ = ModelErrorCategory::kInvalidResult;
    result.diagnostic_ = std::move(diagnostic);
    return result;
}

ModelResult ModelResult::Failure(std::string diagnostic,
                                 ModelErrorCategory category) {
    if (diagnostic.empty()) {
        throw std::invalid_argument(
            "ModelResult::Failure requires a non-empty diagnostic");
    }
    ModelResult result;
    result.status_ = ModelStatus::kFailure;
    result.category_ = category;
    result.diagnostic_ = std::move(diagnostic);
    return result;
}

}  // namespace ak::model
