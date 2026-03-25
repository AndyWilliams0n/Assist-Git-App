## UI Engineering Rules

This document defines coding direction for agents and developers working in the `ui` app.
Use these rules for all new code and while refactoring existing code.

## Core Principles

- Prefer consistency over personal preference.
- Keep code small, modular, and easy to scan.
- Reuse existing shared components before creating new ones.
- Keep feature logic inside features and keep shared code generic.
- Optimize for readability, maintainability, and predictable patterns.

## Application Folder Structure

Use this structure as the default layout for the `ui/src` codebase:

```text
src/
  features/
  layouts/
  router/
  shared/
    components/
      ui/
    hooks/
    store/
    types/
    utils/
```

### Folder Responsibilities

- `features/`: Feature-specific pages, components, hooks, state, and services.
- `layouts/`: App-wide page shells and layout composition.
- `router/`: Route definitions, guards, and route-level wiring.
- `shared/components/`: Reusable app-level components used by multiple features.
- `shared/components/ui/`: shadcn-based primitive UI building blocks.
- `shared/hooks/`: Generic reusable hooks without feature-specific behavior.
- `shared/store/`: Shared state utilities and global store slices.
- `shared/types/`: Shared interfaces, domain types, and type helpers.
- `shared/utils/`: Pure utility helpers and formatting functions.

## Feature Structure

Each feature lives under `src/features/<feature-name>/`.
Use the following structure when creating or expanding a feature:

```text
features/<feature-name>/
  components/
  hooks/
  services/
  store/
  types/
  utils/
  <FeatureName>Page.tsx
  index.ts
```

### Feature Rules

- Keep feature-only code inside its feature folder.
- Add `index.ts` exports to keep imports clean and predictable.
- Keep components focused and avoid multi-purpose "god components."
- Put API and side-effect logic in `services/`, not in UI components.
- Keep business logic in hooks/services/store and keep rendering components presentational where possible.
- Move code to `shared/` only when at least two features use it and the abstraction is stable.

## shadcn and UI Primitives

Use shadcn primitives from `shared/components/ui` as the first choice for base UI.

### Rules for shadcn Usage

- Reuse existing primitives before creating a new one.
- Extend primitives through composition instead of copy-pasting component internals.
- Keep app-specific wrappers in `shared/components/` or the owning feature, not in `shared/components/ui`.
- Maintain accessibility defaults (keyboard support, labels, aria attributes, focus states).
- Prefer consistent variant patterns for size, intent, and state.

### Styling Guidance

- Use Tailwind utility classes and shared variant patterns consistently.
- Avoid one-off styling that breaks visual consistency across screens.
- Keep component styles close to the component unless they are cross-cutting.
- Respect existing spacing, typography, radius, and color conventions.

### Tailwind Class Order (Best Practice)

Write classes in a predictable order so class lists stay readable and easy to diff.

#### Utility Group Order

1. Position: `static`, `relative`, `absolute`, `fixed`, `sticky`, inset, z-index.
2. Display and visibility: `block`, `flex`, `grid`, `hidden`, `sr-only`.
3. Flex and grid layout: direction, wrap, grow/shrink, basis, justify, items, content, gap, grid cols/rows/flow.
4. Sizing: width/height, min/max width/height.
5. Spacing: margin, padding, space-x/space-y.
6. Border and radius: border width/style/color, divide, ring, rounded.
7. Colors and visual style: background, text color, fill/stroke, shadow, opacity.
8. Typography: font family, font size, font weight, line height, tracking, text align, text transform.
9. Overflow and scroll behavior: overflow, overscroll, scrollbar behavior.
10. Effects and motion: transition, duration, ease, animate, transform classes.

#### Variant Order

For every utility type, always apply classes in this order:

1. Base class (primary/default).
2. Responsive variants (`sm:`, `md:`, `lg:`, `xl:`, `2xl:`).
3. State and pseudo variants (`hover:`, `focus:`, `focus-visible:`, `active:`, `disabled:`, `aria-*`, `data-*`).

Keep state and pseudo classes grouped at the end of the class list.

#### Example

```tsx
className='relative flex w-full md:w-auto items-center gap-2 p-3 md:p-4 border border-border bg-background text-foreground text-sm font-medium overflow-hidden focus-visible:outline-none focus-visible:ring-2 hover:bg-accent disabled:opacity-50'
```

## Coding Standards

## TypeScript

- Use strict typing; do not use `any`.
- Prefer explicit interfaces/types for non-trivial props and responses.
- Keep types close to usage; move to shared types only when broadly reused.
- Use clear naming and avoid abbreviations that reduce readability.

## React

- Prefer functional components with typed props.
- Keep components small and focused on one concern.
- Extract repeated logic into hooks or shared helpers.
- Avoid deep prop drilling when composition or context is a better fit.
- Keep side effects controlled and predictable with clear dependencies.

## State and Data Flow

- Keep server state handling separated from presentation concerns.
- Use feature store slices for feature state and shared store only for global concerns.
- Keep data transforms in utilities/selectors instead of inline in JSX.
- Validate and sanitize external data at the boundary.

## Error Handling

- Fail gracefully with user-friendly fallback UI.
- Handle async errors explicitly and avoid silent failures.
- Surface actionable logs/messages for debugging.

## File and Naming Conventions

Use descriptive, predictable naming so files are easy to locate.

### React Naming Best Practices

- **Component files**: use `kebab-case` (example: `user-card.tsx`, `pipeline-task-details-sheet.tsx`).
- **Page files**: use `PascalCase` ending in `Page` (example: `WorkspacePage.tsx`, `AgentsPipelinePage.tsx`).
- **Layout files**: use `PascalCase` ending in `Layout` (example: `MainLayout.tsx`, `AuthFullPageLayout.tsx`).
- **Hook files**: use `camelCase` and start with `use` (example: `useSyncDashboardTheme.ts`).
- **Type files**: use `kebab-case` with descriptive suffixes when helpful (example: `workspace-types.ts`, `api-response-types.ts`).
- **Utility files**: use `kebab-case` (example: `format-date.ts`, `build-route-path.ts`).
- **Store files**: use `kebab-case` with intent-first naming (example: `workspace-store.ts`, `auth-slice.ts`).
- **Test files**: match source file name with `.test.ts` or `.test.tsx`.
- **Barrel files**: use `index.ts` only for curated exports.

### Symbol Naming Conventions

- **React components**: `PascalCase` (example: `UserCard`, `PipelineTaskDetailsSheet`).
- **Hooks**: `camelCase` with `use` prefix (example: `useWorkspaceProjects`).
- **Functions**: `camelCase` with verb-first naming (example: `formatWorkspaceLabel`).
- **Booleans**: `is/has/can/should` prefixes (example: `isLoading`, `hasError`).
- **Constants**: `UPPER_SNAKE_CASE` for true constants, otherwise `camelCase`.
- **Types and interfaces**: `PascalCase` (example: `Workspace`, `PipelineTask`).
- **Enums**: `PascalCase` enum name and `PascalCase` members.

### Additional Rules

- Keep one primary component per file when practical.
- Use consistent suffixes: `*Page`, `*Dialog`, `*Card`, `*Section`, `use*`.
- Keep import ordering clean and remove unused imports.

## Agent Execution Checklist

Before finishing any change, ensure:

- New code follows folder ownership and structure rules.
- Existing shared primitives were reused where possible.
- TypeScript typing is strict and readable.
- Components and hooks are small and focused.
- Error and loading states are handled.
- Unused code, imports, and dead paths are removed.
- Lint passes with zero new issues.