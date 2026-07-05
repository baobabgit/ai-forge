---
id: BL-fix-002
type: BL
parent: FEAT-fix-001
library: ai-forge
target_version: 0.1.0
depends_on:
- BL-fix-001
size: M
status: READY
gates:
  auto:
  - pytest -x
  ai_judged:
  - criterion
scope:
- src/core/specparser.py
---

# BL fixture 002

Second backlog item.