"""Layered layout for the operation graph: pure data in, positions out.

Columns come from the edges, not the engine's levels: each node lands
one column past its deepest predecessor, so every edge flows left to
right in both modes. Within a column nodes order by the barycenter of
their predecessors' rows (two sweeps), which pulls each node toward
the nodes it reads and keeps the noodles short; ties break on the
walk order, then the id.

Positions are in noodles world units. A node measures roughly 1400 x
600 with one pin row per side, so the default pitches leave breathing
room without a measure pass.
"""

from __future__ import annotations

PITCH_X = 2400.0
PITCH_Y = 900.0


def layout_nodes(node_ids, edges, order_of=None, pitch_x=PITCH_X,
                 pitch_y=PITCH_Y, wrap=12):
    """Map op id -> ``(x, y)`` world position.

    ``edges`` are ``(src, dst)`` pairs; endpoints the input does not
    name are ignored rather than an error. ``order_of`` optionally maps
    id -> walk order for tie-breaking. A dependency cycle (which a
    compiled epoch never holds) degrades to column zero for the nodes
    the cycle traps instead of failing. Columns taller than ``wrap``
    rows fold into side-by-side sub-columns, so a wide source layer
    (every exec tap) cannot compress the op flow into a sliver.
    """
    node_ids = list(node_ids)
    if not node_ids:
        return {}
    known = set(node_ids)
    preds = {i: [] for i in node_ids}
    for src, dst in edges:
        if src in known and dst in known and src != dst:
            preds[dst].append(src)

    # Iterative topological depth supports long production dependency chains.
    from collections import deque
    outgoing = {i: [] for i in node_ids}
    remaining = {i: len(preds[i]) for i in node_ids}
    for target, sources in preds.items():
        for source in sources:
            outgoing[source].append(target)
    depth = dict.fromkeys(node_ids, 0)
    ready = deque(i for i in node_ids if not remaining[i])
    while ready:
        source = ready.popleft()
        for target in outgoing[source]:
            depth[target] = max(depth[target], depth[source]+1)
            remaining[target] -= 1
            if not remaining[target]:
                ready.append(target)

    columns = {}
    for node_id in node_ids:
        columns.setdefault(depth[node_id], []).append(node_id)
    ordered_columns = [columns[k] for k in sorted(columns)]

    order_of = order_of or {}
    succs = {i: [] for i in node_ids}
    for src, dst in edges:
        if src in known and dst in known and src != dst:
            succs[src].append(dst)
    row_of = {}
    for column in ordered_columns:
        for row, node_id in enumerate(
                sorted(column, key=lambda i: (order_of.get(i, 0), i))):
            row_of[node_id] = row

    def _sweep(backward):
        columns = ordered_columns if backward else reversed(ordered_columns)
        for column in columns:
            def _key(node_id, _row_of=row_of):
                neighbors = preds[node_id] if backward else succs[node_id]
                named = [p for p in neighbors if p in _row_of]
                if not named:
                    return (1, _row_of[node_id], order_of.get(node_id, 0),
                            node_id)
                mean = sum(_row_of[p] for p in named) / len(named)
                return (0, mean, order_of.get(node_id, 0), node_id)

            column.sort(key=_key)
            for row, node_id in enumerate(column):
                row_of[node_id] = row

    # Alternate backward/forward so sources settle under their consumers
    # as well as consumers under their sources.
    for _ in range(3):
        _sweep(True)
        _sweep(False)

    positions = {}
    col = 0
    for column in ordered_columns:
        chunks = [column[i:i + wrap] for i in range(0, len(column), wrap)]
        for chunk in chunks:
            for row, node_id in enumerate(chunk):
                positions[node_id] = (col * pitch_x, row * pitch_y)
            col += 1
    return positions
