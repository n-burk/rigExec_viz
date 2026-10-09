"""Graph/trace UI against usdview's real imaging evaluator.

Run with testusdview and RIGEXEC_VIZ_ROOT on PYTHONPATH. No private evaluator.
"""
import os


def testUsdviewInputFunction(appController):
    from pxr import Usd
    from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets
    from unittest.mock import patch
    from rigexec_viz.session import LiveSession, trace_stats
    from rigexec_viz.window import RigVizWindow
    import time
    started = time.monotonic()
    api = appController._usdviewApi
    source = api.stage.GetRootLayer().ExportToString()
    session = LiveSession(api)
    window = RigVizWindow(session, api.qMainWindow)
    window.show()
    QtWidgets.QApplication.processEvents()
    window.poll()
    assert session.graph, window.status.text()
    assert not window.status.text().startswith('Live bridge error'), window.status.text()
    print('FULL_GRAPH_LOAD_SECONDS', time.monotonic()-started, flush=True)
    first = session.generation
    window.tabs.setCurrentIndex(1)
    api.dataModel.currentFrame = Usd.TimeCode(api.stage.GetStartTimeCode()+12)
    window.poll()
    assert session.generation != first
    assert session.history
    assert window.timeline.events, window.status.text()
    assert trace_stats(session.history[-1]['trace'])['threads'] >= 1
    for offset in (13, 14):
        api.dataModel.currentFrame = Usd.TimeCode(api.stage.GetStartTimeCode()+offset)
        window.poll()
    assert len(window.timeline.frame_intervals) >= 3
    from rigexec_viz.heatmap import operation_costs
    assert window.overlay.costs == operation_costs(session.history[-1]['trace'])
    assert window.overlay.heat_maximum == max(window.overlay.costs.values())
    window.show_heaviest()
    heaviest = max(window.overlay.costs, key=window.overlay.costs.get)
    assert window.results.item(0).data(QtCore.Qt.ItemDataRole.UserRole) == int(heaviest.split(':')[-1])
    assert len(window.snapshot['frames']) >= 3
    assert len({e[6] for e in window.timeline.events}) >= 3
    assert window.timeline.span > max(end-start for start, end, _, _ in window.timeline.frame_intervals)
    if os.environ.get('RIGEXEC_VIZ_CAPTURE'):
        QtWidgets.QApplication.processEvents()
        window.grab().save(os.environ['RIGEXEC_VIZ_CAPTURE']+'.timeline.png')
    assert len(window.view.nodeGraph.nodes) == len(session.graph)
    window.view.minimap.getGraphBounds()
    bounds_rebuilds = window.view.minimap.bounds_rebuilds
    for _ in range(5):
        window.view.panX += 10
        window.view._zoomAroundPoint(window.view.zoom*1.01, (100, 100))
        window.view.minimap.getGraphBounds()
    assert window.view.minimap.bounds_rebuilds == bounds_rebuilds
    # Camera release and the first passive move must not resume expensive
    # authoring hit tests over the complete operation graph.
    point = QtCore.QPointF(window.view.width()/2, window.view.height()/2)
    release = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, point, point,
        QtCore.Qt.MouseButton.MiddleButton, QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier)
    hover = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, point, point,
        QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier)
    with patch.object(window.view.linkRenderer, 'findLinkUnderCursor', side_effect=AssertionError('noodle picking on hover')), \
         patch.object(window.view, '_updatePropertyTooltip', side_effect=AssertionError('USD tooltip scan on hover')), \
         patch.object(window.view, '_updateHoveredPort', side_effect=AssertionError('authoring port scan on hover')):
        window.view.mouseReleaseEvent(release)
        window.view.mouseMoveEvent(hover)
    fired = {'step:%d' % e[0] for e in session.history[-1]['trace']}
    assert fired <= set(window.overlay.model._last_fire)
    window.focus(int(session.history[-1]['trace'][0][0]))
    assert len(window.view.nodeGraph.nodes) == len(session.graph)
    # Reading the panel must not pull another evaluation.
    count = session.latest['evaluations']
    fires = dict(window.overlay.model._last_fire)
    window.poll()
    assert session.latest['evaluations'] == count
    assert window.overlay.model._last_fire == fires
    assert source == api.stage.GetRootLayer().ExportToString()
    if os.environ.get('RIGEXEC_VIZ_CAPTURE'):
        window.tabs.setCurrentIndex(0)
        QtWidgets.QApplication.processEvents()
        window.overlay.note_links()
        assert window.overlay._links_of_source
        window.overlay.fire(fired)
        window.overlay.repaint()
        assert window.overlay._heat_paths
        heat_rebuilds = window.overlay.heat_rebuilds
        window.view.panX += 2
        window.overlay.repaint()
        assert window.overlay.heat_rebuilds == heat_rebuilds
        started = time.monotonic()
        window.grab().save(os.environ['RIGEXEC_VIZ_CAPTURE'])
        print('GRAPH_CAPTURE_SECONDS', time.monotonic()-started, flush=True)
        window.frame_all()
        QtWidgets.QApplication.processEvents()
        window.overlay.fire(fired)
        window.overlay.repaint()
        assert window.overlay.painted_nodes > 0
        assert window.overlay.painted_links > 0
        window.grab().save(os.environ['RIGEXEC_VIZ_CAPTURE']+'.all.png')
        window.flashes.setChecked(False)
        window.focus(int(heaviest.split(':')[-1]))
        QtWidgets.QApplication.processEvents()
        window.overlay.repaint()
        window.grab().save(os.environ['RIGEXEC_VIZ_CAPTURE']+'.heat.png')
        # Time cached heat painting separately from GL readback and PNG encoding.
        image = QtGui.QImage(window.overlay.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        started = time.monotonic()
        for _ in range(10):
            window.overlay._paint_heat(painter)
        print('CACHED_HEAT_PAINT_SECONDS', (time.monotonic()-started)/10, flush=True)
        painter.end()
        window.flashes.setChecked(True)
    # Selecting and moving a local operation node must not re-marshal the full
    # node snapshot or dirty unrelated dependency chunks.
    view = window.view
    step = int(session.history[-1]['trace'][0][0])
    window.focus(step)
    view.paintGL()
    node = view.nodes['step:%d' % step]
    before = tuple(node.position)
    session_layer = api.stage.GetSessionLayer().ExportToString()
    point = QtCore.QPointF((node.position[0]+node.size[0]*0.5-view.panX)*view.zoom,
                          (node.position[1]+node.size[1]*0.4-view.panY)*view.zoom)
    moved_point = point+QtCore.QPointF(16, 12)
    def mouse(kind, pos, button, buttons):
        return QtGui.QMouseEvent(kind, pos, pos, button, buttons, QtCore.Qt.KeyboardModifier.NoModifier)
    with patch.object(view.nodeGraph, 'syncNodesFromModels', side_effect=AssertionError('full node sync during drag')), \
         patch.object(view, '_updateLinkSelectionFromNodes', side_effect=AssertionError('full edge selection scan')):
        view.mousePressEvent(mouse(QtCore.QEvent.Type.MouseButtonPress, point,
            QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton))
        assert node.id in view._selectedNodes
        view.paintGL()
        view.mouseMoveEvent(mouse(QtCore.QEvent.Type.MouseMove, moved_point,
            QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton))
        expected_chunks = {i//view._LINK_CHUNK for i in view._incident_links.get(node.id, ())}
        assert view._dirty_link_chunks == expected_chunks
        view.paintGL()
        view.mouseReleaseEvent(mouse(QtCore.QEvent.Type.MouseButtonRelease, moved_point,
            QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.NoButton))
        view.paintGL()
    assert tuple(node.position) != before
    assert window.overlay._heat_dirty == {window.overlay._heat_chunk_of[node.id]}
    window.overlay.repaint()
    assert not window.overlay._heat_dirty
    assert not view.draggingNodes and not node._dragging
    after_drag = tuple(node.position)
    from UsdNoodles._usdNoodles import NoodlesUndoManager
    undo = NoodlesUndoManager.instance()
    assert undo.undoDescription() == 'Move operation nodes'
    undo.undo()
    assert tuple(node.position) == before
    undo.redo()
    assert tuple(node.position) == after_drag
    # Box selection still selects operation nodes through the spatial index.
    view.clearSelection()
    view._inspection_marquee_base = set()
    view.marqueeStart = QtCore.QPointF(node.position[0]-1, node.position[1]-1)
    end = QtCore.QPointF((node.position[0]+node.size[0]+1-view.panX)*view.zoom,
                        (node.position[1]+node.size[1]+1-view.panY)*view.zoom)
    view._update_inspection_marquee(end)
    assert node.id in view._selectedNodes
    assert source == api.stage.GetRootLayer().ExportToString()
    assert session_layer == api.stage.GetSessionLayer().ExportToString()
    window.heat.setChecked(False)
    assert not window.overlay.heat_enabled
    window.heat.setChecked(True)
    window.update_heat([])
    assert not window.overlay.costs and not window.overlay._heat_paths
    window.close()
    assert not session.transport.snapshot(session.stage_id, session.rig, '', '')['recording']
    print('LIVE_VIZ_UI_OK', len(session.graph), trace_stats(session.history[-1]['trace']))
    appController._stageView.makeCurrent()
