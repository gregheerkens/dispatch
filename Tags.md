---
type: reference
tags:
  - reference
---

# Dispatch Tag Taxonomy

Use these tags consistently. Obsidian's tag pane and Dataview queries both depend on it.

---

## Lane Tags
| Tag | Use On |
|-----|--------|
| `#jobs` | Anything job search related |
| `#build` | Projects, apps, makerspace |
| `#learn` | Courses, skills, reading |
| `#home` | Maintenance, farm, property |
| `#write` | Drafts, ideas, published work |
| `#self` | Health, habits, reflection |

## Type Tags
| Tag | Use On |
|-----|--------|
| `#standup` | Standup minute notes |
| `#daily` | Daily notes |
| `#weekly-review` | Weekly review notes |
| `#application` | Job application notes |
| `#contact` | Contact/person notes |
| `#project` | Project notes |
| `#maintenance` | Home maintenance item notes |
| `#draft` | Writing drafts |
| `#reference` | Reference/static notes |

## Status Tags
| Tag | Use On |
|-----|--------|
| `#active` | Currently in progress |
| `#blocked` | Waiting on something |
| `#done` | Completed |
| `#dead` | Abandoned or closed |
| `#idea` | Not started, speculative |

## Priority Tags
| Tag | Use On |
|-----|--------|
| `#urgent` | Needs action today |
| `#this-week` | Needs action this week |
| `#someday` | No timeline |

---

## Dataview Cheat Sheet

```dataview
TABLE company, role, date_applied, status
FROM #application
WHERE status != "dead"
SORT date_applied DESC
```

```dataview
TABLE status, started
FROM #project
WHERE status = "active"
```

```dataview
TABLE date, file.link AS "Note"
FROM #standup
SORT date DESC
LIMIT 10
```
