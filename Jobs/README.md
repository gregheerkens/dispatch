---
type: reference
lane: jobs
tags:
  - jobs
  - reference
---

# Jobs Lane

## Active Search
- **Target Roles:** Dev, Sr Dev, PM, TPMM, DevRel
- **Pay Floor:** (fill in)
- **Remote OK:** Yes / Hybrid / No

## Pipeline

```dataview
TABLE company, role, date_applied, status, follow_up AS "Follow Up"
FROM "Jobs"
WHERE type = "application" AND status != "dead"
SORT date_applied DESC
```

## Contacts

```dataview
TABLE company, title, warmth, last_contact, next_followup AS "Next Follow-up"
FROM "Jobs"
WHERE type = "contact"
SORT last_contact DESC
```

## All Applications (including closed)

```dataview
TABLE company, role, date_applied, status
FROM "Jobs"
WHERE type = "application"
SORT date_applied DESC
```

## Market Notes
> Running observations — patterns in listings, what's responding, what's going dark.


## Job Fairs / Events
| Date | Event | Location | Notes |
|------|-------|----------|-------|
| 2026-02-26 | Job Fair — **afternoon** | TBD | Prep: research 3-5 companies, write 30-sec pitch |

