---
paths:
  - "tests/**/*.py"
---

# Tests

- Unit tests run against real `bd`, git and `wt` in a temp repo: no mocks, no model. `python3 -m pytest tests` must never call a model, so every e2e module is skipped unless `SDLC_E2E=1`.
- A new script under `scripts/` comes with `tests/test_<script>.py`. A new skill comes with `tests/e2e/skills/test_skill_<name>.py`.
- e2e sessions are driven through `claude -p` with stream-json in and out; `interactive=False` leaves out the permission-prompt tool and exercises the skill's headless branch.
