# Example CLAUDE.md Files

These are hand-crafted examples of what `strawpot init` generates. Each showcases domain-specific rules that help AI coding agents understand your project's conventions, constraints, and architecture.

## Examples

| File | Domain | Rules | Language |
|------|--------|-------|----------|
| [game-engine-cpp.claude.md](game-engine-cpp.claude.md) | C++ game engine (Vulkan, ECS, job system) | 26 | C++ |
| [web-api-python.claude.md](web-api-python.claude.md) | Python web API (FastAPI, PostgreSQL, JWT) | 20 | Python |
| [web-frontend-react.claude.md](web-frontend-react.claude.md) | React + TypeScript frontend (Vite, Zustand) | 18 | TypeScript |

## How to Use

1. **Copy** the example closest to your project type into your project root as `CLAUDE.md`
2. **Customize** the TODO sections with your project-specific rules
3. **Delete** rules that don't apply to your project
4. **Add** rules for your specific tools, libraries, and conventions

## Automated Generation

For a tailored configuration, run:

```bash
strawpot init
```

This walks you through an adaptive questionnaire and generates CLAUDE.md files customized to your exact project structure, languages, and frameworks.

## Quality Bar

Each example must have ≥3 rules that an experienced developer in that domain would say "I wouldn't have thought to include that." Generic advice ("write tests", "use version control") doesn't make the cut. Rules must be specific and actionable.
