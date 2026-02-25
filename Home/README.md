---
type: reference
lane: home
tags:
  - home
  - reference
---

# Home Lane

## Systems Index

```dataview
TABLE category, location, warranty_expires AS "Warranty"
FROM "Home"
WHERE type = "maintenance"
SORT category ASC
```

## Overdue / Urgent

```dataview
TABLE category, location
FROM "Home"
WHERE type = "maintenance" AND contains(tags, "urgent")
```

## The House
- **Year Built:**
- **Owned Since:**

## Seasonal Calendar
| Month | Task |
|-------|------|
| Jan | |
| Feb | |
| Mar | |
| Apr | |
| May | |
| Jun | |
| Jul | |
| Aug | |
| Sep | |
| Oct | |
| Nov | |
| Dec | |

## Open Items
- [ ]

## Vendors
| Name | Trade | Phone | Rating |
|------|-------|-------|--------|
| | | | |

