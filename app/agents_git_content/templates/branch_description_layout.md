## Brief
- Original request: <source request from Jira ticket or SPEC bundle>

## Changes
- <implementation change 1>
- <implementation change 2>

## Component Dependencies Diagram
```mermaid
flowchart LR
  A["Primary page/feature"] --> B["Component A"]
  A --> C["Component B"]
  C --> D["Shared Utility"]
```

## Workflow Diagram
```mermaid
flowchart LR
  A["User action"] --> B["Page/feature entry"]
  B --> C["Main workflow step"]
  C --> D["Persistence/API side effect"]
  D --> E["Visible outcome"]
```

## Test Report
- Coverage (high level): <known coverage summary or "Not available in this run">.
- Tests passed count: <known count or "Not available in this run">.

## Risks and Follow-ups
- <risk, limitation, or follow-up item>
