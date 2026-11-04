# RigExec Live Graph and Threads

This usdview plugin inspects the standing RigExec imaging evaluator. It does
not instantiate a rig, author a stage, evaluate a frame, or own a playback loop.
It requires a current usdRig build containing the live-debug imaging API,
OpenUSD's usdview/Qt environment, and the bundled UsdNoodles package.

Double-click `launch_usdview.bat` on Windows to open the biped in usdview with
**Live Graph and Threads** connected to its live evaluator. From a terminal:

```text
launch_usdview.bat
launch_usdview.bat "path\to\stage.usda"
```

On Linux/macOS, use `bash launch_usdview.sh [stage.usda]`. Both scripts default
to the sibling `../usdRig` checkout; set `RIG` to use another checkout. They
delegate dependency setup and build checks to usdRig's launcher. Additional
arguments after the stage are passed to usdview. `USD` and `PY` override its
dependencies; `RIGEXEC_VIZ_RIG` selects a specific rig prim path.

The Python entry point is also available from this directory:

```text
python -m rigexec_viz ../usdRig/examples/biped/Biped_stack.usda
```

Use `--repo PATH` for another usdRig checkout and `--rig /path/to/root` to select
a rig. Alternatively set `RIGEXEC_VIZ_ROOT` to this directory and launch through
usdRig's `bin/launch_usdview.bat` or `bin/usdview.sh`. The RigExec > General Editors
menu contains **Live Graph and Threads**. Set `RIGEXEC_VIZ_AUTOOPEN=1` to open it
on startup.

The graph is read directly from the active in-memory program. Search covers all
operations; the node canvas contains every operation and dependency in the
current compiled rig. **Frame all operations** shows the complete
scene. Zoom and pan to explore, or search by step number to frame a node without
removing the rest of the graph. Search lists the first 100 matching operations.
No graph USD file is created.
Vertex-chunk operations (`RevisionChunk`) and their compiled incoming and outgoing
dependencies are part of this full graph. **Vertex chunks** lists them and frames
the first one; selecting another result frames that chunk without hiding the
surrounding graph. Searching `vertex chunks` does the same lookup.

**Operation cost heatmap** colors timed nodes blue through red by operation-body
duration in the latest observed evaluation. The logarithmic scale runs from
zero to that evaluation's maximum, shown in microseconds beside the legend.
Untimed nodes keep their normal colors; a measured zero is blue. The colors
also cover dependency noodles: each uses its source operation's body cost,
updated only when both endpoints have timing samples in the same observed generation.
Each noodle retains that color through later empty or partial runs until a new
eligible measurement replaces it. Clear capture or graph replacement resets it.
Noodles do not have a separately measured duration. Heat colors persist between
evaluations, while amber execution outlines still fade. Toggle
**Execution flashes** off to inspect heat colors without the amber overlay.
**Show heaviest** lists the 100 longest operations; click one to frame it and
inspect its measured duration. Details identify the heat sample's generation
and frame separately from whether the operation ran in the latest followed
capture. Empty observations retain the earlier heat sample and its identity.
Body durations are elapsed intervals and can include thread preemption; they
are not CPU-time measurements or time spent waiting for dependencies.
**Follow live** pauses heatmap updates as well as
the trace display. Timing must be enabled to collect new samples. Heatmap costs
exclude dependency wait time and are not inclusive subtree or critical-path
costs. Clear capture or graph replacement clears the heatmap.
Heatmap geometry is cached in chunks; camera movement reuses it and local node
moves only invalidate affected node and incident-noodle chunks. Heat and glow
layers are cached as screen images between changes; fades composite the cached
glow instead of redrawing every operation and noodle. It reads the existing timing snapshots
without adding evaluator work, locks, or another evaluation loop.
Sparse execution updates visit outgoing dependencies of executed operations
instead of scanning every visible noodle. Cached overlay curves use adaptive
sampling within half a screen pixel, including backward bends; pan reuses them
and crossing a zoom detail level refreshes their geometry.

Pan/zoom reuses cached graph bounds and GPU geometry. At overview scales,
unreadable labels are omitted; every node and dependency remains rendered.
Labels return when zoomed in. Empty authoring-cell and relationship-arrow passes
are excluded from this operation-only viewer.
Passive hover uses the node spatial index for operation inspection. It does not
run USD property/port authoring tests or generate adaptive curve-picking segments
for dependency noodles. Ending a camera drag does not scan all node selections.
Selection uses a blue overlay instead of rebuilding all node geometry. Dragging
updates selected node transforms and incident dependency chunks; unrelated
noodles stay cached. Local layout moves support Ctrl+Z undo and Ctrl+Shift+Z or
Ctrl+Y redo and never author rig USD. This history belongs to the inspection
window and resets on graph replacement, independently of USD editor histories.
Ctrl-click and box selection select multiple operation nodes.

With **Follow live** enabled, executed nodes flash amber and fade over four
seconds. Dependency noodles flash when both endpoints ran in the same observed
generation. Highlights report completed operation runs; they do not imply that
the UI is repainting during individual microsecond-long operations. Repeated
polls of the same generation do not retrigger highlights. Pausing Follow live
stops new flashes. Flashes remain active with **Record operation timing** off;
that setting controls timing samples, not execution activity.
The complete scene is built once per graph replacement;
initial loading is more expensive than reading subsequent execution traces.

Open **Thread trace**, then manipulate controls or play/change usdview's frames.
The default **Timeline: all captured frames** view accumulates evaluations on
one monotonic time axis, preserving idle gaps between frames. The frame strip
labels stage frame time and evaluation generation; repeated evaluations at the
same frame remain separate. Hover an operation to see its frame and generation.
The dropdown can isolate one evaluation. **Clear capture** starts a new capture;
uncheck recording to stop collecting timings, or uncheck Follow live to hold
the displayed timeline while capture continues. Export includes the whole
displayed timeline and its frame intervals. Each exported event's duration is
the operation body; `memo_us` and `publish_us` ride in its args when present.
Each lane is an actual thread ID; bars are measured operation-body intervals.
When the host reports `trace_phases`, each bar also shows the operation's memo
(dim segment before the body) and its value publication (light segment after
it), so a bar spans the whole time the operation held its thread. A host
without them draws bodies only.
Hover a bar for its duration, click to frame its operation in the full graph, and use
the zoom slider and horizontal scrollbar to resolve short operations. Narrow
bars sharing a pixel are collapsed for drawing; zoom or export to inspect them.
The summary reports observed threads, peak interval overlap, body span, and
summed body work, plus the summed memo, body and publication time when phases
are present. These measure operation execution, not total frame latency.

Recording is enabled while the panel is open and can be unchecked. Closing the
panel disables it. Recording adds timestamps to existing per-operation storage;
it does not turn on the accumulating profiler or add operation-body locks.
The UI polls every 100 ms and retains up to 300 observed evaluations, evicting
oldest captures when the operation-event count exceeds one million (the latest
evaluation is always retained). The UI reports evictions. Polling may skip
intermediate evaluations. Cache hits produce no operation execution, and detached
frame-cache warming is excluded. Captured evaluator time and viewport time are
shown separately because they can differ. Graph replacement invalidates history.
Inspection and cached fade repaints continue every 100 ms while manipulating
controls, so completed observed runs flash before mouse release. Polling can
skip intermediate runs; the panel does not replay or infer those executions.
Uncheck **Follow live** to hold the displayed trace; use **Export Chrome trace**
for Chrome trace-event JSON. The host owns all evaluation and scheduling.

Run pure model tests with `python -m unittest discover -s tests`. The usdRig native
`testRigExecLiveDebug_serial` and `_parallel` tests verify the bridge, timestamps,
source-stage preservation, and that inspection does not trigger evaluation.

