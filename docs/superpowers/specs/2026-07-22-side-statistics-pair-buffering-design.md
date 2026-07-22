# Side Statistics Pair Buffering Design

## Problem

Shogitest may finish games out of pair order when a runner uses concurrency greater than one. The worker currently counts every parsed `Finished game` line in side statistics immediately, while trinomial and pentanomial results are emitted only after both games in a numbered pair have finished. A report can therefore contain more side-statistics games than batch games and is rejected by the server.

## Design

Keep the server protocol and validation unchanged. For SHOGI runners, normalize each parsed `FinishedGame` into one game's validated side-statistics counters and retain those counters in a `side_games` dictionary keyed by game number. When the matching odd/even pair is complete, add side statistics for those two games to the current batch and remove those entries from `side_games`. Unmatched entries remain buffered across batch emission.

The existing `games` dictionary remains unchanged and continues to drive trinomial and pentanomial calculation. This limits the production change to the client and preserves CHESS behavior.

## Error Handling

If a SHOGI completion line cannot be parsed, or does not contain Dev and Base exactly once, the legacy result remains available for normal pair accounting. Side-statistics coverage may be lower than the batch game count, which the server already accepts as partial coverage.

Keying pending side data by game number also makes repeated completion lines idempotent for side statistics, matching the overwrite behavior of the existing `games` dictionary.

## Verification

- Reproduce out-of-order completion with `1, 3, 2, 4` and assert that both emitted batches contain two normal games and two side-statistics games.
- Reproduce duplicate completion with `1, 1, 2` and assert that side statistics count two games.
- Preserve the existing parse-failure, aggregation, and non-SHOGI tests.
- Run the focused client tests and the complete project test suite.
