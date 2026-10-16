// ============================================================
// Agent Kernel — TaskContract
// ============================================================
// Describes what a Task requires as input and produces as
// output. This is a structural contract — it declares the
// shape of data, not the data itself.
//
// TaskContract is a value type composed into Task. It is
// set during construction (via TaskBuilder) and remains
// read-only for the lifetime of the Task.
//
// The actual data passing mechanism (how input is delivered
// and output is retrieved) is deferred to AK0020+ (Memory
// and Context specification).
//
// TaskContract does NOT contain:
// - Execution function / callable
// - Lambda or callback
// - Tool or agent reference
// - Runtime engine reference
// ============================================================

#pragma once

#include <string>
#include <vector>
#include <cstdint>

namespace ak {

// ============================================================
// ContractField — description of one input/output field
// ============================================================
struct ContractField {
    std::string name;        // Field name (e.g., "query", "result")
    std::string typeName;    // Human-readable type (e.g., "string", "json")
    bool isRequired = true;  // Whether this field must be provided
    std::string description; // Human-readable description
};

// ============================================================
// TaskContract — immutable input/output declaration
// ============================================================
struct TaskContract {
    // Description of inputs this Task requires
    std::vector<ContractField> inputs;

    // Description of outputs this Task produces
    std::vector<ContractField> outputs;

    // Human-readable description of what this Task does
    std::string description;

    // Version for contract evolution
    std::uint32_t version = 1;

    // Reserved for future: semantic type identifiers
    // std::vector<std::string> inputTypes;
    // std::vector<std::string> outputTypes;
};

}  // namespace ak
