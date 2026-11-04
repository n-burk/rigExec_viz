"""Complete live operation graph, execution highlights, and thread lanes."""
import json
from bisect import bisect_left, bisect_right
from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets
from .session import trace_stats, chrome_trace, timeline_events, op_extent, frame_extent, held_time
from .memory import build_memory_graph
from .layout import layout_nodes
from .overlay import GlowOverlay
from .heatmap import COLORS


class ThreadTimeline(QtWidgets.QWidget):
    selected = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.events, self.lanes, self.hits = [], [], []
        self.frames = []
        self.frame_intervals = []
        self.phased = False
        self.setMouseTracking(True)
        self.setMinimumSize(1000, 300)

    def set_trace(self, events, graph, frames=None):
        self.frames = frames or []
        self.frame_intervals = []
        for frame in self.frames:
            extent = frame_extent(frame)
            if extent:
                self.frame_intervals.append(extent+(frame.get('time', '?'), frame['generation']))
        # Bars span memo start to publication end when the host reports them.
        self.events = sorted((e for e in events if e[1] and e[3]), key=lambda e: op_extent(e)[0])
        self.phased = any(len(e) > 8 and (e[7] or e[8]) for e in self.events)
        self.starts = [op_extent(e)[0] for e in self.events]
        self.max_ends = []
        end = 0
        for e in self.events:
            end = max(end, op_extent(e)[1])
            self.max_ends.append(end)
        self.graph = graph
        self.lanes = sorted({e[3] for e in self.events})
        self.start = min(self.starts, default=0)
        self.span = max((end-self.start for end in self.max_ends), default=1) or 1
        self.setMinimumHeight(max(300, 90+len(self.lanes)*36))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor('#20252c'))
        painter.setPen(QtGui.QColor('#e1e8ef'))
        painter.drawText(12, 20, ('Operations: dim memo, body, light value publication' if self.phased
                                  else 'Operation bodies')+' - elapsed milliseconds - horizontal scroll after zooming')
        if not self.events:
            painter.drawText(20, 75, 'Waiting for a timed live evaluation. Manipulate a control or change the usdview frame.')
            return
        width = self.width()-160
        scale = width/self.span
        lanes = {thread: i for i, thread in enumerate(self.lanes)}
        for thread, lane in lanes.items():
            painter.drawText(8, 90+lane*36, 'thread '+thread)
        last_label = -1000
        for start, end, frame_time, generation in self.frame_intervals:
            x = 150+(start-self.start)*scale
            w = max(2, (end-start)*scale)
            painter.fillRect(QtCore.QRectF(x, 42, w, 19), QtGui.QColor('#586779'))
            painter.setPen(QtGui.QColor('#e1e8ef'))
            if x > last_label+110:
                painter.drawText(int(x), 56, 'F%s / G%s' % (frame_time, generation))
                last_label = x
        self.hits = []
        pixels = set()
        clip = self.visibleRegion().boundingRect()
        left_time = self.start+(clip.left()-151)/scale
        right_time = self.start+(clip.right()-149)/scale
        first = bisect_left(self.max_ends, left_time)
        last = bisect_right(self.starts, right_time)
        for event_index in range(first, last):
            e = self.events[event_index]
            begin, end = op_extent(e)
            x = 150+(begin-self.start)*scale
            w = max(1, (end-begin)*scale)
            lane = lanes[e[3]]
            if x+w < clip.left() or x > clip.right():
                continue
            key = (lane, int(x))
            if w <= 1 and key in pixels:
                continue
            pixels.add(key)
            rect = QtCore.QRectF(x, 72+lane*36, w, 23)
            hue = (int(e[0])*37)%360
            if end-begin > e[2]:
                # Memo before the body, publication after it, in the op's hue.
                painter.fillRect(QtCore.QRectF(x, rect.top(), (e[1]-begin)*scale, 23),
                                 QtGui.QColor.fromHsv(hue, 60, 150))
                painter.fillRect(QtCore.QRectF(150+(e[1]+e[2]-self.start)*scale, rect.top(),
                                               (end-e[1]-e[2])*scale, 23),
                                 QtGui.QColor.fromHsv(hue, 45, 250))
                body = QtCore.QRectF(150+(e[1]-self.start)*scale, rect.top(), max(1, e[2]*scale), 23)
                painter.fillRect(body, QtGui.QColor.fromHsv(hue, 135, 225))
            else:
                painter.fillRect(rect, QtGui.QColor.fromHsv(hue, 135, 225))
            self.hits.append((rect, e))
        painter.setPen(QtGui.QColor('#e1e8ef'))
        for i in range(11):
            x = 150+width*i/10
            painter.drawText(int(x), 35, '%.2f' % (self.span*i/10000))

    def mouseMoveEvent(self, event):
        for rect, e in reversed(self.hits):
            if rect.contains(event.position()):
                op = self.graph.get(int(e[0]), {})
                QtWidgets.QToolTip.showText(event.globalPosition().toPoint(),
                    's%d %s\n%s\n%d us - thread %s%s%s' % (e[0], op.get('kind',''), op.get('label',''), e[2], e[3],
                    ('\nmemo %d us - publication %d us' % (e[7], e[8])) if len(e) > 8 else '',
                    ('\nFrame %s / generation %s' % (e[5], e[6])) if len(e) > 6 else ''))
                return

    def mousePressEvent(self, event):
        for rect, e in reversed(self.hits):
            if rect.contains(event.position()):
                self.selected.emit(int(e[0]))
                return


class RigVizWindow(QtWidgets.QMainWindow):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.setWindowTitle('RigExec Live Graph and Threads')
        self.resize(1400, 900)
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        controls = QtWidgets.QHBoxLayout()
        layout.addLayout(controls)
        self.live = QtWidgets.QCheckBox('Follow live'); self.live.setChecked(True)
        self.live.toggled.connect(lambda enabled: self.refresh_history() if enabled else None)
        self.record = QtWidgets.QCheckBox('Record operation timing'); self.record.setChecked(True)
        self.record.toggled.connect(self._record)
        controls.addWidget(self.live); controls.addWidget(self.record)
        self.history = QtWidgets.QComboBox(); controls.addWidget(self.history)
        self.history.activated.connect(self.show_trace)
        export = QtWidgets.QPushButton('Export Chrome trace'); controls.addWidget(export)
        export.clicked.connect(self.export_trace)
        clear = QtWidgets.QPushButton('Clear capture'); controls.addWidget(clear)
        clear.clicked.connect(self.clear_capture)
        self.tabs = QtWidgets.QTabWidget(); layout.addWidget(self.tabs)
        graph_tab = QtWidgets.QWidget(); gl = QtWidgets.QVBoxLayout(graph_tab)
        self.search = QtWidgets.QLineEdit(); self.search.setPlaceholderText('Search full graph by label, kind, or step number; Enter to search')
        self.search.returnPressed.connect(self.find); gl.addWidget(self.search)
        split = QtWidgets.QSplitter(); gl.addWidget(split)
        self.results = QtWidgets.QListWidget(); split.addWidget(self.results)
        self.results.itemClicked.connect(lambda item: self.focus(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        from .graph_view import LiveGraphView
        self.view = LiveGraphView(); split.addWidget(self.view)
        self.overlay = GlowOverlay(self.view, parent=self.view)
        self.view.inspectionSelectionChanged.connect(self.overlay.update)
        self.overlay.fade_seconds = 4.0
        self.overlay.setGeometry(self.view.rect())
        self.overlay.raise_()
        heat_controls = QtWidgets.QHBoxLayout()
        self.heat = QtWidgets.QCheckBox('Operation cost heatmap'); self.heat.setChecked(True)
        self.heat.setToolTip('Nodes show measured body time. Noodles use the source cost when both endpoints were timed in the same generation.')
        self.heat.toggled.connect(self.toggle_heat)
        heat_controls.addWidget(self.heat)
        self.flashes = QtWidgets.QCheckBox('Execution flashes'); self.flashes.setChecked(True)
        self.flashes.toggled.connect(self.toggle_flashes)
        heat_controls.addWidget(self.flashes)
        swatches = ' '.join('<span style="color:%s">&#9632;</span>' % c for c in COLORS)
        heat_controls.addWidget(QtWidgets.QLabel('Short '+swatches+' Long (log scale)'))
        self.heat_metrics = QtWidgets.QLabel('Waiting for timed operations')
        heat_controls.addWidget(self.heat_metrics)
        heavy = QtWidgets.QPushButton('Show heaviest'); heavy.clicked.connect(self.show_heaviest)
        heat_controls.addWidget(heavy)
        gl.insertLayout(1, heat_controls)
        frame = QtWidgets.QPushButton('Frame all operations')
        frame.clicked.connect(self.frame_all)
        graph_actions = QtWidgets.QHBoxLayout()
        graph_actions.addWidget(frame)
        chunks = QtWidgets.QPushButton('Vertex chunks')
        chunks.clicked.connect(self.show_vertex_chunks)
        graph_actions.addWidget(chunks)
        gl.insertLayout(1, graph_actions)
        self.details = QtWidgets.QPlainTextEdit(); self.details.setReadOnly(True); split.addWidget(self.details)
        split.setSizes([260, 850, 290])
        self.tabs.addTab(graph_tab, 'In-memory operation graph')
        trace_tab = QtWidgets.QWidget(); tl = QtWidgets.QVBoxLayout(trace_tab)
        self.metrics = QtWidgets.QLabel(); tl.addWidget(self.metrics)
        zoom = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); zoom.setRange(1, 300); zoom.setValue(1)
        zoom.valueChanged.connect(lambda n: self.timeline.setMinimumWidth(1000*n)); tl.addWidget(zoom)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); tl.addWidget(scroll)
        self.timeline = ThreadTimeline(); scroll.setWidget(self.timeline)
        self.timeline.selected.connect(self.focus)
        self.tabs.addTab(trace_tab, 'Thread trace')
        self.tabs.currentChanged.connect(lambda index: self.refresh_history()
                                        if index == 1 and self.live.isChecked() else None)
        self.status = QtWidgets.QLabel(); self.statusBar().addWidget(self.status)
        self.shown_key = None
        self.snapshot = None
        self.display_history = []
        self.timer = QtCore.QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(100)
        self.last_selected = None
        self.heat_generation = None
        self.heat_time = None
        self.observed_steps = set()
        self.observed_generation = None

    def _record(self, enabled):
        self.session.recording = enabled
        self.poll()

    def poll(self):
        try:
            reply = self.session.poll()
            if not reply.get('active'):
                self.status.setText('Waiting for an active RigExec imaging evaluator')
                if self.shown_key is not None:
                    self.shown_key = None
                    self.snapshot = None
                    self.display_history = []
                    self.results.clear(); self.details.clear(); self.history.clear()
                    self.timeline.set_trace([], {})
                    build_memory_graph(self.view, [], [], {})
                    self.overlay.model.clear()
                    self.update_heat([])
                return
            self.status.setText('%s - %d operations - generation %s - evaluator time %s - viewport time %s' %
                (self.session.rig, len(self.session.graph), reply['generation'], reply['time'], reply['viewport_time']))
            if self.shown_key != reply['graph_key']:
                self.snapshot = None
                self.display_history = []
                self.timeline.set_trace([], self.session.graph)
                self.history.clear()
                self.shown_key = reply['graph_key']; self.find()
                self.load_graph()
                print('[rigExec_viz] attached to %s: %d live operations, Work concurrency limit %s' %
                      (self.session.rig, len(self.session.graph), reply['concurrency_limit']), flush=True)
            if 'trace' in reply and self.live.isChecked():
                self.observed_steps = {int(e[0]) for e in reply['trace']}
                self.observed_generation = reply['generation']
                self.last_selected = None
                if self.tabs.currentIndex() == 1:
                    self.refresh_history()
                if reply.get('recording'):
                    self.update_heat(reply['trace'], reply['generation'], reply.get('time'))
                self.overlay.fire('step:%d' % e[0] for e in reply['trace'])
            selected = getattr(self.view, '_selectedNodes', set())
            if len(selected) == 1:
                selected_id = next(iter(selected))
                if selected_id != self.last_selected:
                    self.last_selected = selected_id
                    step = int(selected_id.split(':')[-1])
                    self.show_details(step)
        except Exception as error:
            self.status.setText('Live bridge error: '+str(error))

    def find(self):
        query = self.search.text().lower().strip()
        if query in ('vertex chunk', 'vertex chunks'):
            query = 'revisionchunk'
        self.results.clear()
        for step, op in self.session.graph.items():
            if not query or query == str(step) or query in (op['label']+' '+op['kind']).lower():
                item = QtWidgets.QListWidgetItem('s%d %s\n%s' % (step, op['kind'], op['label']))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, step); self.results.addItem(item)
                if self.results.count() >= 100: break

    def show_vertex_chunks(self):
        self.search.setText('vertex chunks')
        self.find()
        chunks = [step for step, op in self.session.graph.items() if op['kind'] == 'RevisionChunk']
        if chunks:
            self.focus(chunks[0])
        else:
            self.details.setPlainText('The current host operation graph contains no vertex chunks.')

    def toggle_heat(self, enabled):
        self.overlay.heat_enabled = enabled
        self.overlay.update()

    def toggle_flashes(self, enabled):
        self.overlay.activity_enabled = enabled
        self.overlay.update()

    def update_heat(self, events, generation=None, frame_time=None):
        replaced = self.overlay.set_heat(events, clear=generation is None)
        if replaced:
            self.heat_generation, self.heat_time = generation, frame_time
        if generation is None:
            self.observed_steps.clear()
            self.observed_generation = None
        self.heat_metrics.setText(('G%s: %d timed nodes; max %g us' %
            (self.heat_generation, len(self.overlay.costs), self.overlay.heat_maximum))
            if self.overlay.costs else 'Waiting for timed operations')
        self.last_selected = None

    def show_heaviest(self):
        self.results.clear()
        from heapq import nlargest
        for node_id, cost in nlargest(100, self.overlay.costs.items(), key=lambda entry: entry[1]):
            step = int(node_id.split(':')[-1])
            op = self.session.graph.get(step)
            if op is None: continue
            item = QtWidgets.QListWidgetItem('%g us - s%d %s\n%s' % (cost, step, op['kind'], op['label']))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, step); self.results.addItem(item)

    def show_details(self, step):
        cost = self.overlay.costs.get('step:%d' % step)
        timing = ('Operation body: %g us — heat sample G%s, frame %s' %
                  (cost, self.heat_generation, self.heat_time)
                  if cost is not None else 'No timing sample in the displayed heatmap generation')
        timing += '\n%s in latest followed generation G%s.' % (
            'Observed running' if step in self.observed_steps else 'Not observed running',
            self.observed_generation)
        timing += '\nBody timings are elapsed intervals, not CPU time or dependency wait time.'
        self.details.setPlainText(timing+'\n\n'+json.dumps(self.session.graph[step], indent=2))

    def focus(self, step):
        graph = self.session.graph
        if step not in graph: return
        self.view.clearSelection()
        node = self.view.nodes.get('step:%d' % step)
        if node is not None:
            node.selected = True
            self.view._selectedNodes.add(node.id)
            self.view.inspectionSelectionChanged.emit()
            self.view.frameScene()
        self.show_details(step)
        self.tabs.setCurrentIndex(0)

    def load_graph(self):
        graph = self.session.graph
        ids = list(graph)
        nodes = [dict(graph[i], id='step:%d'%i, domain='step', order=i) for i in ids]
        known = set(ids)
        edges = [('step:%d'%i, 'step:%d'%int(j)) for i in ids for j in graph[i]['succs'] if int(j) in known]
        build_memory_graph(self.view, nodes, edges, layout_nodes([n['id'] for n in nodes], edges,
                           wrap=max(12, int(len(nodes)**0.5)*2)))
        self.overlay.model.clear()
        self.update_heat([])
        self.overlay.invalidate_links()
        self.frame_all()
        self.details.setPlainText('All %d operations and %d dependencies loaded.\nWheel to zoom; search to frame an operation.\nAmber nodes executed in the latest observed run; amber noodles connect executed operations.' % (len(nodes), len(edges)))

    def frame_all(self):
        self.view.clearSelection()
        self.view.frameScene()

    def refresh_history(self):
        was_all = self.history.currentIndex() <= 0
        self.display_history = list(self.session.history)
        self.history.clear()
        self.history.addItem('Timeline: all captured frames')
        for snap in self.display_history:
            self.history.addItem('Frame %s / generation %s' % (snap.get('time', '?'), snap['generation']))
        self.history.setCurrentIndex(0 if was_all else self.history.count()-1)
        self.show_trace(self.history.currentIndex())

    def show_trace(self, index):
        if not self.display_history: return
        frames = self.display_history if index == 0 else self.display_history[index-1:index]
        if not frames: return
        self.snapshot = dict(frames[-1], frames=frames, trace=timeline_events(frames))
        events = self.snapshot['trace']; stats = trace_stats(events)
        self.timeline.set_trace(events, self.session.graph, frames)
        held = (' - with memo and publication %.3f ms' % (held_time(events)/1000)
                if self.timeline.phased else '')
        self.metrics.setText('%d captured evaluations - %d operations - %d threads (Work limit %s) - peak overlap %d - timeline %.3f ms - work %.3f ms%s\n'
            'Actual elapsed time, including gaps between frames. Polling may skip runs; cache hits and detached warming are not traced. %d older captures evicted.' %
            (len(frames), len(events), stats['threads'], self.snapshot.get('concurrency_limit', '?'), stats['peak'], stats['span']/1000, stats['work']/1000, held, self.session.dropped_frames))

    def clear_capture(self):
        self.session.history.clear()
        self.session.dropped_frames = 0
        self.display_history = []
        self.snapshot = None
        self.history.clear()
        self.timeline.set_trace([], self.session.graph)
        self.metrics.setText('Capture cleared. Waiting for new evaluations.')
        self.update_heat([])

    def export_trace(self):
        if self.live.isChecked():
            self.refresh_history()
        if not self.snapshot: return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export trace', 'rigexec-trace.json', 'JSON (*.json)')
        if path:
            with open(path, 'w', encoding='utf-8') as stream:
                json.dump(chrome_trace(self.timeline.graph, self.snapshot), stream)

    def closeEvent(self, event):
        self.timer.stop(); self.overlay._timer.stop(); self.session.close(); super().closeEvent(event)
