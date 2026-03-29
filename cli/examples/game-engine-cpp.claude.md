<!-- strawpot:meta
generated: 2026-03-29T12:00:00Z
archetype: game-engine
language: C++
component: engine
rule_count: 26
dirs_at_gen: [src, include, shaders, assets, tests]
build_file_hash: example
-->

# Engine

This is the **engine** component of ExampleGame, a C++ game engine using Vulkan, archetype-based ECS, and a job system for parallelism. Built with CMake.

## Build Commands

```bash
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

## Hard Rules

These rules must always be followed:

- No raw `new`/`delete`. Use `std::unique_ptr` for single ownership, `std::shared_ptr` only when ownership is genuinely shared. If you're reaching for `shared_ptr`, reconsider the ownership model first.
- No heap allocations in the hot loop (update/render). Pre-allocate in `init()`, use pool allocators for per-frame data. If you need a temporary buffer in a system, use the job system's per-thread scratch allocator.
- Every public header must be self-contained — including it alone must compile without errors. Use `#pragma once` and forward-declare types in headers wherever possible.
- All GPU resources must have explicit lifetime management. No resource may outlive the device or context that created it.
- Vulkan objects must be destroyed in reverse creation order. Never destroy a `VkDevice` before all objects created from it. Use validation layers (`VK_LAYER_KHRONOS_validation`) in all debug builds.
- All Vulkan API calls must check `VkResult`. Wrap calls in a `VK_CHECK` macro that logs the error code and file/line on failure. Never silently ignore a failed Vulkan call.
- ECS components must be trivially copyable (POD types). No virtual functions, no `std::string`, no heap-owning members. Use handles/IDs to reference complex objects. If a component needs a string, store a `StringId` (hashed) instead.
- Never store pointers to ECS components — archetype moves invalidate them. Always access components through entity queries within the current frame. Cache entity IDs, not component pointers.
- ECS systems may execute in parallel via the job system. Shared mutable state requires explicit synchronization — prefer lock-free queues or double-buffered data over mutexes in the hot path.
- Jobs must not allocate heap memory. Use the job system's per-thread scratch allocator. Jobs must be pure functions of their input data — no global state access, no singleton references.
- Fixed-point or integer math for gameplay logic that must be deterministic across platforms. Floating-point is fine for rendering, not for netcode-sensitive state.
- Never block the main thread on file I/O. Use async loading with callbacks or futures. Show placeholder assets while loading.
- All engine subsystems must support hot-reload of assets (shaders, textures, configs) in debug builds. Production builds may skip this but must use the same asset pipeline.

## Soft Rules

Follow these conventions unless there's a good reason not to:

- Naming: `PascalCase` for types and namespaces, `camelCase` for functions and methods, `snake_case` for local variables, `SCREAMING_SNAKE_CASE` for constants and macros.
- Prefer composition over inheritance. Use ECS components and systems rather than deep class hierarchies. The engine has zero classes with more than 2 levels of inheritance.
- Shader source files live alongside the C++ code that uses them. Group by feature (`rendering/shadows/`), not by file type (`shaders/`).
- Prefer `constexpr` over `#define` for compile-time constants. Use `static_assert` for compile-time validation of assumptions.
- Error handling: use error codes in the hot path (no exceptions in update/render). Exceptions are acceptable in initialization and asset loading.
- Profile before optimizing. Mark hot functions with `ALWAYS_INLINE` or equivalent only after profiler data confirms they're bottlenecks. Premature `ALWAYS_INLINE` bloats the instruction cache.
- Asset loading must be asynchronous. Never block the main thread waiting for disk I/O or network resources. Use a loading thread pool with priority queues.

## Cross-Component Awareness

- When modifying `shared/*.proto` or shared data definitions, regenerate C++ bindings (`protoc --cpp_out`) before building the engine.
- The server (`server/`) has authoritative game state. Engine-side state is for rendering and client-side prediction only — never trust it for gameplay logic.
- The client UI layer (`client/`) may call engine APIs for rendering. Engine APIs exposed to the client must be thread-safe or documented as main-thread-only.

## Architecture Guide

The engine follows a strict layered architecture:

```
Platform Layer (OS, windowing, input)
  ↓
Core Layer (memory allocators, containers, math)
  ↓
ECS Layer (archetypes, systems, queries)
  ↓
Render Layer (Vulkan abstraction, render graph)
  ↓
Game Layer (systems that implement gameplay)
```

Lower layers never depend on higher layers. The Game Layer registers systems with the ECS Layer; the Render Layer reads component data through queries.

## What NOT To Do

- Don't add `std::map` or `std::unordered_map` in hot paths. Use flat arrays with ID-based lookup. The cache misses from node-based containers destroy frame time.
- Don't use RTTI (`dynamic_cast`, `typeid`). The ECS provides type-safe component access without runtime type information.
- Don't add global constructors or `static` objects with non-trivial destructors. They create hidden initialization order dependencies and prevent clean shutdown.

## Project-Specific Rules

<!-- TODO: Add rules specific to your project that templates can't cover -->
<!-- Examples: specific Vulkan extension requirements, custom memory allocator conventions, shader compilation pipeline details -->
