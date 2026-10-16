cmake_minimum_required(VERSION 3.22)

project(agent-kernel
    VERSION 0.1.0
    DESCRIPTION "Agent Kernel - Modular runtime for AI Agents"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
    message(FATAL_ERROR "In-source builds are forbidden. Use a separate build directory.")
endif()

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build type" FORCE)
endif()
set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS
    Debug Release RelWithDebInfo MinSizeRel
)

option(AK_BUILD_TESTS    "Build unit and integration tests"      ON)
option(AK_BUILD_EXAMPLES "Build example programs"                ON)
option(AK_BUILD_PROTOTYPE "Build AVP0000 architecture validation prototype" ON)
option(AK_ENABLE_INSTALL "Generate install and export targets"   OFF)

if(MSVC)
    add_compile_options(/W4 /WX /utf-8 /MP)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -Werror)
endif()

if(AK_BUILD_TESTS)
    enable_testing()
endif()

add_subdirectory(src)
add_subdirectory(runtime)
add_subdirectory(src/runtime_integration)
add_subdirectory(src/runtime_backed_agent)
add_subdirectory(src/model_to_runtime)
add_subdirectory(src/agent_continuation)

if(AK_BUILD_PROTOTYPE AND EXISTS
   "${CMAKE_CURRENT_SOURCE_DIR}/prototype/avp0000/CMakeLists.txt")
    add_subdirectory(prototype/avp0000)
endif()

if(AK_BUILD_PROTOTYPE AND EXISTS
   "${CMAKE_CURRENT_SOURCE_DIR}/prototype/avp0001/CMakeLists.txt")
    add_subdirectory(prototype/avp0001)
endif()

if(AK_BUILD_TESTS)
    add_subdirectory(tests)
endif()

if(AK_BUILD_EXAMPLES)
    add_subdirectory(examples)
endif()

if(AK_ENABLE_INSTALL)
    include(GNUInstallDirs)
    include(CMakePackageConfigHelpers)

    set(AK_EXPORT_NAME AgentKernelTargets)
    set(AK_CONFIG_INSTALL_DIR "${CMAKE_INSTALL_LIBDIR}/cmake/AgentKernel")

    install(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/include/"
        DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
        FILES_MATCHING PATTERN "*.hpp"
    )

    install(TARGETS agent_kernel agent_kernel_foundation
        EXPORT ${AK_EXPORT_NAME}
        INCLUDES DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
        ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
    )

    install(EXPORT ${AK_EXPORT_NAME}
        FILE AgentKernelTargets.cmake
        NAMESPACE AK::
        DESTINATION "${AK_CONFIG_INSTALL_DIR}"
    )

    configure_package_config_file(
        "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Config.cmake.in"
        "${CMAKE_CURRENT_BINARY_DIR}/AgentKernelConfig.cmake"
        INSTALL_DESTINATION "${AK_CONFIG_INSTALL_DIR}"
    )

    install(FILES "${CMAKE_CURRENT_BINARY_DIR}/AgentKernelConfig.cmake"
        DESTINATION "${AK_CONFIG_INSTALL_DIR}"
    )
endif()

message(STATUS "Agent Kernel v${PROJECT_VERSION}")
message(STATUS "Build type:   ${CMAKE_BUILD_TYPE}")
message(STATUS "C++ standard: ${CMAKE_CXX_STANDARD}")
