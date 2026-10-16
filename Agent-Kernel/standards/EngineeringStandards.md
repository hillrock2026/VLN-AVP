# Agent Kernel Engineering Standards

**Document Version:** 1.0  
**Status:** Permanent  
**Applies To:** All AI agents and human developers working on Agent Kernel  
**Enforcement:** Mandatory — code not conforming to these standards shall be rejected at review

---

## Chapter 1 — Purpose

### 1.1 Mission

This document is the single source of truth for all engineering decisions in the Agent Kernel project. Every line of code, every review comment, every prompt, and every architectural decision must conform to the standards defined herein.

### 1.2 Scope

These standards govern:

- C++ source code (headers, implementations, tests, examples)
- Project structure and file organization
- API design and interface contracts
- Memory and resource management
- Error handling and exception policy
- Dependency management
- Code review criteria
- AI prompt engineering
- AI agent collaboration boundaries

### 1.3 Audience

| Role | How This Document Is Used |
|------|--------------------------|
| Human Developer | Reference during implementation and review |
| Codex | Primary instruction source for code generation |
| GPT-5.5 | Context for architecture review and refactoring |
| DeepSeek | Reference for code analysis and bug detection |
| GitHub Copilot | Inline completion style guidance |
| Human Architect | Establishes and enforces these standards |

### 1.4 Maintenance

This document is versioned with the project. Amendments require an RFC; minor clarifications do not. Chapter numbering is stable — future versions append chapters without renumbering existing ones.

---

## Chapter 2 — Engineering Principles

### 2.1 Core Values

| Principle | Meaning |
|-----------|---------|
| **Readable** | Code is written for humans first, compilers second |
| **Maintainable** | Every structure is easy to modify without breaking other parts |
| **Modular** | Each module has one responsibility and one reason to change |
| **Composable** | Components combine freely through well-defined interfaces |
| **Testable** | Every public function can be tested in isolation |
| **Replaceable** | Any implementation can be swapped without affecting callers |

### 2.2 Design Tenets

1. **RFC Driven** — No significant design decision is made without an RFC
2. **Architecture before implementation** — Interface first, implementation second
3. **Explicit over magic** — No implicit conversions, no hidden side effects, no clever tricks
4. **No unnecessary abstraction** — Abstraction has a cost; justify every layer
5. **No premature optimization** — Write correct code first, profile second, optimize third
6. **Fail fast** — Detect and report errors at the earliest possible point
7. **Composability over inheritance** — Prefer interfaces and dependency injection over deep class hierarchies

### 2.3 Anti-Patterns (Forbidden)

- Global mutable state
- Singleton pattern
- Hidden dependencies (magic statics, global registries)
- Macro-based APIs (except include guards)
- Compiler-specific extensions
- Undefined behavior of any kind


---

## Chapter 3 — Project Structure

### 3.1 Top-Level Layout

```
agent-kernel/
+-- include/ak/       # Public headers - the installed API surface
+-- src/              # Implementation files (.cpp)
+-- tests/            # All test code
|   +-- unit/         #   Unit tests (one-per-class)
|   +-- integration/  #   Integration tests (module boundaries)
|   +-- benchmark/    #   Performance benchmarks
|   +-- regression/   #   Bug regression tests
+-- examples/         # Example programs
+-- docs/             # Architecture, RFC, API, guides
+-- prompt/           # AI prompt library
+-- templates/        # Code generation templates
+-- standards/        # Engineering standards (this document)
+-- scripts/          # Build and CI scripts
+-- cmake/            # CMake helper modules
+-- third_party/      # External dependencies
+-- tools/            # Developer tooling
+-- .github/          # CI/CD workflows
```

### 3.2 Module Layout (Future)

Each future module (Session, Workflow, Task, etc.) follows this pattern:

```
include/ak/<module>/
+-- <component>.hpp           # Public interface
+-- <component>_observer.hpp  # Observer interface (if applicable)
+-- <component>_factory.hpp   # Factory interface (if applicable)
+-- fwd.hpp                   # Forward declarations for the module

src/<module>/
+-- <component>.cpp           # Implementation
+-- <component>_factory.cpp   # Factory implementation
+-- detail/                   # Internal helpers (not in public headers)

tests/unit/<module>/
+-- <component>_test.cpp      # Tests mirror the source structure

tests/integration/<module>/
+-- <module>_integration_test.cpp
```

### 3.3 One-Class-Per-File Rule

Every public class occupies exactly one header and one source file, both named after the class. The only exceptions are:

- Template classes where implementation must remain in the header
- Small POD types or type aliases grouped in a types.hpp file
- Enumerations grouped in an enum.hpp file per module


---

## Chapter 4 — Naming Convention

### 4.1 General Rules

- Use American English spelling throughout
- No abbreviations unless they are universally understood (e.g., Id, Ctx, Ptr)
- Names must be self-documenting — a reader should infer purpose without comments

### 4.2 Table of Naming Rules

| Category | Convention | Example |
|----------|-----------|---------|
| Namespace | snake_case, all lowercase | ak::session, ak::workflow |
| Class / Struct | PascalCase | SessionManager, TaskExecutor |
| Interface (abstract base, no state) | PascalCase prefixed with I | ISessionHandler, ITaskObserver |
| Enum type | PascalCase | SessionState, TaskPriority |
| Enum enumerator | kPascalCase prefixed with k | kIdle, kRunning, kCompleted |
| Function / Method | PascalCase | CreateSession(), ExecuteTask() |
| Free function | PascalCase | InitializeRuntime(), ShutdownRuntime() |
| Local variable | camelCase | currentSession, taskCount |
| Member variable | camelCase_ trailing underscore | currentState_, taskQueue_ |
| Static member | camelCase_ trailing underscore | defaultTimeout_ |
| Constant (local/constexpr) | kPascalCase prefixed with k | kMaxRetries, kDefaultPort |
| Macro (avoid; only include guards) | UPPER_SNAKE_CASE | AK_SESSION_SESSION_MANAGER_HPP |
| Template parameter (type) | PascalCase | typename T, typename ResultType |
| Template parameter (non-type) | kPascalCase | int kBufferSize |
| File name (header) | snake_case.hpp | session_manager.hpp |
| File name (source) | snake_case.cpp | session_manager.cpp |
| Directory name | snake_case | session/, workflow/ |
| Event type | PascalCase suffixed with Event | SessionCreatedEvent, TaskFailedEvent |
| Task / Workflow ID | PascalCase type alias | using SessionId = std::uint64_t |
| State name | PascalCase | kInitializing, kActive, kTerminated |

### 4.3 Include Guard Pattern

```cpp
#pragma once   // Preferred
```

If #pragma once is unavailable:

```cpp
#ifndef AK_MODULE_CLASS_NAME_HPP
#define AK_MODULE_CLASS_NAME_HPP
#endif
```


---

## Chapter 5 — C++ Coding Style

### 5.1 Language Standard

- C++20 is mandatory; C++17 features are permitted; C++23 features are not yet approved
- CMAKE_CXX_EXTENSIONS is OFF - no compiler-specific extensions

### 5.2 Formatting

Formatting is enforced by .clang-format (Google style with 4-space indent, 100-column limit). The CI pipeline rejects unformatted code.

### 5.3 Type Deduction

- Use auto for variables when the type is obvious from the right-hand side: auto session = CreateSession();
- Do NOT use auto when the type is not obvious or when it sacrifices readability
- Use auto for lambda parameters
- Prefer explicit types for public API return values

### 5.4 Structured Bindings

Allowed for tuple-like types and aggregates when it improves readability:

```cpp
auto [ec, session] = factory.CreateSession();
```

### 5.5 Const Correctness

- Mark member functions const whenever they do not modify observable state
- Mark local variables const unless they are intended to mutate
- Pass by const& for read-only parameters of non-trivial types
- Return const& for accessors that expose internal state (document lifetime)

### 5.6 No using namespace in Headers

using namespace is forbidden in header files. In source files, using namespace ak::session; is acceptable within a .cpp after all includes.

### 5.7 Lambdas

- Capture by explicit value or explicit reference - no default capture modes
- Prefer named lambdas for anything longer than 3 lines
- Mark lambdas mutable only when required

### 5.8 No Raw Loops Without Justification

Prefer std::ranges algorithms over raw for loops. Raw loops are permitted only when:

- The algorithm requires early exit with complex conditions
- Performance profiling demonstrates a measurable difference
- The standard library provides no equivalent


---

## Chapter 6 — API Design Principles

### 6.1 Single Responsibility

Every class has exactly one responsibility and one reason to change. A class name must describe its single responsibility.

### 6.2 Dependency Injection

- Dependencies are passed through constructors, not obtained via static accessors
- Backends/services are injected as interfaces (abstract base classes)
- No class calls GetInstance(), CreateDefault(), or any global accessor

### 6.3 Interface Stability

- Public API is the contract; breaking changes require a major version bump
- Deprecated API must emit a compiler warning and remain for at least one minor version
- Mark internal API with [[nodiscard]] or place in detail namespace

### 6.4 Minimal Public API

- Expose the minimum surface area required for correct usage
- Everything else is private or in detail/ headers
- Friends are forbidden (except for unit test fixtures in the same library)

### 6.5 Backward Compatibility

- New overloads are additive; never remove or change an existing signature
- Default parameter values are part of the contract; do not change them
- Adding const to a parameter is not a breaking change; removing it is

### 6.6 Explicit Ownership

Every API function makes ownership transfers explicit:

| Pattern | Meaning |
|---------|---------|
| std::unique_ptr<T> | Exclusive ownership transfer |
| std::shared_ptr<T> | Shared ownership (document why) |
| T& | Non-owning reference (caller guarantees lifetime) |
| const T& | Non-owning read-only reference |
| T* | Nullable non-owning pointer (document null meaning) |

### 6.7 No Hidden Side Effects

- Functions named Get* must not mutate state
- Functions named Compute* may perform work but must not mutate visible state
- Functions named Set* must only mutate the named property
- Functions named Create* must return a new object and not modify existing state


---

## Chapter 7 — Ownership Rules

### 7.1 Principle

Every object in the system has exactly one owner at any point in time. Ownership is explicit in the type system.

### 7.2 Ownership Table

| Ownership Pattern | When to Use | Mechanism |
|-------------------|-------------|-----------|
| Unique (default) | One owner, one lifetime | std::unique_ptr<T> |
| Shared (rare) | Genuinely shared lifetime (e.g., Event Bus subscriptions) | std::shared_ptr<T> |
| Observer | Non-owning reference to an object owned elsewhere | T* or T& |
| Weak | Break shared_ptr cycles | std::weak_ptr<T> |
| Value | Object is part of another object's state | Member variable |

### 7.3 Rules

1. std::unique_ptr is the default ownership model. Use std::make_unique for creation.
2. std::shared_ptr requires documented justification in a comment. Prefer std::unique_ptr and explicit sharing via observer pattern.
3. Raw pointers as observers must be documented with lifetime invariants.
4. Never return a raw pointer to an owned object unless transfer is documented.
5. Never store a raw pointer that outlives the pointed-to object (use std::weak_ptr or restructure).


---

## Chapter 8 — Memory Management

### 8.1 RAII

Every resource (memory, file handle, socket, mutex) is owned by an RAII object. There are no manual new/delete calls in application code.

### 8.2 Smart Pointer Policy

| Pointer | Allowed? | Rule |
|---------|----------|------|
| std::unique_ptr | Default ownership | std::make_unique for construction |
| std::shared_ptr | Rare | Must be justified; use std::make_shared |
| std::weak_ptr | Allowed | Only to break shared_ptr cycles |
| T* | Observer only | Must document lifetime |
| T& | Observer only | Non-nullable |
| new / delete | Forbidden | Use std::make_unique or std::make_shared |
| malloc / free | Forbidden | Use containers or RAII wrappers |

### 8.3 Move Semantics

- Move constructors and move assignment operators are noexcept wherever possible
- Move-only types are preferred over copyable types when ownership transfer is the norm
- Return std::unique_ptr by value from factory functions - NRVO/move is guaranteed

### 8.4 Copy Semantics

- Copy constructors are deleted for owning types (unique ownership)
- Copy is permitted only for value types (small, cheap to copy) and types where shared state is intentional (e.g., std::shared_ptr)
- Every copyable class must document the cost of copying


---

## Chapter 9 — Exception Policy

### 9.1 General Rule

Exceptions are the primary error reporting mechanism. No function returns error codes for logical errors.

### 9.2 Exception Hierarchy

All custom exceptions inherit from ak::Error (a subclass of std::runtime_error):

```
std::exception
+-- std::runtime_error
    +-- ak::Error
        +-- ak::InvalidArgumentError
        +-- ak::StateError        (invalid state transition)
        +-- ak::NotFoundError     (resource not found)
        +-- ak::AlreadyExistsError
        +-- ak::TimeoutError
        +-- ak::LimitError        (capacity exceeded)
        +-- ak::SystemError       (OS-level failure, wraps errno/HRESULT)
```

### 9.3 Exception Safety Guarantees

Every function documents one of:

| Guarantee | Meaning | Requirement |
|-----------|---------|-------------|
| No-throw | Function never throws | Must be marked noexcept |
| Strong | On failure, state is rolled back | Required for all public API |
| Basic | On failure, invariants are preserved | Minimum for internal functions |
| No guarantee | Not acceptable in public API | Internal only, with documentation |

### 9.4 When NOT to Throw

- Destructors (must be noexcept)
- Move constructors / move assignment (should be noexcept)
- Callbacks invoked from destructors
- Functions explicitly marked noexcept in the interface

### 9.5 noexcept Specification

- All destructors are implicitly noexcept
- Move operations are noexcept whenever possible
- Swaps are noexcept
- Get* accessors are noexcept
- Factory functions and Create* functions may throw



---

## Chapter 10 — Dependency Rules

### 10.1 Direction

```
Kernel API  <-  Plugin System
    ^               ^
    +-- Session  <--+
    +-- Workflow <--+
    +-- Task     <--+
    +-- Scheduler <--+
    +-- Executor  <--+
    +-- Memory    <--+
    +-- Context   <--+
    +-- Event Bus <--+
         ^
    Runtime

Dependencies point downward: higher-level modules depend on lower-level ones. No module depends on a module at the same or higher level.

### 10.2 Circular Dependencies

Circular dependencies are strictly forbidden. Detection:

- CMake target_link_libraries must form a DAG
- Any cycle in the include graph is a build error
- Break cycles by introducing an interface (abstract base) in a lower-level module

### 10.3 Header Dependency Rules

- A header must include only what it uses (no transitive includes)
- Prefer forward declarations over #include where possible
- Each header must compile independently - include all types it uses
- The first include in a .cpp file is always its own header (self-containment test)

### 10.4 Forward Declaration Policy

- Forward-declare class types when only pointers or references are used
- Never forward-declare types from std:: namespace (include the standard header)
- Place module-level forward declarations in <module>/fwd.hpp

### 10.5 Interface Isolation

- Modules communicate through abstract interfaces, not concrete classes
- Interface headers live in include/ak/<module>/ alongside the implementation header
- No module #includes the .cpp or detail/ of another module



---

## Chapter 11 — Header Organization

### 11.1 Header Template

```cpp
// ============================================================
// Agent Kernel -- <Module>/<ClassName>
// ============================================================
// <Short description of the class responsibility>
//
// <Lifetime and ownership notes if non-trivial>
// <Thread safety annotation if applicable>
// ============================================================

#pragma once

// -- Standard Library --
#include <memory>
#include <string_view>

// -- Agent Kernel --
#include <ak/<dependency1>.hpp>
#include <ak/<dependency2>.hpp>

namespace ak::<module> {

/// <Brief description - one sentence>
///
/// <Detailed description - required for public API>
///
/// ## Thread Safety
/// <ThreadSafe | NotThreadSafe | Reentrant>
///
/// ## Ownership
/// <Exclusive | Shared | Observer - see Chapter 7>
class ClassName {
public:
    // -- Lifecycle --
    ClassName() = delete;
    explicit ClassName(<ConstructorArgs>);
    ~ClassName() noexcept;
    ClassName(const ClassName&) = delete;
    ClassName& operator=(const ClassName&) = delete;
    ClassName(ClassName&&) noexcept;
    ClassName& operator=(ClassName&&) noexcept;

    // -- Public API --
    [[nodiscard]] ResultType DoSomething(<Args>);

private:
    // -- Dependencies (injected) --
    IDependency& dependency_;
    // -- State --
    StateType currentState_;
};

}  // namespace ak::<module>
```

### 11.2 Order of Declarations in a Header

1. Preamble comment block
2. #pragma once
3. Blank line
4. Standard library includes
5. Third-party includes
6. Agent Kernel includes
7. Forward declarations (if any)
8. Namespace opening
9. Class / enum / type alias declarations
10. Namespace closing comment

### 11.3 Include Order (within each group)

- Headers from the currently implemented module first
- Headers from lower-level modules
- Headers from peer modules
- Standard library headers (alphabetically)
- Third-party headers (alphabetically)



---

## Chapter 12 — Source Organization

### 12.1 Source File Template

```cpp
// ============================================================
// Agent Kernel -- <Module>/<ClassName> (implementation)
// ============================================================

// -- Self header (always first) --
#include <ak/<module>/<class_name>.hpp>

// -- Standard Library --
#include <utility>

// -- Agent Kernel (as needed) --
#include <ak/<other_module>/<dependency>.hpp>

namespace ak::<module> {
namespace {

// -- Internal helpers (file-static / anonymous ns) --
constexpr auto kDefaultTimeout = std::chrono::seconds{30};

bool ValidateState(StateType state) {
    return state >= kMinValid && state <= kMaxValid;
}

}  // namespace

// -- ClassName --
ClassName::ClassName(IDependency& dependency)
    : dependency_{dependency}
    , currentState_{StateType::kInitializing} {
}

ResultType ClassName::DoSomething(<Args>) {
    // Implementation
}

}  // namespace ak::<module>
```

### 12.2 Order of Definitions in a Source File

1. Preamble comment block
2. Self-header include
3. Standard library includes
4. Third-party includes
5. Agent Kernel includes
6. Anonymous namespace (file-static helpers)
7. Destructor
8. Constructors (default, parameterized, move)
9. Assignment operators (copy, move)
10. Public API methods (alphabetically)
11. Protected methods
12. Private methods
13. Free functions in the module namespace

### 12.3 Test File Structure

```
tests/unit/<module>/<class_name>_test.cpp
tests/integration/<module>/<integration_point>_test.cpp
```

Each test file mirrors one public class. Test file structure:

```cpp
#include <gtest/gtest.h>
#include <ak/<module>/<class_name>.hpp>
#include <mock/<dependency>.hpp>

namespace ak::<module>::test {

class <ClassName>Test : public ::testing::Test {
protected:
    void SetUp() override { /* create test fixtures */ }
    void TearDown() override { /* clean up */ }
};

TEST_F(<ClassName>Test, <Scenario_ExpectedOutcome>) {
    // Arrange
    // Act
    // Assert
}

}  // namespace ak::<module>::test
```



---

## Chapter 13 — Namespace Rules

### 13.1 Top-Level Namespace

All Agent Kernel public API lives under the ak namespace. No exceptions.

### 13.2 Module Namespaces

Each module has its own nested namespace:

```cpp
namespace ak::session { ... }
namespace ak::workflow { ... }
namespace ak::task { ... }
namespace ak::scheduler { ... }
namespace ak::executor { ... }
namespace ak::memory { ... }
namespace ak::context { ... }
namespace ak::event_bus { ... }
namespace ak::plugin { ... }
namespace ak::runtime { ... }
namespace ak::kernel { ... }
```

### 13.3 Detail Namespace

Implementation details not part of the public API reside in ak::<module>::detail.

### 13.4 Test Namespace

Test code resides in ak::<module>::test.

### 13.5 Rules

- using namespace ak; is forbidden in headers
- using namespace ak::<module>; is acceptable in .cpp files after all includes
- Never open a namespace that belongs to another module
- Always close a namespace with a comment: }  // namespace ak::session



---

## Chapter 14 — Logging Policy

### 14.1 Logging Library

A future RFC will select the logging library (likely spdlog). Until then, no logging calls are made.

### 14.2 Log Levels

| Level | Purpose | Frequency |
|-------|---------|-----------|
| TRACE | Function entry/exit, variable values | Development only |
| DEBUG | Diagnostic details for troubleshooting | Development / optional at runtime |
| INFO | Lifecycle events (startup, shutdown, config load) | Always on in production |
| WARN | Recoverable issues, degraded behavior | Always on |
| ERROR | Unrecoverable errors within a single operation | Always on |
| CRITICAL | System-wide failures requiring immediate attention | Always on |

### 14.3 Rules

- No printf, std::cout, or std::cerr in production code
- Log messages are structured (key-value pairs), not free-form text
- Logs never contain sensitive data (passwords, tokens, PII)
- Log calls must not throw exceptions (log level checking before formatting)
- Each module gets its own logger instance named ak::<module>



---

## Chapter 15 — Error Handling

### 15.1 Error Categories

| Category | Mechanism | Example |
|----------|-----------|---------|
| Programming error | assert() / std::terminate | Null pointer passed to non-null parameter |
| Invalid input | Exception (ak::InvalidArgumentError) | Out-of-range value |
| State violation | Exception (ak::StateError) | Illegal state transition |
| Resource not found | Exception (ak::NotFoundError) | Session ID does not exist |
| Resource already exists | Exception (ak::AlreadyExistsError) | Duplicate registration |
| Timeout | Exception (ak::TimeoutError) | Operation exceeded time limit |
| Capacity exceeded | Exception (ak::LimitError) | Queue full, memory exhausted |
| OS failure | Exception (ak::SystemError) | File read failure, socket error |

### 15.2 Exception Handling Rules

- Catch by const& (e.g., catch (const ak::Error& error))
- Never catch (...) without rethrowing or invoking std::terminate
- Always log the exception at the catch site
- Translate third-party exceptions into ak::Error at module boundaries
- Exception-neutral code propagates exceptions without catching

### 15.3 Assertions

- Use assert() for internal invariant checks only
- Use gsl::Expects() for pre-condition checks
- Use gsl::Ensures() for post-condition checks
- Assertions are compiled out in Release builds; do not rely on them for correctness



---

## Chapter 16 — Review Rules

### 16.1 What Reviewers Verify

Every code review must check these items in order:

| # | Check | Description |
|---|-------|-------------|
| 1 | RFC Compliance | Does the implementation match the approved RFC? |
| 2 | Standards Compliance | Does the code follow this Engineering Standards document? |
| 3 | Naming | Do all names follow Chapter 4 conventions? |
| 4 | Ownership | Is every object's owner explicit (Chapter 7)? |
| 5 | Memory Safety | Are there leaks, dangling pointers, or double frees? |
| 6 | Exception Safety | Does the code meet its documented exception guarantee? |
| 7 | Architecture Drift | Has the implementation deviated from the architecture? |
| 8 | State Machine Correctness | Are state transitions valid? Are illegal transitions caught? |
| 9 | Include Hygiene | Are includes minimal? Is every header self-contained? |
| 10 | Test Coverage | Are all public functions tested? Are error paths tested? |

### 16.2 What Reviewers Do NOT Check

- Personal formatting preferences (delegated to .clang-format)
- Variable naming style that already conforms to Chapter 4
- Performance optimization (delegated to profiling)
- Completeness of future features (scope of the RFC)

### 16.3 Review Outcome

| Result | Meaning | Action |
|--------|---------|--------|
| Approved | Conforms to all standards | Merge |
| Needs Changes | Minor issues found | Author fixes, re-review waived for trivial changes |
| Revise and Re-review | Structural or ownership issues | Author revises, full re-review required |
| Rejected | Violates RFC or architecture | Return to RFC stage |



---

## Chapter 17 — Prompt Engineering Rules

### 17.1 Universal Prompt Template

Every AI prompt in the Agent Kernel project must contain these sections in order:

```
Role:           <What the AI should act as>
Objective:      <Single sentence describing the task>
Background:     <Context the AI needs to understand the problem>
Scope:          <What the AI IS allowed to do>
Non-Goals:      <What the AI is NOT allowed to do>
Acceptance Criteria: <How to verify the output is correct>
Deliverables:   <Exact list of files or artifacts to produce>
Intent Contract: <Architect'''s intent - the why behind the task>
Self-Check:     <Checklist the AI runs before final output>
```

### 17.2 Role Definitions

| Role | Purpose |
|------|---------|
| Senior C++ Software Architect | Structural decisions, standards, RFCs |
| C++ Software Engineer | Implementation of specified components |
| C++ Code Reviewer | Code review against standards |
| Test Engineer | Test generation and test infrastructure |
| Documentation Engineer | Documentation and prompt engineering |

### 17.3 Prompt Categories

| Category | Location | Purpose |
|----------|----------|---------|
| prompt/coding/ | Phase implementation prompts | Generate implementation code |
| prompt/review/ | Code review prompts | Review generated code against standards |
| prompt/testing/ | Test generation prompts | Generate tests for existing code |
| prompt/intent/ | Intent extraction prompts | Clarify architect intent from vague requirements |
| prompt/documentation/ | Documentation prompts | Generate API docs, guides, README files |

### 17.4 Self-Check Requirement

Every prompt must end with a self-check section that the AI executes before delivering output. The self-check must be a table of yes/no questions that catch common mistakes.



---

## Chapter 18 — AI Collaboration Rules

### 18.1 Agent Role Boundaries

| Agent | Primary Responsibility | May NOT Do |
|-------|-----------------------|------------|
| Human Architect | Define RFCs, approve architecture, set standards | Implement code (delegates) |
| Human Reviewer | Final review and merge approval | Modify code (only comments) |
| Codex | Code generation, implementation, prompt execution | Change architecture, create new modules without RFC |
| GPT-5.5 | Architecture review, refactoring suggestions, complex analysis | Direct code modification |
| DeepSeek | Bug detection, static analysis, security review | Code generation |
| GitHub Copilot | Inline completions within established patterns | Drive architecture or create new files |

### 18.2 Collaboration Principles

1. No overlapping responsibility - Every task has exactly one owner
2. RFC first - No agent changes architecture without an approved RFC
3. Standards always apply - Every agent follows this document
4. Human in the loop - All merges require human review
5. Output verification - Every AI output is verified against the acceptance criteria before delivery
6. Context preservation - Agents read the full context; partial context causes errors

### 18.3 Handoff Protocol

When one agent hands off to another:

1. The delivering agent includes its output and a summary of decisions made
2. The receiving agent reads the full context before acting
3. Any assumptions made by the delivering agent are explicitly documented
4. Unresolved questions are elevated to the Human Architect



---

## Chapter 19 — Future Compatibility

### 19.1 Module Expansion

The project structure supports adding new modules without restructuring:

- New public headers go in include/ak/<new_module>/
- Implementations go in src/<new_module>/
- New CMake target uses target_link_libraries(new_target PUBLIC ak_core)
- Tests go in tests/unit/<new_module>/ and tests/integration/<new_module>/

### 19.2 Plugin System Expansion

Plugin templates are in templates/Plugin/. A future plugin system will load shared libraries at runtime. Design implications:

- All public API must be ABI-stable (use opaque pointers / Pimpl where necessary)
- Plugin interfaces are pure abstract classes with virtual destructors
- No C++ standard library types cross the plugin boundary (use C-style primitives or ABI-safe wrappers)

### 19.3 Async Evolution

The architecture anticipates asynchronous execution. Design today for eventual async:

- All blocking operations are isolated in dedicated executor classes
- Interfaces return result types that can be made future-like (e.g., replace Result with std::future<Result>)
- Callbacks are injected as std::function - easily replaced with std::move_only_function in C++23

### 19.4 C++23 Forward Compatibility

When the project migrates to C++23:

- std::expected replaces exception-based error returns in performance-critical paths
- std::mdspan replaces manual index calculations
- std::print replaces the selected logging library formatting layer
- std::move_only_function replaces std::function for move-only callbacks

### 19.5 Standards Document Versioning

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-07-08 | Initial release - Phase 0, P0-02 |



---

## Chapter 20 — Summary

### 20.1 The Ten Commandments of Agent Kernel

1. One responsibility per class - No exceptions
2. Explicit ownership - Every object has one known owner
3. RAII always - No manual resource management
4. Dependency injection - No global state, no singletons
5. RFC driven - No architecture change without discussion
6. Fail fast - Detect errors early, report them clearly
7. Composable over inherited - Interfaces over base classes
8. Self-documenting code - Names explain intent; comments explain why
9. Tested at the boundary - Every public function has tests
10. AI and human readable - Code serves both audiences equally

### 20.2 Conformance

Every line of code generated by any AI agent for Agent Kernel must conform to this document. Non-conforming code will be rejected at review. If this document conflicts with a tool'''s default behavior (e.g., an AI model'''s built-in style preferences), this document takes precedence.

### 20.3 Document Authority

This document supersedes all earlier implicit conventions. For questions not covered by this document, consult the Human Architect. Ambiguities in this document should be reported as GitHub issues tagged standards-clarification.

---

*End of Engineering Standards - Agent Kernel v1.0*

