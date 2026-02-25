---
type: reference
lane: build
tags:
  - build
  - reference
---

# Build Lane

## Active Projects

```dataview
TABLE stack, started, status
FROM "Build"
WHERE type = "project" AND status = "active"
SORT started DESC
```

## All Projects

```dataview
TABLE stack, started, status
FROM "Build"
WHERE type = "project"
SORT started DESC
```

## Makerspace
- **Equipment:** CNC, 3D Printer
- **Current Materials:**
- **Upcoming Build Ideas:**

## Ideas Inbox
> Raw captures. Don't filter here.


## Shipped
> Things done and out in the world.


