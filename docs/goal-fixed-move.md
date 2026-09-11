# Goal fixed-move screening

The closed `goal-fixed-move-2t-v1` profile compares two source revisions with
the same registered network. Both sides use two threads, 128 MiB Hash and
CSARule24. Acceptance plays two games; the following STC uses the existing
0/+4 Elo SPRT with a 131,072-game ceiling. This is a screening profile, not
a promotion or LTC contract.

`MT=1000` means 1,000 milliseconds per move. The worker still benchmarks both
engines and reports their speed, but this profile always uses scale factor
1.0. It sends `st=1000 timemargin=250` to the pinned shogitest runner, whose
`st` parser takes integer milliseconds. The runner expresses this through
USI as zero main time and 1,000 ms byoyomi. The 250 ms runner grace is not
extra engine thinking time. Other increment clocks retain their existing
speed scaling. Generic Shogi fixed-move clocks now also use integer
milliseconds; chess fixed-move clocks retain their seconds format.

Creation, GET read-back and workload construction check the common network,
clock, options, game budget, rule profile and stage. Only the configured
autotune owner receives the fixed timing marker. A changed fixed-clock Goal
workload is rejected before it can fall back to ordinary speed scaling.

Migration `0006_result_illegal_moves` adds an integer counter to Result.
Worker result uploads commit these counters together with the test's game
and terminal state. Fixed-profile uploads reject negative or excessive error
counts and mismatched result ownership. GET returns crash, time-loss and
illegal-move counts only for this new profile: historical zero defaults do
not establish that old tests had no illegal moves.

Deploy the exact reviewed source through the operator's fixed maintenance
adapter while server and worker are quiescent, with a protected database
backup and this additive migration applied before restart. Source push does
not authorize deployment or migration. If code is rolled back, preserve the
database and its added column; do not reverse-migrate away collected data.
An exact runtime audit and a new successful bounded qualification are
required before any production test. Unit tests alone do not prove the
deployed engine's timing behavior.
