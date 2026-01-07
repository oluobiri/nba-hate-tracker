---
name: Feature
about: New functionality or capability
title: 'feat(scope): '
labels: feature
---

**Effort:** _[30 min / 1-2 hrs / 2-3 hrs / 3-4 hrs]_  
**Risk:** _[Low / Medium / High]_  
**Phase:** _[1 / 2 / 3 / 4 / 5 / 6]_

---

## Description

_What capability is being added? What problem does it solve?_

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

---

## Proposed Interface

_For new modules/classes, sketch the public API._

```python
# path/to/module.py
class NewClass:
    def method(self, param: str) -> dict:
        """What it does."""
        ...
```

---

## Testing

_What tests validate the feature?_

```python
# tests/unit/test_module.py
def test_feature_happy_path():
    ...

def test_feature_edge_case():
    ...
```

---

## Out of Scope

- _What explicitly won't be done in this PR?_

---

## Dependencies

- [ ] _PR #X must be merged first_
- [ ] _Data file must exist: `data/raw/file.jsonl`_

---

## Notes

_Optional: expected output, sample data, verification steps._