# Working on the live visualizer

The host usdview imaging session owns evaluation. Read its standing operation
graph and last-run trace on the stage owner thread. Never create another Rig,
open a private stage for evaluation, or add a playback/evaluation loop here.
Graph layout and timeline painting consume immutable inspection snapshots.

Preserve the unified dependency compiler, scheduler, and kernels. Operation
bodies, numerical kernels, and frozen arenas are no-mutex zones: no new mutexes,
lock-taking instrumentation, shared event appenders, or stage access. Timing
uses existing per-operation stamps and post-run inspection at the host boundary.

Load the complete operation graph; do not truncate it to a neighborhood. Bound
per-frame work with view culling, cached geometry, and idle repaint suppression.
Execution highlights come from observed traces, never inferred evaluation.
Highlight dependency noodles only when both endpoints ran in the same observed
generation. Search must cover the full graph. Invalidate
trace history on stage/graph replacement. Report actual thread IDs and measured
intervals without inferring parallelism from operation sequence numbers. Do not
claim cache hits or detached warming are live operation runs.

Run the pure model tests and the testusdview integration script after changes.
Keep one-off logs, captures, and investigation scripts outside this directory.
