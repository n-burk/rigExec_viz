"""Fire glow overlay: a transparent widget over the noodles view.

Noodles renders nodes and links in GL with global highlight colors, so
per-node analog fading lives one layer up: this widget tracks the view's
geometry and repaints an amber outline (plus the fired node's outgoing
noodles) whose alpha follows the ``ActivityModel``. It never takes mouse
events -- pan, zoom, drag and selection all fall through to the view --
and it repaints from the view's live pan/zoom, so the glow stays glued
to its node while the camera moves.
"""

from __future__ import annotations

import time
import math

from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets

from .activity import ActivityModel
from .heatmap import COLORS, color_bucket, operation_costs, dependency_bucket

_GLOW = (255, 196, 64)


class GlowOverlay(QtWidgets.QWidget):
    """Transparent fire-glow layer parented over a noodles ``GraphView``."""

    def __init__(self, view, parent=None):
        super().__init__(parent or view.parentWidget())
        self._view = view
        self._activity = ActivityModel()
        self._links_of_source = {}
        self._indexed_links = None
        self._had_live = False
        self._run = 0
        self._run_of = {}
        self._last_camera = None
        self._curve_paths = {}
        self.painted_nodes = self.painted_links = 0
        self.heat_enabled = True
        self.activity_enabled = True
        self.costs = {}
        self.heat_maximum = 0
        self._heat_chunks = []
        self._heat_chunk_of = {}
        self._heat_dirty = set()
        self._heat_paths = {}
        self._heat_link_paths = {}
        self._heat_link_buckets = {}
        self._heat_image = None
        self._glow_image = None
        self._glow_expiry = 0
        self._glow_time = 0
        self.painted_heat_links = 0
        self.heat_rebuilds = 0
        view.inspectionNodesMoved.connect(self._invalidate_moved_heat)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        view.installEventFilter(self)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(100)

    # -- activity --------------------------------------------------------

    def set_heat(self, events, clear=False):
        costs = operation_costs(events)
        if clear:
            self._heat_link_buckets.clear()
        elif not costs:
            # A cache-only/empty run has no replacement timing evidence.
            return False
        self.costs = costs
        self.heat_maximum = max(self.costs.values(), default=0)
        self._remember_link_heat()
        ids = list(dict.fromkeys([*self.costs, *self._heat_link_buckets]))
        self._heat_chunks = [ids[i:i+512] for i in range(0, len(ids), 512)]
        self._heat_chunk_of = {node_id: i for i, chunk in enumerate(self._heat_chunks)
                               for node_id in chunk}
        self._heat_dirty = set(range(len(self._heat_chunks)))
        self._heat_paths.clear()
        self._heat_link_paths.clear()
        self._heat_image = None
        self.update()
        return True

    def _remember_link_heat(self):
        for source in self.costs:
            for link in self._links_of_source.get(source, ()):
                target = str(link.targetNodeId)
                bucket = dependency_bucket(source, target, self.costs, self.heat_maximum)
                if bucket is not None:
                    self._heat_link_buckets.setdefault(source, {})[target] = bucket

    def _invalidate_moved_heat(self, moved):
        affected = set(moved)
        for node_id in moved:
            for index in self._view._incident_links.get(node_id, ()):
                affected.add(str(self._view.links[index].sourceNodeId))
        self._heat_dirty.update(self._heat_chunk_of[i] for i in affected
                                if i in self._heat_chunk_of)
        self._heat_image = self._glow_image = None
        self.update()

    def _paint_heat(self, painter):
        if not self.heat_enabled or not self.costs:
            return
        if self._heat_image is not None:
            painter.drawImage(0, 0, self._heat_image)
            return
        image = self._new_image()
        cache_painter = QtGui.QPainter(image)
        self._paint_heat_geometry(cache_painter)
        cache_painter.end()
        self._heat_image = image
        painter.drawImage(0, 0, image)

    def _new_image(self):
        ratio = self.devicePixelRatioF()
        image = QtGui.QImage(round(self.width()*ratio), round(self.height()*ratio),
                             QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        return image

    def _paint_heat_geometry(self, painter):
        for index in self._heat_dirty:
            paths = {}
            link_paths = {}
            for node_id in self._heat_chunks[index]:
                node = self._view.nodes.get(node_id)
                if node is None:
                    continue
                if node_id in self.costs:
                    bucket = color_bucket(self.costs[node_id], self.heat_maximum)
                    path = paths.setdefault(bucket, QtGui.QPainterPath())
                    path.addRect(float(node.position[0]), float(node.position[1]),
                                 float(node.size[0]), float(node.size[1]))
                for link in self._links_of_source.get(node_id, ()):
                    link_bucket = self._heat_link_buckets.get(node_id, {}).get(str(link.targetNodeId))
                    if link_bucket is not None:
                        link_paths.setdefault(link_bucket, QtGui.QPainterPath()).addPath(self._curve_path(link))
            self._heat_paths[index] = paths
            self._heat_link_paths[index] = link_paths
            self.heat_rebuilds += 1
        self._heat_dirty.clear()
        zoom = self._view.zoom
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        painter.setTransform(QtGui.QTransform(zoom, 0, 0, zoom,
            -self._view.panX*zoom, -self._view.panY*zoom))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        visible = QtCore.QRectF(self._view.panX, self._view.panY,
                                self.width()/zoom, self.height()/zoom)
        self.painted_heat_links = 0
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        for paths in self._heat_link_paths.values():
            for bucket, path in paths.items():
                if path.boundingRect().intersects(visible):
                    # Cover the underlying blue ribbon at every zoom, rather
                    # than leaving only a thin colored center stripe.
                    width = max(1.5, self._view._cachedLinkLineWidth*zoom)
                    pen = QtGui.QPen(QtGui.QColor(COLORS[bucket]), width)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawPath(path)
                    self.painted_heat_links += 1
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        for paths in self._heat_paths.values():
            for bucket, path in paths.items():
                if path.boundingRect().intersects(visible):
                    color = QtGui.QColor(COLORS[bucket]); color.setAlpha(135)
                    painter.setBrush(color)
                    painter.drawPath(path)
        painter.restore()

    @property
    def model(self):
        return self._activity

    @property
    def fade_seconds(self):
        return self._activity.fade_seconds

    @fade_seconds.setter
    def fade_seconds(self, seconds):
        import math

        seconds = max(0.1, float(seconds))
        self._activity.tau = seconds / -math.log(self._activity.floor)

    def fire(self, node_ids):
        """Light ``node_ids`` at full brightness, now."""
        node_ids = list(node_ids)
        self._run += 1
        self._run_of.update((node_id, self._run) for node_id in node_ids)
        self._activity.fire(node_ids, time.monotonic())
        self._glow_image = None
        self.update()

    def invalidate_links(self):
        self._indexed_links = None
        self._links_of_source.clear()
        self._run_of.clear()
        self._curve_paths.clear()
        self._heat_link_paths.clear()
        self._heat_link_buckets.clear()
        self._heat_image = self._glow_image = None

    def note_links(self):
        """Re-index the view's current links by source node id.

        The view rebuilds its flat link list from USD on the first paint
        after a load, so this is called lazily -- once links exist -- and
        again after every reload.
        """
        links = getattr(self._view, "links", None) or []
        index = {}
        for link in links:
            source = getattr(link, "sourceNodeId", None)
            if source is None:
                continue
            index.setdefault(str(source), []).append(link)
        self._links_of_source = index
        self._indexed_links = len(links)
        self._remember_link_heat()
        self._heat_dirty.update(range(len(self._heat_chunks)))
        self._heat_image = self._glow_image = None

    # -- paint -----------------------------------------------------------

    def eventFilter(self, watched, event):
        if watched is self._view and event.type() in (
                QtCore.QEvent.Type.Paint,
                QtCore.QEvent.Type.Resize,
                QtCore.QEvent.Type.Move,
                QtCore.QEvent.Type.UpdateRequest):
            if self.geometry() != self._view.rect():
                self.setGeometry(self._view.rect())
                self._heat_image = self._glow_image = None
            camera = (self._view.panX, self._view.panY, self._view.zoom)
            if camera != self._last_camera:
                if (self._last_camera is None or
                        math.ceil(math.log2(camera[2])) != math.ceil(math.log2(self._last_camera[2]))):
                    self._heat_dirty.update(range(len(self._heat_chunks)))
                self._last_camera = camera
                self._heat_image = self._glow_image = None
                self.update()
        return False

    def _on_tick(self):
        if not self.isVisible():
            return
        live = self.activity_enabled and self._activity.has_live(time.monotonic())
        if live or self._had_live:
            self.update()
        self._had_live = live

    def _world_to_screen(self, x, y):
        zoom = self._view.zoom
        return ((x - self._view.panX) * zoom,
                (y - self._view.panY) * zoom)

    def paintEvent(self, event):
        now = time.monotonic()
        live = self.activity_enabled and self._activity.has_live(now)
        selected = self._view._selectedNodes
        if not live and not selected and not (self.heat_enabled and self.costs):
            return
        if self._indexed_links != len(getattr(self._view, 'links', []) or []):
            self.note_links()
        nodes = getattr(self._view, "nodes", {}) or {}
        zoom = self._view.zoom
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self._paint_heat(painter)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor('#76d6ff'), 3))
        for node_id in selected:
            node = nodes.get(node_id)
            if node is not None:
                x, y = self._world_to_screen(node.position[0], node.position[1])
                painter.drawRoundedRect(QtCore.QRectF(x-2, y-2,
                    node.size[0]*zoom+4, node.size[1]*zoom+4), 6, 6)
        if live:
            if self._glow_image is None or now >= self._glow_expiry:
                self._build_glow(now)
            painter.setOpacity(math.exp(-max(0, now-self._glow_time)/self._activity.tau))
            painter.drawImage(0, 0, self._glow_image)
        painter.end()

    def _curve_path(self, link):
        start, end = link.start, link.end
        key = (str(link.sourceNodeId), str(link.targetNodeId))
        # Use the renderer's adaptive curve producer with at most half a
        # screen pixel of error. Overview noodles need far fewer segments.
        curve_zoom = 2.0**math.ceil(math.log2(self._view.zoom))
        endpoints = (float(start[0]), float(start[1]), float(end[0]), float(end[1]), curve_zoom)
        cached = self._curve_paths.get(key)
        if cached is None or cached[0] != endpoints:
            from UsdNoodles.linkRenderer import sampleLinkCurveAdaptive
            points = sampleLinkCurveAdaptive(start, end, flatness=0.5/curve_zoom)
            path = QtGui.QPainterPath(QtCore.QPointF(points[0][0], points[0][1]))
            for point in points[1:]:
                path.lineTo(point[0], point[1])
            cached = (endpoints, path)
            self._curve_paths[key] = cached
        return cached[1]

    def _build_glow(self, now):
        # Fade a cached screen image between observations. Batch geometry by
        # observed run so thousands of dependencies are not separate draw calls.
        live = self._activity.live(now)
        self.painted_nodes = self.painted_links = 0
        self._glow_time = now
        self._glow_expiry = min((self._activity._last_fire[i]+self.fade_seconds
                                 for i in live), default=now+self.fade_seconds)
        image = self._new_image()
        painter = QtGui.QPainter(image)
        zoom = self._view.zoom
        transform = QtGui.QTransform(zoom, 0, 0, zoom,
                                     -self._view.panX*zoom, -self._view.panY*zoom)
        from pxr import Gf
        pad = 12/zoom
        bounds = Gf.Range2d(Gf.Vec2d(self._view.panX-pad, self._view.panY-pad),
                           Gf.Vec2d(self._view.panX+self.width()/zoom+pad,
                                    self._view.panY+self.height()/zoom+pad))
        links = self._view.links
        if len(live) < len(self._view.nodes)//8:
            # Sparse edits must scale with executed operations, not the entire
            # visible graph (the overview can contain tens of thousands).
            node_ids = live.keys()
            candidates = (link for source in live for link in self._links_of_source.get(source, ()))
        else:
            node_ids, link_indices = self._view._spatialIndex.queryRegion(bounds)
            candidates = (links[index] for index in link_indices)
        visible = QtCore.QRectF(self._view.panX-pad, self._view.panY-pad,
                                self.width()/zoom+2*pad, self.height()/zoom+2*pad)
        groups = {}
        def group(node_id):
            run = self._run_of.get(node_id)
            if run not in groups:
                groups[run] = (live[node_id], QtGui.QPainterPath(), QtGui.QPainterPath())
            return groups[run]
        for node_id in node_ids:
            if node_id not in live:
                continue
            node = self._view.nodes[node_id]
            rect = QtCore.QRectF(node.position[0], node.position[1], node.size[0], node.size[1])
            if not rect.intersects(visible):
                continue
            x, y = self._world_to_screen(node.position[0], node.position[1])
            group(node_id)[1].addRect(x-3, y-3, node.size[0]*zoom+6, node.size[1]*zoom+6)
            self.painted_nodes += 1
        for link in candidates:
            source, target = str(link.sourceNodeId), str(link.targetNodeId)
            if source not in live or target not in live:
                continue
            if self._run_of.get(source) != self._run_of.get(target):
                continue
            path = self._curve_path(link)
            if not path.boundingRect().adjusted(-pad, -pad, pad, pad).intersects(visible):
                continue
            group(source)[2].addPath(path)
            self.painted_links += 1
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, zoom >= 0.04)
        for value, nodes, links in groups.values():
            painter.setTransform(transform)
            pen = QtGui.QPen(QtGui.QColor(*_GLOW, int(170*value)), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(links)
            painter.resetTransform()
            painter.setPen(QtGui.QPen(QtGui.QColor(*_GLOW, int(225*value)), 2))
            painter.setBrush(QtGui.QColor(*_GLOW, int(26*value)))
            painter.drawPath(nodes)
        painter.end()
        self._glow_image = image
