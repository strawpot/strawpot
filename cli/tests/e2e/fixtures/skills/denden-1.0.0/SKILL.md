---
name: denden
description: DenDen communication skill — delegate, ask, and remember
---
Use the `denden` CLI to communicate with the orchestrator.

## Commands

### Delegate to another agent

```bash
denden send '{"denden_version":"1","request_id":"<uuid>","trace":{...},"delegate":{"delegate_to":"<role>","task":{"text":"<task description>"}}}'
```

Use delegation when the task requires a different role's expertise. Read the
target role's `ROLE.md` before delegating so you can write a clear task.

### Ask your requester

```bash
denden send '{"denden_version":"1","request_id":"<uuid>","trace":{...},"ask_user":{"question":"<question>","why":"<reason>"}}'
```

Use this when you need task clarification or domain knowledge from the role
that delegated work to you.

### Remember knowledge

```bash
denden send '{"denden_version":"1","request_id":"<uuid>","trace":{...},"remember":{"content":"<what to remember>","keywords":["kw1","kw2"],"scope":"project"}}'
```

Use `remember` to persist knowledge that will be useful in future sessions:
- **Stable facts** discovered during work (architecture decisions, conventions, key paths)
- **Lessons learned** from debugging or problem-solving
- **User preferences** for workflow, tools, or communication style

Guidelines:
- Include `keywords` for topic-specific knowledge so it surfaces when relevant.
- Omit `keywords` (or leave empty) for knowledge that should always be included.
- `scope` is one of `"global"`, `"project"`, or `"role"` (default: `"project"`).
- Do NOT remember transient or session-specific information.
