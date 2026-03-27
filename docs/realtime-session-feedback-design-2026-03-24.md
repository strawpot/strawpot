# Real-time Session Feedback for StrawPot CLI

**Date:** 2026-03-24
**Issue:** [#483](https://github.com/strawpot/strawpot/issues/483) (Gap 2)
**Author:** product-advisor
**Status:** Draft
**Strategic Review:** Passed (2026-03-24)

---

## Problem Statement

When a user runs `strawpot start --task "..."`, they see **nothing** until the entire session completes. Sessions take 5-20+ minutes (delegations to multiple roles, code generation, reviews). The user stares at a blank terminal with no progress, no status, no sense of what is happening.

The strawpot.com landing page shows an idealized progressive-checkmark experience that does not exist in the real product. This is the single highest-impact gap between the demo and reality.

## Demand Evidence

- Issue #483 consolidates #481 and #482 -- identified through a systematic audit of the demo-product gap
- The strawpot.com website prominently features the checkmark output as a selling point
- Any new user running `strawpot start --task` for the first time will experience 5+ minutes of silence, which reads as "broken"

## Status Quo

- **CLI task mode:** `Session.start()` calls `self.runtime.wait(handle)` and blocks with zero terminal output until the orchestrator exits (session.py L544-545)
- **CLI interactive mode:** User sees agent output because stdin/stdout are attached -- less painful but still no structured progress
- **GUI:** Has SSE infrastructure (`event_bus.py`, `sse.py`) and file watching (`watchfiles` on session directories), but no delegation-level progress events are surfaced
- **Trace system:** `trace.py` writes rich JSONL events (`delegate_start`, `delegate_end`, `agent_spawn`, `agent_end`, `ask_user_*`, `memory_*`) to `<session_dir>/trace.jsonl` -- **the data for feedback already exists, it is just not rendered**

## Target User & Narrowest Wedge

**Target:** Any StrawPot user running headless task sessions (`--task` flag). This includes:
- Developers using StrawPot for automated code tasks
- Scheduled/cron sessions via the GUI scheduler
- CI/CD integrations

**Narrowest wedge:** Progressive checkmark output to stderr during `strawpot start --task` sessions, driven by delegation lifecycle events the Session class already handles.

## Constraints

1. Must work in headless/agent mode (no interactive prompts, no hang risk)
2. Must work in both CLI and GUI contexts with the same underlying mechanism
3. Stage names must be dynamic (reflect actual roles used), not hardcoded
4. Must degrade gracefully (if rendering fails, session continues)
5. Output goes to stderr (stdout reserved for agent output in task mode)
6. No changes to the denden gRPC protocol in v1

## Premises

1. **The trace system already captures every signal needed.** `delegate_start`, `delegate_end`, `agent_spawn`, and `agent_end` events contain role, task, timing, and exit code. No new data collection is required.
2. **Session._handle_delegate is the natural hook point.** It processes every delegation request and already knows role slug, task text, start time, and completion status.
3. **The primary pain is task mode.** Interactive mode shows agent output; task mode shows nothing. The fix should prioritize task mode but benefit both.
4. **Rendering is a separate concern from event emission.** The Session should emit structured events; renderers (CLI terminal, GUI SSE, file trace) should be pluggable consumers.
5. **denden protocol changes are out of scope.** Agent-initiated progress events (agents reporting their own sub-steps) would be valuable but is an ocean -- v1 uses session-level signals only.

## Approaches Considered

### Approach A: Trace File Tailer (Minimal Viable)

**Summary:** Add a background thread in task mode that tails `trace.jsonl` using `watchfiles`, parses events, and renders checkmark lines to stderr.

**How it works:**
1. Before `runtime.wait(handle)`, spawn a daemon thread that watches `trace.jsonl`
2. On each new line, parse the JSONL event and render if it's a `delegate_start` or `delegate_end`
3. Thread exits when the session ends

**Effort:** S (human: 2 days / AI: 30 min)
**Risk:** Low

| Pros | Cons |
|---|---|
| Smallest diff -- ~80 lines, all in cli.py or a new renderer module | Slight latency: file write + fsnotify + read (typically <100ms but varies by OS) |
| No changes to Session internals | Requires `trace=true` (currently default, but could be disabled) |
| Works today with existing trace infrastructure | Duplicates parsing logic that the GUI already has |
| Easy to test -- just check file output | Cannot surface events that aren't traced (future: ask_user prompts in progress) |

**Existing code reused:** `trace.py` (producer), `watchfiles` (already a dependency for GUI)

---

### Approach B: Session Event Callback (Recommended)

**Summary:** Add a pluggable event callback to the `Session` class. On delegation start/end and other lifecycle events, the Session calls registered listeners. The CLI registers a terminal renderer; the GUI registers an SSE publisher.

**How it works:**
1. Define a `ProgressEvent` dataclass with `kind`, `role`, `detail`, `timestamp`, `duration_ms`, `status`, `depth`
2. Add `on_event: Callable[[ProgressEvent], None] | None` to `Session.__init__`
3. Add a central `_emit_event()` method with try/except guard for graceful degradation
4. In `_handle_delegate`, emit events at delegation start and end (all 7 exit paths covered)
5. In `start()`, emit session-level events (session started, orchestrator spawned, cleanup)
6. CLI task mode passes a `TerminalProgressRenderer` that prints checkmarks to stderr
7. GUI passes an adapter that publishes to the `EventBus`

**Effort:** M (human: 1 week / AI: 1 hour)
**Risk:** Low

| Pros | Cons |
|---|---|
| Real-time -- no file I/O latency, events fire inline | Touches Session internals (but minimally -- one callback call per event) |
| Works regardless of trace config | ~200 lines across 3 files (session.py, new renderer, cli.py) vs ~80 for Approach A |
| Clean separation: Session emits, renderers consume | Callback runs on the delegation handler thread -- renderer must be fast and non-blocking |
| GUI can use the same events for a live timeline | |
| Natural extension point for future event types | |
| Testable: mock the callback, assert events emitted | |

**Existing code reused:** `EventBus` pattern from GUI (same pub/sub concept), `TraceEvent` field names, `ask_user_handler` callback pattern

---

### Approach C: denden Protocol Extension (Ideal Architecture)

**Summary:** Extend the denden gRPC protocol with a `Progress` message type. Agents can emit progress events (e.g., "reading codebase", "writing tests", "creating PR") that flow through the orchestrator to the CLI/GUI. Session-level events from Approach B are also included.

**How it works:**
1. Add `Progress` message to `denden.proto`: `{ stage: string, detail: string, percent: float }`
2. Add `on_progress` handler to `DenDenServer`
3. Agents call `denden send '{"progress":{"stage":"Writing tests","detail":"12/15 complete"}}'`
4. Session surfaces these alongside its own delegation lifecycle events
5. CLI renders a rich progress display (stages + sub-steps)

**Effort:** XL (human: 3 weeks / AI: 4 hours)
**Risk:** High

| Pros | Cons |
|---|---|
| Most informative -- agents report their own progress | Protocol change requires updating denden, all wrappers, and the denden skill docs |
| Enables sub-step visibility ("writing file 3/7") | Agents must opt in -- existing agents produce no progress events until updated |
| Future-proof architecture | Significantly larger scope -- protocol, server, client, renderers, docs |
| | Risk of noisy/inconsistent progress from different agents |

**Existing code reused:** `DenDenServer` handler pattern, `denden.proto` extension point

---

## Recommended Approach

**Approach B: Session Event Callback**, with Approach A's trace-file mechanism as a fallback for the GUI.

**Rationale:**

1. **Completeness at low cost.** Per the completeness principle, the delta between A (~80 lines) and B (~200 lines) is trivial with AI agents. B gives a cleaner architecture, real-time delivery, and GUI compatibility -- the extra lines are free.

2. **Right abstraction boundary.** The Session already handles every delegation. Adding a callback is the natural extension -- it doesn't require trace to be enabled, doesn't add file I/O latency, and creates a clean contract between event producer (Session) and consumer (renderer).

3. **Approach C is an ocean.** Valuable but unbounded -- protocol changes ripple through denden, all agent wrappers, skill documentation, and require every agent to opt in. We should build B now and layer C on top later if needed.

4. **Phased delivery.** B ships useful progress output immediately. The same event callback can later feed Approach C's richer events without rewriting.

## Detailed Architecture

### ProgressEvent Dataclass

Named `ProgressEvent` (not `SessionEvent`) to avoid collision with the GUI's existing `gui.event_bus.SessionEvent` class, which has different fields (`kind`, `run_id`, `project_id`, `data`).

```python
@dataclass
class ProgressEvent:
    kind: str          # "session_start" | "delegate_start" | "delegate_end" | ...
    role: str          # Role slug (e.g., "implementer", "code-reviewer")
    detail: str        # Human-readable detail (truncated task text or reason)
    timestamp: str     # ISO 8601 UTC wall clock (matches tracer convention)
    duration_ms: int   # 0 for start events, elapsed for end events
    status: str        # "ok" | "error" | "denied" | "cached" | "" (for start events)
    depth: int         # Delegation depth (0 = orchestrator)
```

**Timestamp convention:** Uses wall clock ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`), matching the `TraceEvent.ts` field convention. Durations are computed as deltas between start/end event pairs. This keeps `ProgressEvent` consistent with the trace system and avoids dual-timestamp complexity.

### Central Event Emission Method

All event emission goes through a single `_emit_event()` method on Session. This is the **only** place the `on_event` callback is invoked, providing a single point for error handling, logging, and future behavior (e.g., disable after N failures).

```python
def _emit_event(self, event: ProgressEvent) -> None:
    """Emit a progress event to the registered callback.

    Swallows all exceptions -- a failing renderer must never
    crash the session.
    """
    if self._on_event is None:
        return
    try:
        self._on_event(event)
    except Exception:
        logger.debug("Event callback failed", exc_info=True)
```

### _handle_delegate Exit Path Mapping

`_handle_delegate` has 7 distinct exit paths. Each must emit the correct events:

```
_handle_delegate()
|
+-- 1. Max delegations exceeded (L1069)
|   emit: delegate_denied(status="denied", detail="DENY_DELEGATIONS_LIMIT")
|
+-- 2. Cache hit, fast path (L1096)
|   emit: delegate_cached(status="cached")
|
+-- 3. Cache hit, after lock (L1140)
|   emit: delegate_cached(status="cached")
|
+-- 4. Success (L1202)
|   emit: delegate_start(status="") ... [delegation runs] ... delegate_end(status="ok")
|
+-- 5. Non-zero exit (L1185)
|   emit: delegate_start(status="") ... [delegation runs] ... delegate_end(status="error")
|
+-- 6. PolicyDenied (L1206)
|   emit: delegate_start(status="") ... delegate_denied(status="denied")
|
+-- 7. Exception (L1217)
    emit: delegate_start(status="") ... delegate_end(status="error")
```

**Key placement rule:** For paths 4-7, `delegate_start` is emitted **after** cache checks pass (after L1167), not at the top of the method. This ensures cache hits don't produce spurious start events.

### Event Kinds

| Event | Where emitted | Key data |
|---|---|---|
| `session_start` | `Session.start()` after session setup | role=orchestrator_role |
| `delegate_start` | `_handle_delegate()` after cache checks, before `handle_delegate()` call | role, task summary |
| `delegate_end` | `_handle_delegate()` after result (paths 4, 5, 7) | role, duration, status |
| `delegate_denied` | `_handle_delegate()` on max limit (path 1) or PolicyDenied (path 6) | role, reason |
| `delegate_cached` | `_handle_delegate()` on cache hit (paths 2, 3) | role |
| `ask_user_start` | `_handle_ask_user()` before handler call | role, question summary |
| `ask_user_end` | `_handle_ask_user()` after response | role, duration |
| `session_end` | `Session.stop()` | duration, exit_code, files_changed count |

### Thread Safety

`_handle_delegate` runs on the denden gRPC server's thread pool. Multiple delegations can run concurrently (proven by the per-key cache locks at L1126-1134). The renderer must be thread-safe.

**Strategy:** The `TerminalProgressRenderer` owns a `threading.Lock()`. All stderr writes are serialized through this lock. The lock is internal to the renderer -- `Session._emit_event()` does not need its own lock because it only calls the callback (a single function call is thread-safe).

### BrokenPipeError Handling

When stderr is piped or redirected (`2>/dev/null`, `2>&1 | head`), writing can raise `BrokenPipeError`. The renderer catches this and silently disables further writes:

```python
class TerminalProgressRenderer:
    def __init__(self):
        self._lock = threading.Lock()
        self._disabled = False

    def handle_event(self, event: ProgressEvent) -> None:
        if self._disabled:
            return
        with self._lock:
            try:
                self._render(event)
            except (BrokenPipeError, OSError):
                self._disabled = True
```

### CLI Terminal Renderer Output

```
$ strawpot start --task "Add dark mode toggle"

  Session started (orchestrator: ai-ceo)

  > Delegating to product-advisor...
  [checkmark] product-advisor completed (12s)

  > Delegating to implementer...
    > Delegating to code-reviewer... (depth 2)
    [checkmark] code-reviewer completed (34s)
  [checkmark] implementer completed (2m 47s)

  > Delegating to pr-reviewer...
  [checkmark] pr-reviewer completed (1m 12s)

  [checkmark] Session complete (5m 32s) - 7 files changed
```

**Rendering rules:**
- Output to stderr (stdout reserved for final agent output)
- Indent nested delegations by depth (2 spaces per level)
- Show `>` arrow for in-progress, checkmark for success, X for failure
- Truncate task text to first 60 chars for the "Delegating to..." line
- Format durations human-readably (seconds, minutes)
- Use Unicode checkmark/cross with color when terminal supports it, ASCII fallback otherwise
- Cached delegations show with "(cached)" suffix
- Terminal title updated to show current active role (e.g., `\033]0;StrawPot: implementer (2m)\007`)

### JSON Progress Mode

For CI/CD and machine consumption, `--progress json` outputs one JSON object per line to stderr instead of human-readable checkmarks:

```
$ strawpot start --task "..." --progress json

{"kind":"session_start","role":"ai-ceo","detail":"","timestamp":"2026-03-24T10:00:00Z","duration_ms":0,"status":"","depth":0}
{"kind":"delegate_start","role":"implementer","detail":"Add dark mode toggle...","timestamp":"2026-03-24T10:00:01Z","duration_ms":0,"status":"","depth":1}
{"kind":"delegate_end","role":"implementer","detail":"","timestamp":"2026-03-24T10:02:48Z","duration_ms":167000,"status":"ok","depth":1}
{"kind":"session_end","role":"ai-ceo","detail":"7 files changed","timestamp":"2026-03-24T10:05:32Z","duration_ms":332000,"status":"ok","depth":0}
```

This reuses the same `ProgressEvent` data -- the renderer just serializes differently.

### Architecture Diagram

```
+--------------------------------------------------------------+
|                          cli.py                               |
|                                                               |
|  start() command                                              |
|    |                                                          |
|    +-- if task mode:                                          |
|    |     if --progress json: renderer = JsonProgressRenderer()|
|    |     else:               renderer = TerminalProgressRend()|
|    |                                                          |
|    +-- Session(on_event=renderer.handle_event)                |
|                                                               |
+--------------------------------------------------------------+
                              |
                              v
+--------------------------------------------------------------+
|                        session.py                             |
|                                                               |
|  Session.__init__(on_event: Callable[[ProgressEvent], None])  |
|                                                               |
|  _emit_event(event) --- try/except wrapper ------+           |
|       |                                           |           |
|       +-- start()          -> session_start       |           |
|       +-- _handle_delegate -> delegate_*          |           |
|       +-- _handle_ask_user -> ask_user_*          |           |
|       +-- stop()           -> session_end         |           |
|                                                   |           |
|  Also calls self._tracer.* (unchanged)            |           |
|                                                               |
+--------------------------------------------------------------+
                              |
                    on_event(ProgressEvent)
                              |
              +---------------+---------------+
              v                               v
+-------------------------+   +------------------------------+
| TerminalProgressRenderer|   | EventBusAdapter (GUI)        |
|                          |   |                              |
| - threading.Lock         |   | Maps ProgressEvent ->        |
| - sys.stderr.write()    |   | gui.SessionEvent              |
| - BrokenPipeError guard |   | Publishes to EventBus        |
| - Unicode/ASCII detect  |   |                              |
| - _disabled flag         |   |                              |
+-------------------------+   +------------------------------+
```

## Open Questions

1. **Should we show ask_user events in progress output?** In headless mode, ask_user gets auto-responded. Showing "Waiting for user input..." then immediately "Response received" adds noise. Recommendation: show only if duration > 2s (implies actual human interaction via GUI bridge).

2. **Should cached delegations appear?** Cache hits are instant but still represent completed work. Recommendation: show with a "(cached)" suffix -- it's informative and helps users understand why re-runs are faster.

3. **Verbose mode?** Should `--verbose` show task text snippets alongside role names? Recommendation: yes, add a `--progress-verbose` or respect existing `-v` flag to show truncated task text.

4. **GUI integration priority?** The GUI already has SSE and event_bus. Should we wire up the ProgressEvent adapter in v1 or defer? Recommendation: wire it up -- it's ~20 lines to bridge ProgressEvent to the existing EventBus, and the GUI frontend can consume it when ready.

## Success Criteria

- [ ] Running `strawpot start --task "..."` produces progressive output showing each delegation stage as it starts and completes
- [ ] Each line identifies the role that is active or completed
- [ ] Durations are shown for completed stages
- [ ] Nested delegations are visually indented
- [ ] Final summary line shows total duration and files changed count
- [ ] Output goes to stderr (stdout contains only final agent output)
- [ ] Works in headless mode with no interactive prompts
- [ ] Degrades gracefully: `_emit_event()` catches all exceptions; renderer catches BrokenPipeError
- [ ] Stage names are dynamic (derived from actual delegation roles, not hardcoded)
- [ ] GUI EventBus receives the same events (adapter wired up)
- [ ] `--progress json` mode outputs machine-readable JSONL to stderr
- [ ] Terminal title updates to show current active role

## Dependencies

- `strawpot` CLI (session.py, cli.py) -- primary changes
- `strawpot-gui` (event_bus adapter) -- small addition
- No changes to denden, agent wrappers, or the gRPC protocol

## Phased Implementation Plan

### Phase 1: Core event callback + CLI renderer (ships first)
- Define `ProgressEvent` dataclass (new file: `cli/src/strawpot/progress.py`)
- Add `on_event` callback and `_emit_event()` to `Session.__init__` / session.py
- Emit events from all 7 `_handle_delegate` exit paths, `_handle_ask_user`, `start()`, `stop()`
- Implement `TerminalProgressRenderer` with checkmark output to stderr (thread-safe, BrokenPipeError-safe)
- Implement `JsonProgressRenderer` for `--progress json` mode
- Add `--progress` flag to `cli.py` `start()` command (`auto` | `json` | `off`; default `auto` = enabled for task mode)
- Terminal title updates for active role
- Wire up in `cli.py` `start()` command
- Wire up GUI `EventBusAdapter` (~20 lines)
- Tests (see test plan below)

### Phase 2: Polish (follow-up)
- Color support with terminal capability detection
- `--progress-verbose` flag for task text display
- Spinner animation for long-running delegations (if terminal supports it)

### Phase 3: Future -- Agent-initiated progress (Approach C)
- Extend denden protocol with `Progress` message
- Update denden skill documentation
- Agents opt in to progress reporting
- Merge agent progress with session lifecycle events in renderer

## Test Plan

### Unit tests: TerminalProgressRenderer
1. Renders `delegate_start` with correct indentation by depth
2. Renders `delegate_end` with duration formatting (seconds, minutes)
3. Renders `delegate_denied` with X mark
4. Renders `delegate_cached` with "(cached)" suffix
5. Renders `session_start` / `session_end` with summary
6. Handles Unicode checkmark/cross and ASCII fallback
7. Thread safety: concurrent events don't garble output (multiple threads writing)
8. BrokenPipeError disables renderer without crash
9. OSError disables renderer without crash

### Unit tests: JsonProgressRenderer
1. Outputs valid JSON per line
2. Contains all ProgressEvent fields

### Unit tests: Session event emission
1. `_handle_delegate` success path emits start + end(ok)
2. `_handle_delegate` cache hit (fast path) emits cached event only
3. `_handle_delegate` cache hit (after lock) emits cached event only
4. `_handle_delegate` max delegations denied emits denied event
5. `_handle_delegate` PolicyDenied emits start + denied
6. `_handle_delegate` exception emits start + end(error)
7. `_handle_delegate` non-zero exit emits start + end(error)
8. `_handle_ask_user` emits ask_user_start + ask_user_end
9. `Session.start()` emits session_start
10. `Session.stop()` emits session_end
11. Callback=None produces no errors (no-op)
12. Callback raises -> session continues (graceful degradation via _emit_event)
13. Depth values match what tracer receives

### Integration test
1. Full session with mock agent -> verify complete event sequence matches expected order

## The Assignment

Ship Phase 1. Define `ProgressEvent`, add the callback to `Session`, implement both renderers, wire it up in `cli.py` and the GUI adapter. This is a bounded lake -- ~200 lines across 4 files, all within the strawpot CLI package plus ~20 lines for the GUI adapter.

## What I Noticed

- The trace system (`trace.py`) is remarkably well-designed -- content-addressed artifact storage, span-based event model, full delegation call tree. The architecture already anticipates observability; the gap is purely that these events don't reach the terminal.
- The Session class handles delegations, ask_user, memory, and caching all through clean handler methods. Adding an event callback is a natural extension of this pattern -- identical to the existing `ask_user_handler` callback.
- The GUI's `EventBus` is exactly the right abstraction for the GUI side -- but the existing `SessionEvent` class has different fields, so the new class is named `ProgressEvent` to avoid collision.
- The `_handle_delegate` method has 7 distinct exit paths (max limit, 2 cache paths, success, non-zero exit, PolicyDenied, exception). Each is mapped to specific events in this design.
