# Error Log

## [ERR-20260601-001] executor-image-stale-after-source-fix

**Logged**: 2026-06-01T18:05:00+08:00
**Priority**: medium
**Status**: pending
**Area**: infra

### Summary
Task executor containers kept using old PyInstaller binary after source-level git clone fixes, causing icode ugate token handling to remain stale.

### Details
In Wegent docker mode, task containers run /app/executor from the executor image. Editing shared/executor source and restarting backend/executor_manager is insufficient; rebuild the executor image and restart executor_manager so binary_extractor refreshes the named volume.

### Suggested Action
After executor/shared changes that affect task runtime, rebuild wegent-executor:dev and restart executor_manager before retrying tasks.

### Metadata
- Source: error
- Related Files: shared/utils/git_util.py, executor/agents/base.py, docker/executor/Dockerfile
- Tags: executor, pyinstaller, docker, icode

---

## [ERR-20260601-002] executor-pytest-coverage-db-corrupted

**Logged**: 2026-06-01T20:05:00+08:00
**Priority**: medium
**Status**: pending
**Area**: tests

### Summary
Relevant executor tests passed, but the default pytest run failed during coverage combination because the local `.coverage` SQLite database is corrupted.

### Error
```text
coverage.exceptions.DataError: Couldn't use data file '/Users/qiaofenglin/open_source/Wegent/executor/.coverage': no such table: other_db.file
```

### Context
- Command attempted: `cd executor && uv run pytest tests/agents/test_mode_strategy.py tests/agents/test_claude_code_config_security.py -q`
- The test body completed successfully (`12 passed`) before pytest-cov failed while merging coverage data.
- Running the same tests with `--no-cov` worked.

### Suggested Fix
Remove the broken `executor/.coverage` data file or clean stale parallel coverage fragments before rerunning coverage-enabled pytest.

### Metadata
- Reproducible: yes
- Related Files: executor/.coverage
- Tags: pytest, coverage, sqlite

---
