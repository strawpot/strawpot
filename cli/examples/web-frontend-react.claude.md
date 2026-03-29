# Client

This is the **client** component of ExampleApp, a React + TypeScript frontend using Vite, Zustand for state management, and Tailwind CSS.

## Build Commands

```bash
npm install
npm run dev          # Development server (Vite)
npm run build        # Production build
npm run test         # Vitest
npm run lint         # ESLint + Prettier check
npm run typecheck    # tsc --noEmit
```

## Hard Rules

These rules must always be followed:

- Enable strict mode in `tsconfig.json` (`"strict": true`). Never use `any` type — use `unknown` and narrow with type guards when the type is truly unknown. If a library has bad types, create a `.d.ts` override rather than using `any`.
- All function parameters and return types must have explicit type annotations. Let TypeScript infer types for local variables only.
- Never use non-null assertion (`!`) in production code. Use proper null checks or optional chaining (`?.`) instead. The `!` operator hides bugs that TypeScript would otherwise catch.
- Never trust data from the API — validate with `zod` at the API boundary. TypeScript types are compile-time only; `zod` schemas provide runtime validation. Define API response schemas that match the backend's OpenAPI spec.
- React hooks must follow the Rules of Hooks: only call at the top level, only call from React functions. Never conditionally call hooks. Extract complex logic into custom hooks.
- Components must not directly call `fetch` or API functions. Use a data layer (React Query / TanStack Query) that handles caching, deduplication, and error states. Components consume data, they don't fetch it.
- All user-visible text must go through the i18n system (`react-intl` or `i18next`). Never hardcode English strings in components — even if the app is English-only today.
- Form inputs must always be controlled components with explicit value and onChange. Never use uncontrolled inputs with refs for form data — they bypass React's rendering cycle and break validation.

## Soft Rules

Follow these conventions unless there's a good reason not to:

- Use named exports, not default exports. Named exports are refactor-friendly, greppable, and work better with tree shaking. Exception: page components for file-based routing.
- State management hierarchy: local state (`useState`) → component-tree state (`useContext`) → global state (Zustand store). Never reach for global state when local state suffices. Zustand stores are for truly global concerns (auth, theme, notifications).
- Prefer composition over prop drilling. Use the compound component pattern for complex UI (Tabs, Accordion, Dropdown). Use `children` and render props before reaching for `useContext`.
- CSS: use Tailwind utility classes for layout and spacing. Extract repeated patterns into component variants (CVA or class-variance-authority), not CSS files. Avoid `@apply` — it defeats the purpose of utility classes.
- Performance: wrap expensive list items with `React.memo()`. Use `useMemo` for expensive computations, `useCallback` for callbacks passed to memoized children. Don't memoize everything — profile first.
- Use `React.lazy()` and `Suspense` for route-based code splitting. The initial bundle must load the shell and first route only. Other routes load on navigation.
- Accessibility: every interactive element must be keyboard-navigable. Use semantic HTML (`button`, `nav`, `main`, `dialog`). Add `aria-label` to icon-only buttons. Test with keyboard and screen reader.
- Error boundaries: wrap each major section (sidebar, main content, modals) in an error boundary. A crash in the sidebar shouldn't take down the whole page. Show a "retry" button, not a blank screen.

## Cross-Component Awareness

- API types must match the backend's OpenAPI schema. Import shared types from `shared/` — never manually define API response types in the frontend. If the types drift, the `zod` validation will catch it at runtime.
- The server is authoritative for all business logic. Client-side validation is for UX only — never skip server-side validation because "the frontend already checks it."

## Architecture Guide

```
src/
├── app/              # App shell, routing, providers
├── pages/            # Page-level components (one per route)
├── features/         # Feature modules (auth, dashboard, settings)
│   └── auth/
│       ├── components/   # Feature-specific components
│       ├── hooks/        # Feature-specific hooks
│       ├── api.ts        # API calls for this feature
│       └── store.ts      # Zustand store slice
├── components/       # Shared UI components (Button, Modal, etc.)
├── hooks/            # Shared custom hooks
├── lib/              # Third-party wrappers (API client, i18n)
├── types/            # Shared TypeScript types
└── utils/            # Pure utility functions (no React)
```

Feature modules are self-contained. A feature can import from `components/`, `hooks/`, `lib/`, and `types/` — but never from another feature. Cross-feature communication goes through Zustand stores or URL state.

## Project-Specific Rules

<!-- TODO: Add rules specific to your project -->
<!-- Examples: specific component library conventions, custom hooks patterns, specific API client configuration -->
