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

from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets

from .activity import ActivityModel
from .heatmap import COLORS, color_bucket, operation_costs

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
        self.heat_rebuilds = 0
        view.inspectionNodesMoved.connect(self._invalidate_moved_heat)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        view.installEventFilter(self)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(33)

    # -- activity --------------------------------------------------------

    def set_heat(self, events):
        self.costs = operation_costs(events)
        self.heat_maximum = max(self.costs.values(), default=0)
        ids = list(self.costs)
        self._heat_chunks = [ids[i:i+512] for i in range(0, len(ids), 512)]
        self._heat_chunk_of = {node_id: i for i, chunk in enumerate(self._heat_chunks)
                               for node_id in chunk}
        self._heat_dirty = set(range(len(self._heat_chunks)))
        self._heat_paths.clear()
        self.update()

    def _invalidate_moved_heat(self, moved):
        self._heat_dirty.update(self._heat_chunk_of[i] for i in moved
                                if i in self._heat_chunk_of)
        self.update()

    def _paint_heat(self, painter):
        if not self.heat_enabled or not self.costs:
            return
        for index in self._heat_dirty:
            paths = {}
            for node_id in self._heat_chunks[index]:
                node = self._view.nodes.get(node_id)
                if node is None:
                    continue
                bucket = color_bucket(self.costs[node_id], self.heat_maximum)
                path = paths.setdefault(bucket, QtGui.QPainterPath())
                path.addRect(float(node.position[0]), float(node.position[1]),
                             float(node.size[0]), float(node.size[1]))
            self._heat_paths[index] = paths
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
        self.update()

    def invalidate_links(self):
        self._indexed_links = None
        self._links_of_source.clear()
        self._run_of.clear()
        self._curve_paths.clear()

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

    # -- paint -----------------------------------------------------------

    def eventFilter(self, watched, event):
        if watched is self._view and event.type() in (
                QtCore.QEvent.Type.Paint,
                QtCore.QEvent.Type.Resize,
                QtCore.QEvent.Type.Move,
                QtCore.QEvent.Type.UpdateRequest):
            if self.geometry() != self._view.rect():
                self.setGeometry(self._view.rect())
            camera = (self._view.panX, self._view.panY, self._view.zoom)
            if camera != self._last_camera:
                self._last_camera = camera
                self.update()
        return False

    def _on_tick(self):
        if not self.isVisible():
            return
        live = self.activity_enabled and bool(self._activity.live(time.monotonic()))
        if live or self._had_live:
            self.update()
        self._had_live = live

    def _world_to_screen(self, x, y):
        zoom = self._view.zoom
        return ((x - self._view.panX) * zoom,
                (y - self._view.panY) * zoom)

    def paintEvent(self, event):
        self.painted_nodes = self.painted_links = 0
        live = self._activity.live(time.monotonic()) if self.activity_enabled else {}
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
        for node_id, value in live.items():
            node = nodes.get(node_id)
            if node is None:
                continue
            self._paint_node_glow(painter, node, value, zoom)
            self._paint_output_links(painter, node_id, value, live)

    def _paint_node_glow(self, painter, node, value, zoom):
        x, y = self._world_to_screen(
            float(node.position[0]), float(node.position[1]))
        w = float(node.size[0]) * zoom
        h = float(node.size[1]) * zoom
        pad = 3.0 + 7.0 * value
        rect = QtCore.QRectF(x - pad, y - pad, w + 2 * pad, h + 2 * pad)
        if not rect.intersects(QtCore.QRectF(self.rect())):
            return
        self.painted_nodes += 1
        r, g, b = _GLOW
        painter.setBrush(QtGui.QColor(r, g, b, int(26 * value)))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 12.0, 12.0)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(
            QtGui.QColor(r, g, b, int(225 * value)), 1.0 + 3.0 * value))
        painter.drawRoundedRect(rect, 12.0, 12.0)

    def _paint_output_links(self, painter, node_id, value, live):
        links = self._links_of_source.get(node_id)
        if not links:
            return
        r, g, b = _GLOW
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(
            QtGui.QColor(r, g, b, int(170 * value)), 2.0 + 4.0 * value,
            QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        for link in links:
            if str(getattr(link, 'targetNodeId', '')) not in live:
                continue
            if self._run_of.get(node_id) != self._run_of.get(str(link.targetNodeId)):
                continue
            start = getattr(link, "start", None)
            end = getattr(link, "end", None)
            if start is None or end is None:
                continue
            x0, y0 = self._world_to_screen(float(start[0]), float(start[1]))
            x1, y1 = self._world_to_screen(float(end[0]), float(end[1]))
            if max(x0, x1) < 0 or min(x0, x1) > self.width() or max(y0, y1) < 0 or min(y0, y1) > self.height():
                continue
            # Use the renderer's geometry producer, including backward bows.
            key = (node_id, str(link.targetNodeId))
            endpoints = (float(start[0]), float(start[1]), float(end[0]), float(end[1]))
            cached = self._curve_paths.get(key)
            if cached is None or cached[0] != endpoints:
                from UsdNoodles.linkRenderer import sampleLinkCurve
                points = sampleLinkCurve(start, end, 32)
                path = QtGui.QPainterPath(QtCore.QPointF(points[0][0], points[0][1]))
                for point in points[1:]:
                    path.lineTo(point[0], point[1])
                cached = (endpoints, path)
                self._curve_paths[key] = cached
            zoom = self._view.zoom
            transform = QtGui.QTransform(zoom, 0, 0, zoom,
                                         -self._view.panX*zoom, -self._view.panY*zoom)
            painter.drawPath(transform.map(cached[1]))
            self.painted_links += 1
