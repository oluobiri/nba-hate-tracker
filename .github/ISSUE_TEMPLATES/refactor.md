---
name: Refactor
about: Code restructuring without behavior changes
title: 'refactor(scope): '
labels: refactor, tech-debt
---

**Effort:** _[30 min / 1-2 hrs / 2-3 hrs / 3-4 hrs]_  
**Risk:** _[Low / Medium / High]_

---

## Description

_What code smell or structural problem exists? Why refactor now?_

---

## Acceptance Criteria

- [ ] _Criterion 1_
- [ ] _Criterion 2_
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check .` passes

---

## Deliverables

| Action | File |
|--------|------|
| Create | `path/to/new_file.py` |
| Modify | `path/to/existing_file.py` |
| Delete | `path/to/deprecated_file.py` |

---

## Testing

_What tests validate the refactor? Include parametrized test examples if applicable._

```python
# tests/unit/test_module.py
def test_example():
    ...
```

---

## Out of Scope

- _What explicitly won't be done in this PR?_
- _Feature additions, behavior changes, etc._

---

## Notes

_Optional: verification steps, dependencies on other PRs, risks to watch for._