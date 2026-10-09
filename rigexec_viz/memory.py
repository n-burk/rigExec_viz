"""In-memory noodles graph: live ops straight into NodeModels.

No USD is authored. Each operation becomes a bare ``NodeModel`` (the
same construction the Blueprint loader uses for its virtual nodes),
each dependency a ``LinkData`` cached on its target node, and the
populated ``NodeGraph`` is handed to the view, whose link rebuild
collects the cached links. The graph reads the session's structures
and nothing else: there is no stage to keep in sync and no prim
namespace to collide with.
"""

from __future__ import annotations

#: Domain -> title-bar color (linear RGB). Pose-domain ops in blues,
#: geometry in greens, property chains in amber, exec taps in slate,
#: values in gray.
DOMAIN_COLORS = {
    "batch": (0.23, 0.49, 0.65),
    "solver": (0.29, 0.56, 0.76),
    "constraint": (0.18, 0.49, 0.43),
    "chain": (0.35, 0.62, 0.29),
    "revision": (0.25, 0.48, 0.21),
    "propchain": (0.73, 0.54, 0.18),
    "proprev": (0.60, 0.44, 0.15),
    "tap": (0.42, 0.47, 0.55),
    "provider": (0.45, 0.45, 0.48),
    "switch": (0.55, 0.55, 0.30),
    "interp": (0.65, 0.38, 0.25),
    "skipped": (0.45, 0.30, 0.30),
    "step": (0.29, 0.56, 0.76),
}
_DEFAULT_COLOR = (0.45, 0.45, 0.48)

#: Baked step kind -> title-bar color: the pose walk in blues, weight
#: assembly in amber, geometry in greens.
STEP_KIND_COLORS = {
    "ComposeSubtree": (0.18, 0.49, 0.43),
    "Solve": (0.23, 0.49, 0.65),
    "SolverCommit": (0.26, 0.55, 0.72),
    "Constraint": (0.29, 0.56, 0.76),
    "CommitDelta": (0.29, 0.56, 0.76),
    "PropagateChunk": (0.29, 0.56, 0.76),
    "CommitApply": (0.26, 0.55, 0.72),
    "ProviderMatrix": (0.18, 0.49, 0.43),
    "SnapshotFinals": (0.42, 0.55, 0.68),
    "PoseInterpolator": (0.48, 0.61, 0.78),
    "VolumePlacements": (0.73, 0.54, 0.18),
    "WeightPacket": (0.73, 0.54, 0.18),
    "InfluenceFold": (0.35, 0.62, 0.29),
    "RevisionStatic": (0.29, 0.54, 0.25),
    "RevisionChunk": (0.25, 0.48, 0.21),
    "RevisionFuse": (0.44, 0.68, 0.37),
    "ChainStatus": (0.53, 0.71, 0.42),
    "Derived": (0.61, 0.76, 0.51),
}


def domain_color(domain, kind=""):
    if domain == "step" and kind in STEP_KIND_COLORS:
        return STEP_KIND_COLORS[kind]
    return DOMAIN_COLORS.get(domain, _DEFAULT_COLOR)


def _last(path, count=1):
    parts = [p for p in str(path).split("/") if p]
    return "/".join(parts[-count:]) if parts else str(path)


def compact_title(node):
    """A title short enough to read at graph scale; details live in the panel."""
    domain = node.get("domain", "")
    label = node.get("label", "")
    if domain == "batch":
        return "batch %s" % node.get("id", "").split(":")[-1]
    if domain == "tap":
        return "tap %s" % node.get("id", "")[4:]
    if domain == "revision":
        mover = node.get("details", {}).get("mover", "")
        return "%s@%s" % (_last(mover), node.get("order", 0))
    if domain == "proprev":
        return "%s@%s" % (_last(label), node.get("order", 0))
    if domain == "chain":
        return _last(label, 2) if "." in _last(label) else _last(label)
    if domain == "step":
        return "s%s %s" % (node.get("id", "").split(":")[-1],
                           node.get("kind", ""))
    return _last(label)


def build_memory_graph(view, nodes, edges, positions):
    """Populate ``view`` with a stageless graph; returns the ``NodeGraph``.

    ``nodes`` are session op dicts, ``edges`` ``(src, dst)`` op-id pairs,
    ``positions`` maps op id -> ``(x, y)`` world units. Unknown endpoints
    are skipped, so a partial structure still graphs.
    """
    from pxr import Gf

    from UsdNoodles.core import LinkData
    from UsdNoodles.models import NodeModel
    from UsdNoodles.nodeGraph import NodeGraph

    graph = NodeGraph()
    by_id = {n["id"]: n for n in nodes}
    has_in = set()
    has_out = set()
    for src, dst in edges:
        if src in by_id and dst in by_id:
            has_out.add(src)
            has_in.add(dst)

    for op in nodes:
        node = NodeModel()
        node.id = op["id"]
        node.name = compact_title(op)
        node.type = op.get("domain", "")
        x, y = positions.get(op["id"], (0.0, 0.0))
        node.position = Gf.Vec2d(float(x), float(y))
        if op["id"] in has_in:
            node.inputPins = ["in"]
            node.inputPinTypes = {"in": "token"}
        if op["id"] in has_out:
            node.outputPins = ["out"]
            node.outputPinTypes = {"out": "token"}
        color = domain_color(op.get("domain", ""), op.get("kind", ""))
        node.displayColorR, node.displayColorG, node.displayColorB = color
        node._display_color = color
        graph.nodes[node.id] = node

    for op in nodes:
        node = graph.nodes[op["id"]]
        graph._calculateNodeSize(
            node, view.textRenderer.calculateTextWidth, view.fontAtlas)

    for src, dst in edges:
        if src not in by_id or dst not in by_id:
            continue
        link = LinkData()
        link.sourceNodeId = src
        link.sourcePort = "out"
        link.targetNodeId = dst
        link.targetPort = "in"
        graph.nodes[dst].inputLinks.append(link)

    graph.linksChanged = True
    if hasattr(graph, "syncSelectionToPrimTree"):
        graph.syncSelectionToPrimTree = False
    view.nodeGraph = graph
    view.linksChanged = True
    return graph
