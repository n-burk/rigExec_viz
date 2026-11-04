"""Rendering policy for the complete, stageless operation graph."""
from UsdNoodles.graphView import GraphView, _guardsQtBoundary
from UsdNoodles.core import positionWriteGeneration, GraphModel
from UsdNoodles.widgets.minimap import Minimap
from pxr.Usdviewq.qt import QtCore, QGLFormat
from pxr import Gf


class CachedMinimap(Minimap):
    def __init__(self, view):
        super().__init__(view)
        self._bounds_key = None
        self.bounds_rebuilds = 0

    def _getGraphBounds(self):
        view = self._graphView
        key = (id(view.nodeGraph), len(view.nodes), positionWriteGeneration())
        if key != self._bounds_key:
            self._bounds = super()._getGraphBounds()
            self._bounds_key = key
            self.bounds_rebuilds += 1
        return self._bounds


class LiveGraphView(GraphView):
    inspectionSelectionChanged = QtCore.Signal()
    inspectionNodesMoved = QtCore.Signal(object)
    _LINK_CHUNK = 512
    def __init__(self, parent=None):
        # UsdNoodles selects GL 3.2 for its own canvas, but also changes Qt's
        # process-wide default. Auto-open can run before usdview creates its
        # viewport: keep that viewport's higher-capability format intact.
        host_format = QGLFormat.defaultFormat()
        try:
            super().__init__(parent=parent)
        finally:
            QGLFormat.setDefaultFormat(host_format)
        self.minimap = CachedMinimap(self)
        self._link_chunks = []
        self._incident_links = {}
        self._dirty_link_chunks = set()
        self._drag_origins = {}
        self._inspection_marquee_base = set()
        self._layout_undo = []
        self._layout_redo = []
        self.nodeGraphReplaced.connect(self._clear_layout_history)

    def _clear_layout_history(self):
        self._layout_undo.clear()
        self._layout_redo.clear()
        self._drag_origins.clear()
        self._inspection_marquee_base.clear()
        self.draggingNodes = self.marqueeActive = False

    def _performUndo(self):
        if self._layout_undo:
            initial, final = self._layout_undo[-1]
            self._move_to_positions(initial)
            self._layout_redo.append(self._layout_undo.pop())

    def _performRedo(self):
        if self._layout_redo:
            initial, final = self._layout_redo[-1]
            self._move_to_positions(final)
            self._layout_undo.append(self._layout_redo.pop())

    def clearSelection(self):
        for node_id in self._selectedNodes:
            node = self.nodes.get(node_id)
            if node is not None:
                node.selected = False
        self._selectedNodes.clear()
        self.inspectionSelectionChanged.emit()
        self.update()

    @_guardsQtBoundary
    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self.spacePressed:
            return super().mousePressEvent(event)
        self.setFocus()
        position = event.position().toPoint()
        self.lastMousePos = self.mousePosOnMouseDown = position
        if self._cachedShowMinimap and self.minimap.handleMousePress(position):
            return
        self._updateNodeUnderCursor(position)
        node = self.nodes.get(self.nodeIdUnderCursor)
        control = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier)
        if node is None:
            if not control:
                self.clearSelection()
            self._inspection_marquee_base = set(self._selectedNodes)
            self.marqueeStart = QtCore.QPointF(position.x()/self.zoom+self.panX,
                                             position.y()/self.zoom+self.panY)
            self.marqueeCurrent = self.marqueeStart
            self.marqueeActive = True
            event.accept()
            return
        if not control and node.id not in self._selectedNodes:
            self.clearSelection()
        if control and node.id in self._selectedNodes:
            node.selected = False
            self._selectedNodes.remove(node.id)
        else:
            node.selected = True
            self._selectedNodes.add(node.id)
        self.draggingNodes = node.id in self._selectedNodes
        self._drag_origins = ({i: tuple(self.nodes[i].position) for i in self._selectedNodes}
                              if self.draggingNodes else {})
        for i in self._drag_origins:
            self.nodes[i].beginDrag()
        self.inspectionSelectionChanged.emit()
        self.update()
        event.accept()

    def _update_inspection_marquee(self, point):
        self.marqueeCurrent = QtCore.QPointF(point.x()/self.zoom+self.panX,
                                           point.y()/self.zoom+self.panY)
        start, end = self.marqueeStart, self.marqueeCurrent
        bounds = Gf.Range2d(Gf.Vec2d(min(start.x(), end.x()), min(start.y(), end.y())),
                            Gf.Vec2d(max(start.x(), end.x()), max(start.y(), end.y())))
        candidates, _ = self._spatialIndex.queryRegion(bounds)
        selected = set(self._inspection_marquee_base)
        for node_id in candidates:
            node = self.nodes.get(node_id)
            if node and bounds.Contains(node.position) and bounds.Contains(node.position+node.size):
                selected.add(node_id)
        for node_id in self._selectedNodes-selected:
            self.nodes[node_id].selected = False
        for node_id in selected-self._selectedNodes:
            self.nodes[node_id].selected = True
        self._selectedNodes = selected
        self.inspectionSelectionChanged.emit()
        self.update()

    def _move_to_positions(self, positions):
        for node_id, position in positions.items():
            node = self.nodes.get(node_id)
            if node is None:
                continue
            delta = Gf.Vec2d(*position)-node.position
            node.position = Gf.Vec2d(*position)
            self._nodeTransformFrame.translate(node_id, delta[0], delta[1])
        moved = set(positions) & self.nodes.keys()
        self._updateNodeSpatialBounds(moved)
        self._updateLinksForMovedNodes(moved)
        for node_id in moved:
            node = self.nodes[node_id]
            self._reconciledPositionVersions[node_id] = node.positionVersion
            if self.minimap._bounds_key is not None:
                self.minimap._bounds = Gf.Range2d.GetUnion(self.minimap._bounds,
                    Gf.Range2d(node.position, node.position+node.size))
        self._reconcilePositionGen = positionWriteGeneration()
        if self.minimap._bounds_key is not None:
            self.minimap._bounds_key = (id(self.nodeGraph), len(self.nodes), positionWriteGeneration())
        self.inspectionNodesMoved.emit(moved)
        self.inspectionSelectionChanged.emit()
        self.update()

    @_guardsQtBoundary
    def mouseMoveEvent(self, event):
        if self.marqueeActive and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._update_inspection_marquee(event.position().toPoint())
            event.accept()
            return
        if self.draggingNodes and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            delta = Gf.Vec2d(point.x()-self.lastMousePos.x(), point.y()-self.lastMousePos.y())/self.zoom
            self._move_to_positions({i: tuple(self.nodes[i].position+delta) for i in self._selectedNodes})
            self.lastMousePos = point
            event.accept()
            return
        if (event.buttons() == QtCore.Qt.MouseButton.NoButton
                and not self.draggingNodes and not self._draggingLink
                and not self.marqueeActive and not self.nodeCreationHotbox.is_visible):
            # Inspect operation nodes through the existing spatial index. USD
            # property/port authoring and adaptive noodle picking do not belong
            # in passive hover for this stageless inspection view.
            position = event.position().toPoint()
            previous = self.nodeIdUnderCursor
            self._updateNodeUnderCursor(position)
            if self._cachedShowMinimap:
                self.minimap.updateHoverState(position)
            self.lastMousePos = position
            if self.nodeIdUnderCursor != previous:
                node = self.nodes.get(self.nodeIdUnderCursor)
                self.setToolTip(node.name if node else '')
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    @_guardsQtBoundary
    def mouseReleaseEvent(self, event):
        if self.marqueeActive and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._update_inspection_marquee(event.position().toPoint())
            self.marqueeActive = False
            self._inspection_marquee_base.clear()
            event.accept()
            self.update()
            return
        if self.draggingNodes and event.button() == QtCore.Qt.MouseButton.LeftButton:
            final = {i: tuple(self.nodes[i].position) for i in self._selectedNodes}
            for i in self._selectedNodes:
                self.nodes[i].endDrag()
            self.draggingNodes = False
            initial = self._drag_origins
            self._drag_origins = {}
            if initial != final:
                # Layout belongs to this inspection graph, not a USD stage history.
                self._layout_undo.append((initial, final))
                del self._layout_undo[:-100]
                self._layout_redo.clear()
            self.inspectionSelectionChanged.emit()
            self.update()
            event.accept()
            return
        camera_release = (event.button() == QtCore.Qt.MouseButton.MiddleButton
                          or (self.spacePressed and event.button() == QtCore.Qt.MouseButton.LeftButton))
        if camera_release and not (self.draggingNodes or self._draggingLink or self.marqueeActive):
            self.minimap.handleMouseRelease()
            self.lastMousePos = event.position().toPoint()
            event.accept()
            self.update()
            return
        super().mouseReleaseEvent(event)

    def _zoomAroundPoint(self, newZoom, focusPoint):
        bounds = self.minimap.getGraphBounds()
        minimum = 1e-8
        if not bounds.IsEmpty():
            size = bounds.GetSize()
            if size[0] > 0 and size[1] > 0:
                minimum = max(minimum, min(self.width()/size[0], self.height()/size[1])*0.1)
        zoom = max(minimum, min(float(newZoom), 10.0))
        delta = 1.0/self.zoom - 1.0/zoom
        self.panX += focusPoint[0]*delta
        self.panY += focusPoint[1]*delta
        self.zoom = zoom

    def _paintValueCells(self):
        # Operation nodes have no authored USD value cells.
        pass

    def _renderRelationshipArrowheads(self, *args, **kwargs):
        # Every edge in this view is an operation dependency, not a USD rel.
        pass

    def paintText(self):
        # Keep every node/edge drawn, but omit unreadable subpixel labels/icons.
        if not self.nodes or not self.shaderLibrary or not self.fontAtlas:
            return
        # Complete a content rebuild even at overview scale, so node geometry
        # does not stay dirty and rebuild on each camera movement.
        if self.textChanged or self.zoom >= 0.04:
            if self._render_without_selection(lambda: self.textRenderer.renderNodeText(self.nodeGraph,
                    self._worldSpaceProjectionMatrix(), self.zoom, self.textChanged,
                    self.panX, self.panY, float(self.width()), float(self.height()), True)):
                self.textChanged = False

    def _render_without_selection(self, render):
        # Keep selection out of cached native geometry/text even when a later
        # content rebuild occurs; the small overlay owns its appearance.
        nodes = [self.nodes[i] for i in self._selectedNodes if i in self.nodes]
        for node in nodes:
            node.selected = False
        try:
            return render()
        finally:
            for node in nodes:
                node.selected = True

    def paintNodes(self):
        # Selection is a small overlay, not a rebuild of all node quads.
        self._lastNodeQuadSelection = frozenset(self._selectedNodes)
        if self.textChanged:
            self.minimap._bounds_key = None
        self._render_without_selection(super().paintNodes)

    def _renderPortHighlightsCpp(self):
        # This inspection graph has no editable ports. Avoid rebuilding the
        # authoring-port decoration buffer for every dragged node position.
        pass

    def _rebuildLinks(self):
        super()._rebuildLinks()
        self._link_chunks = []
        self._incident_links = {}
        for index, link in enumerate(self.links):
            self._incident_links.setdefault(link.sourceNodeId, set()).add(index)
            self._incident_links.setdefault(link.targetNodeId, set()).add(index)
        for first in range(0, len(self.links), self._LINK_CHUNK):
            graph = GraphModel()
            graph.syncLinksFromModels(self.links[first:first+self._LINK_CHUNK])
            self._link_chunks.append(graph)
        self._dirty_link_chunks.clear()

    def _updateLinksForMovedNodes(self, moved):
        indices = set()
        for node_id in moved:
            indices.update(self._incident_links.get(node_id, ()))
        for index in indices:
            link = self.links[index]
            self._setupLinkEndpoints(link, self.nodes[link.sourceNodeId],
                self.nodes[link.targetNodeId], link.sourcePort, link.targetPort)
            self._spatialIndex.insertLink(index, self._computeLinkBounds(link))
            self._dirty_link_chunks.add(index//self._LINK_CHUNK)

    def paintLinks(self):
        if not self.linkRenderer:
            return
        for chunk in self._dirty_link_chunks:
            first = chunk*self._LINK_CHUNK
            self._link_chunks[chunk].syncLinksFromModels(self.links[first:first+self._LINK_CHUNK])
        self._dirty_link_chunks.clear()
        projection = self._worldSpaceProjectionMatrix()
        config = self._renderConfig()
        for index, graph in enumerate(self._link_chunks):
            self.linkRenderer.renderLinksFromGraph(graph, projection, self.zoom,
                self.panX, self.panY, self.width(), self.height(), config,
                relationshipOnly=False, dimming=1.0, drawSelected=False,
                baseColor=list(self._cachedLinkAttributeBaseColor[:3]), cacheKey=1000+index)

    def _resetRenderCachesAfterBulkMove(self, *args, **kwargs):
        if hasattr(self, 'minimap') and isinstance(self.minimap, CachedMinimap):
            self.minimap._bounds_key = None
        return super()._resetRenderCachesAfterBulkMove(*args, **kwargs)
