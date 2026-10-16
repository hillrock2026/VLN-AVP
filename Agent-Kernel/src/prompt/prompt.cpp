// ============================================================
// Agent Kernel - Prompt implementation (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapters 9-25 implementation.
//
// Determinism (PRM-014, PRM-041): assembly depends only on the
// immutable PromptDefinition and the immutable input values of
// the individual PromptAssemblyRequest. No global mutable
// state, random state, wall-clock time, thread scheduling,
// provider-specific behavior, or environmental dependency
// exists (Chapter 13.3).
//
// Concurrency (PRM-021, PRM-047): all Prompt state is
// immutable after construction; concurrent assembly with
// independent requests shares no mutable state and requires no
// synchronization (Chapters 17-18).
//
// Error semantics (PRM-043): deterministic classification per
// Chapter 25.2; exceptions are used only for construction
// failure (Chapter 25.1), following the project's established
// result-envelope convention. The classification mapping is:
//   - required variable, no binding supplied
//       -> kUnavailableRequiredMaterial
//   - required variable, bound value empty/whitespace-only
//       -> kMissingRequiredInput
//   - binding name not declared by the definition
//       -> kUnknownBinding
//   - bound value contains U+0000 (not representable as
//     model-neutral content) -> kInvalidValue
//   - component content references an undeclared variable
//       -> kInvalidSubstitution
//   - invalid Prompt state (defensive default) -> kInvalidState
//
// NON-responsibilities:
// - No Runtime, Memory, Context, Planner, Tool, or concrete
//   Model-provider type is referenced (PRM-024..PRM-029).
// ============================================================

#include <agent_kernel/prompt/prompt.hpp>

#include <algorithm>
#include <cctype>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ak::prompt {
namespace {

// ------------------------------------------------------------
// Structural invariant helpers (Chapter 25.1)
// ------------------------------------------------------------
bool HasNonWhitespace(const std::string& value) {
    return std::any_of(value.begin(), value.end(),
                       [](unsigned char c) { return !std::isspace(c); });
}

void ValidateNonEmpty(const std::string& value, const char* message) {
    if (!HasNonWhitespace(value)) {
        throw std::invalid_argument(message);
    }
}

void ValidateComponentContent(const std::string& content) {
    ValidateNonEmpty(content,
                     "Prompt component content must be non-empty and contain "
                     "at least one non-whitespace character");
}

void ValidateVariableName(const std::string& name) {
    ValidateNonEmpty(name,
                     "Prompt variable name must be non-empty and contain "
                     "at least one non-whitespace character");
}

// ------------------------------------------------------------
// Variable substitution (Chapters 11.1, 13.2)
// ------------------------------------------------------------
struct SubstitutionOutcome {
    std::string content;
    std::string reference;  // offending reference on failure
    bool failure = false;
};

// Resolves `{variable_name}` placeholders in component content
// against the declared variables and the supplied bindings.
//
// - A placeholder naming an undeclared variable is a failed
//   substitution (kInvalidSubstitution, Chapter 25.2).
// - A placeholder naming an optional unbound variable is
//   substituted with empty content (deterministic).
// - A `{` without a matching `}` is treated as literal text
//   (deterministic; no hidden parsing state).
SubstitutionOutcome Substitute(
    const std::string& content,
    const std::map<std::string, const PromptVariable*>& declared,
    const std::map<std::string, std::string>& bound) {
    SubstitutionOutcome outcome;
    outcome.content.reserve(content.size());

    std::size_t index = 0;
    while (index < content.size()) {
        const char c = content[index];
        if (c == '{') {
            const std::size_t close = content.find('}', index + 1);
            if (close == std::string::npos) {
                outcome.content.push_back(c);  // literal text
                ++index;
                continue;
            }
            const std::string name =
                content.substr(index + 1, close - index - 1);
            const auto declared_it = declared.find(name);
            if (declared_it == declared.end()) {
                outcome.failure = true;
                outcome.reference = name;
                return outcome;
            }
            const auto bound_it = bound.find(name);
            if (bound_it != bound.end()) {
                outcome.content.append(bound_it->second);
            }
            index = close + 1;
            continue;
        }
        outcome.content.push_back(c);
        ++index;
    }
    return outcome;
}

}  // namespace

// ============================================================
// PromptComponent (Chapter 11.1)
// ============================================================
PromptComponent::PromptComponent(PromptSectionKind kind,
                                 std::string content,
                                 std::vector<std::string> variable_references,
                                 PromptMetadata metadata)
    : kind_(kind),
      content_(std::move(content)),
      variable_references_(std::move(variable_references)),
      metadata_(std::move(metadata)) {
    ValidateComponentContent(content_);
}

PromptSectionKind PromptComponent::Kind() const noexcept { return kind_; }
const std::string& PromptComponent::Content() const noexcept { return content_; }
const std::vector<std::string>& PromptComponent::VariableReferences() const noexcept {
    return variable_references_;
}
const PromptMetadata& PromptComponent::Metadata() const noexcept { return metadata_; }

// ============================================================
// PromptSection (Chapter 10.1)
// ============================================================
PromptSection::PromptSection(PromptSectionKind kind,
                             std::vector<PromptComponent> components,
                             PromptMetadata metadata)
    : kind_(kind),
      components_(std::move(components)),
      metadata_(std::move(metadata)) {
    if (components_.empty()) {
        throw std::invalid_argument(
            "Prompt section must contain at least one component");
    }
}

PromptSectionKind PromptSection::Kind() const noexcept { return kind_; }
const std::vector<PromptComponent>& PromptSection::Components() const noexcept {
    return components_;
}
const PromptMetadata& PromptSection::Metadata() const noexcept { return metadata_; }

// ============================================================
// PromptVariable (Chapter 12.1)
// ============================================================
PromptVariable::PromptVariable(std::string name,
                               PromptSectionKind category,
                               bool required)
    : name_(std::move(name)),
      category_(category),
      required_(required) {
    ValidateVariableName(name_);
}

const std::string& PromptVariable::Name() const noexcept { return name_; }
PromptSectionKind PromptVariable::Category() const noexcept { return category_; }
bool PromptVariable::Required() const noexcept { return required_; }

// ============================================================
// PromptInputBinding (Chapter 12.2)
// ============================================================
PromptInputBinding::PromptInputBinding(std::string variable_name,
                                       std::string value)
    : variable_name_(std::move(variable_name)),
      value_(std::move(value)) {
    ValidateVariableName(variable_name_);
}

const std::string& PromptInputBinding::VariableName() const noexcept {
    return variable_name_;
}
const std::string& PromptInputBinding::Value() const noexcept { return value_; }

// ============================================================
// PromptAssemblyRequest (Chapter 13.1)
// ============================================================
PromptAssemblyRequest::PromptAssemblyRequest(
    std::vector<PromptInputBinding> bindings,
    PromptMetadata metadata)
    : bindings_(std::move(bindings)),
      metadata_(std::move(metadata)) {
    // Duplicate binding names are malformed input and are
    // rejected deterministically (Chapters 25.2, 41.4).
    for (std::size_t i = 0; i < bindings_.size(); ++i) {
        for (std::size_t j = i + 1; j < bindings_.size(); ++j) {
            if (bindings_[i].VariableName() == bindings_[j].VariableName()) {
                throw std::invalid_argument(
                    "Prompt assembly request contains a duplicate input "
                    "binding for variable '" +
                    bindings_[i].VariableName() + "'");
            }
        }
    }
}

const std::vector<PromptInputBinding>& PromptAssemblyRequest::Bindings() const noexcept {
    return bindings_;
}
const PromptMetadata& PromptAssemblyRequest::Metadata() const noexcept {
    return metadata_;
}

// ============================================================
// PromptDefinition (Chapter 9.1)
// ============================================================
PromptDefinition::PromptDefinition(PromptId id,
                                   std::string version,
                                   std::vector<PromptSection> sections,
                                   std::vector<PromptVariable> variables,
                                   PromptMetadata metadata)
    : id_(std::move(id)),
      version_(std::move(version)),
      sections_(std::move(sections)),
      variables_(std::move(variables)),
      metadata_(std::move(metadata)) {
    ValidateNonEmpty(version_,
                     "Prompt definition version must be non-empty and "
                     "contain at least one non-whitespace character");
    if (sections_.empty()) {
        throw std::invalid_argument(
            "Prompt definition must contain at least one section");
    }
    // Duplicate variable names are rejected (Chapter 25.1).
    for (std::size_t i = 0; i < variables_.size(); ++i) {
        for (std::size_t j = i + 1; j < variables_.size(); ++j) {
            if (variables_[i].Name() == variables_[j].Name()) {
                throw std::invalid_argument(
                    "Prompt definition declares duplicate variable '" +
                    variables_[i].Name() + "'");
            }
        }
    }
}

const PromptId& PromptDefinition::Id() const noexcept { return id_; }
const std::string& PromptDefinition::Version() const noexcept { return version_; }
const std::vector<PromptSection>& PromptDefinition::Sections() const noexcept {
    return sections_;
}
const std::vector<PromptVariable>& PromptDefinition::Variables() const noexcept {
    return variables_;
}
const PromptMetadata& PromptDefinition::Metadata() const noexcept { return metadata_; }

// ============================================================
// PromptResult (Chapter 14.1)
// ============================================================
PromptResult::PromptResult(PromptId id,
                           std::string definition_version,
                           std::vector<AssembledComponent> components,
                           PromptMetadata metadata,
                           PromptValidationStatus validation)
    : id_(std::move(id)),
      definition_version_(std::move(definition_version)),
      components_(std::move(components)),
      metadata_(std::move(metadata)),
      validation_(validation) {}

const PromptId& PromptResult::Id() const noexcept { return id_; }
const std::string& PromptResult::DefinitionVersion() const noexcept {
    return definition_version_;
}
const std::vector<AssembledComponent>& PromptResult::Components() const noexcept {
    return components_;
}
const PromptMetadata& PromptResult::Metadata() const noexcept { return metadata_; }
PromptValidationStatus PromptResult::ValidationStatus() const noexcept {
    return validation_;
}

// ============================================================
// PromptAssemblyService implementation (Chapters 13, 24)
// ============================================================
namespace {

class PromptAssemblyServiceImpl final : public PromptAssemblyService {
public:
    explicit PromptAssemblyServiceImpl(const PromptDefinition* definition) noexcept
        : definition_(definition) {}

    [[nodiscard]] PromptAssemblyResult Assemble(
        const PromptAssemblyRequest& request) const override;

private:
    const PromptDefinition* definition_;
};

PromptAssemblyResult PromptAssemblyServiceImpl::Assemble(
    const PromptAssemblyRequest& request) const {
    // Defensive invalid-state / invalid-definition checks
    // (Chapter 25.2). The public construction path guarantees a
    // valid definition; the checks keep the classification
    // contract deterministic and complete.
    if (definition_ == nullptr) {
        return {PromptAssemblyStatus::kInvalidState, std::nullopt,
                "Prompt assembly service has no Prompt definition", ""};
    }
    if (definition_->Sections().empty()) {
        return {PromptAssemblyStatus::kInvalidDefinition, std::nullopt,
                "Prompt definition contains no sections", ""};
    }

    const std::vector<PromptVariable>& variables = definition_->Variables();
    const std::vector<PromptInputBinding>& bindings = request.Bindings();

    std::map<std::string, const PromptVariable*> declared;
    for (const PromptVariable& variable : variables) {
        declared[variable.Name()] = &variable;
    }

    // Unknown bindings and invalid values are rejected
    // deterministically (Chapter 25.2).
    std::map<std::string, std::string> bound;
    for (const PromptInputBinding& binding : bindings) {
        if (declared.find(binding.VariableName()) == declared.end()) {
            return {PromptAssemblyStatus::kUnknownBinding, std::nullopt,
                    "Prompt assembly request contains an unknown input "
                    "binding for variable '" +
                        binding.VariableName() + "'",
                    binding.VariableName()};
        }
        if (binding.Value().find('\0') != std::string::npos) {
            return {PromptAssemblyStatus::kInvalidValue, std::nullopt,
                    "Prompt assembly input value for variable '" +
                        binding.VariableName() +
                        "' is not representable as model-neutral content",
                    binding.VariableName()};
        }
        bound[binding.VariableName()] = binding.Value();
    }

    // Required-variable validation (Chapters 12.3, 25.2).
    for (const PromptVariable& variable : variables) {
        if (!variable.Required()) {
            continue;
        }
        const auto found = bound.find(variable.Name());
        if (found == bound.end()) {
            return {PromptAssemblyStatus::kUnavailableRequiredMaterial,
                    std::nullopt,
                    "required Prompt material is unavailable: no binding "
                    "was supplied for variable '" +
                        variable.Name() + "'",
                    variable.Name()};
        }
        if (!HasNonWhitespace(found->second)) {
            return {PromptAssemblyStatus::kMissingRequiredInput, std::nullopt,
                    "required Prompt input is missing: bound value for "
                    "variable '" +
                        variable.Name() + "' is empty",
                    variable.Name()};
        }
    }

    // Ordered component resolution (Chapters 10.2, 13.2).
    std::vector<AssembledComponent> components;
    for (const PromptSection& section : definition_->Sections()) {
        for (const PromptComponent& component : section.Components()) {
            const SubstitutionOutcome outcome =
                Substitute(component.Content(), declared, bound);
            if (outcome.failure) {
                return {PromptAssemblyStatus::kInvalidSubstitution,
                        std::nullopt,
                        "Prompt component references undeclared variable '" +
                            outcome.reference + "'",
                        outcome.reference};
            }
            AssembledComponent assembled;
            assembled.kind = component.Kind();
            assembled.content = outcome.content;
            assembled.metadata = component.Metadata();
            components.push_back(std::move(assembled));
        }
    }

    // Model-neutral representation metadata: definition
    // metadata first, then request metadata (request keys
    // override on conflict). Both inputs are explicit and
    // immutable, so the merge is deterministic (Chapter 13.3).
    PromptMetadata result_metadata = definition_->Metadata();
    for (const auto& [key, value] : request.Metadata()) {
        result_metadata[key] = value;
    }

    PromptResult result(definition_->Id(), definition_->Version(),
                        std::move(components), std::move(result_metadata),
                        PromptValidationStatus::kValid);
    return {PromptAssemblyStatus::kSuccess, std::move(result), "", ""};
}

}  // namespace

// ============================================================
// Prompt root (Chapters 16, 24)
// ============================================================
struct Prompt::Impl {
    explicit Impl(PromptDefinition definition)
        : definition(std::move(definition)),
          assembly_service(&this->definition) {}

    PromptDefinition definition;
    PromptAssemblyServiceImpl assembly_service;
};

Prompt::Prompt(PromptDefinition definition)
    : impl_(std::make_unique<Impl>(std::move(definition))) {}

Prompt::~Prompt() = default;

const PromptId& Prompt::Id() const noexcept {
    return impl_->definition.Id();
}

const PromptDefinition& Prompt::Definition() const noexcept {
    return impl_->definition;
}

PromptAssemblyService& Prompt::Assembly() noexcept {
    return impl_->assembly_service;
}

const PromptAssemblyService& Prompt::Assembly() const noexcept {
    return impl_->assembly_service;
}

}  // namespace ak::prompt