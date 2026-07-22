# Side Statistics Pair Buffering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure SHOGI side statistics are emitted for exactly the completed game pairs in each worker result batch.

**Architecture:** Store validated, one-game SHOGI side-statistics counters by game number beside the existing legacy result map. Move counters into the batch accumulator only when the corresponding odd/even pair completes, leaving unrelated unfinished games buffered for a later batch.

**Tech Stack:** Python 3.12, `unittest`, existing ShogiBench client modules.

## Global Constraints

- Do not change the server payload schema or weaken server validation.
- Preserve legacy and CHESS worker behavior.
- Preserve partial side-statistics coverage when a SHOGI line cannot be parsed.
- Do not modify or stage unrelated worktree files.

---

### Task 1: Buffer side statistics until pair completion

**Files:**
- Modify: `Client/test_worker_side_stats.py`
- Modify: `Client/worker.py:534-591`
- Modify: `Client/worker.py:1360-1417`

**Interfaces:**
- Consumes: `shogi_result.parse_finished_game(line) -> FinishedGame | None`
- Consumes: `shogi_result.add_finished_game(counters, finished_game)`
- Produces: `results["side_games"]`, mapping integer game IDs to one-game side-statistics dictionaries.

- [x] **Step 1: Write the failing out-of-order test**

Add a runner test whose output order is games 1, 3, 2, 4. Assert that two queue batches are emitted and each has `sum(trinomial) == side_stats_games == 2`.

- [x] **Step 2: Run the test to verify RED**

Run:

```powershell
& 'C:\Users\nodchip\AppData\Local\Programs\Python\Python312\python.exe' -m unittest Client.test_worker_side_stats.WorkerSideStatsTests.test_runner_batches_side_stats_by_completed_pair -v
```

Expected: FAIL because the first batch reports three side-statistics games.

- [x] **Step 3: Implement pair-scoped buffering**

Initialize `results["side_games"] = {}` for SHOGI. Convert each successfully parsed `FinishedGame` into a fresh one-game counter dictionary and store it by game number. Once `first` and `second` are both present in `results["games"]`, pop and add only those corresponding side records to the counters before the batch is queued. Do not clear unmatched `side_games` entries during batch reset.

- [x] **Step 4: Run the focused test to verify GREEN**

Run the command from Step 2. Expected: one collected test, PASS.

- [x] **Step 5: Add and verify duplicate-line coverage**

Add `test_duplicate_finished_game_does_not_duplicate_side_statistics` using order 1, 1, 2. Assert `sum(trinomial) == side_stats_games == 2`, then run the complete `Client.test_worker_side_stats` module.

- [x] **Step 6: Run project verification**

Run:

```powershell
& 'C:\Users\nodchip\AppData\Local\Programs\Python\Python312\python.exe' -m unittest Client.test_shogi_result Client.test_worker_side_stats -v
& 'C:\Users\nodchip\AppData\Local\Programs\Python\Python312\python.exe' manage.py test -v 1
git diff --check
git diff -- Client/worker.py Client/test_worker_side_stats.py docs/superpowers/specs/2026-07-22-side-statistics-pair-buffering-design.md docs/superpowers/plans/2026-07-22-side-statistics-pair-buffering.md
```

Expected: all tests pass, `git diff --check` emits no errors, and the diff contains only the intended changes.
