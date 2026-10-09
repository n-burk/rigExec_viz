"""Read-only snapshots of usdview's standing evaluator, on its owner thread."""
import ctypes
import json
import threading
from collections import deque


def neighborhood(graph, focus, limit=128):
    pending, seen = deque([focus]), set()
    while pending and len(seen) < limit:
        step = pending.popleft()
        if step in seen or step not in graph:
            continue
        seen.add(step)
        op = graph[step]
        pending.extend(int(i) for i in op['preds'] + op['succs'] if int(i) not in seen)
    return sorted(seen)


def trace_phases(frame):
    """[memo_us, publish_us] per trace row; zeros from a host without them."""
    rows = frame.get('trace', [])
    phases = frame.get('trace_phases')
    if not isinstance(phases, list) or len(phases) != len(rows):
        return [(0, 0)]*len(rows)
    return [(row[0], row[1]) if len(row) >= 2 else (0, 0) for row in phases]


def timeline_events(frames):
    """[step, start, duration, thread, seq, time, generation, memo, publish]."""
    return [list(event[:5])+[frame.get('time'), frame['generation'], phase[0], phase[1]]
            for frame in frames for event, phase in zip(frame['trace'], trace_phases(frame))]


def op_extent(e):
    """Memo start to publication end when the event carries both phases."""
    memo, publish = (e[7], e[8]) if len(e) > 8 else (0, 0)
    return e[1]-memo, e[1]+e[2]+publish


def frame_extent(frame):
    """First memo start to last publication end of a frame's timed ops."""
    spans = [(e[1]-memo, e[1]+e[2]+publish)
             for e, (memo, publish) in zip(frame['trace'], trace_phases(frame)) if e[1] and e[3]]
    if not spans:
        return None
    return min(begin for begin, _ in spans), max(end for _, end in spans)


def trace_stats(events):
    timed = [e for e in events if e[1] and e[3]]
    if not timed:
        return dict(span=0, work=0, threads=0, peak=0)
    boundaries = sorted((t, delta) for e in timed if e[2] > 0
                        for t, delta in ((e[1], 1), (e[1]+e[2], -1)))
    active = peak = 0
    for _, delta in boundaries:
        active += delta
        peak = max(active, peak)
    return dict(span=max(e[1]+e[2] for e in timed)-min(e[1] for e in timed),
                work=sum(e[2] for e in timed), threads=len({e[3] for e in timed}), peak=peak)


def held_time(events):
    """Summed memo, body and publication of the timed ops (body alone without phases)."""
    return sum(end-begin for begin, end in map(op_extent, (e for e in events if e[1] and e[3])))


def chrome_trace(graph, snapshot):
    if 'frames' in snapshot:
        events = []
        for frame in snapshot['frames']:
            events.extend(chrome_trace(graph, frame)['traceEvents'])
            extent = frame_extent(frame)
            if extent:
                start, end = extent
                events.append(dict(name='Frame %s / generation %s' % (frame.get('time'), frame['generation']),
                                   cat='frame', ph='X', pid=1, tid='Frames', ts=start, dur=end-start))
        return {'traceEvents': events}
    # The event stays the body interval; memo and publication ride as args.
    return {'traceEvents': [dict(name=graph.get(int(e[0]), {}).get('label', str(e[0])),
            cat=graph.get(int(e[0]), {}).get('kind', ''), ph='X', pid=1, tid=e[3],
            ts=e[1], dur=e[2], args=dict({'step': int(e[0]), 'generation': snapshot['generation'],
                                          'graph_key': snapshot['graph_key'], 'frame': snapshot.get('time')},
                                         **({'memo_us': phase[0], 'publish_us': phase[1]}
                                            if 'trace_phases' in snapshot else {})))
            for e, phase in zip(snapshot.get('trace', []), trace_phases(snapshot)) if e[1] and e[3]]}


class NativeTransport:
    def __init__(self):
        import rigExecUsdview
        self.lib = ctypes.CDLL(rigExecUsdview.ImagingLibraryPath())
        self.read = self.lib.RigExecImaging_LiveDebugJsonForStage
        self.read.argtypes = [ctypes.c_longlong, ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int]
        self.read.restype = ctypes.c_int
        self.record = self.lib.RigExecImaging_SetLiveOpTimingForStage
        self.record.argtypes = [ctypes.c_longlong, ctypes.c_char_p, ctypes.c_int]
        self.record.restype = ctypes.c_int

    def snapshot(self, stage, rig, graph, generation):
        args = (stage, rig.encode(), graph.encode(), generation.encode())
        size = self.read(*args, None, 0)
        if size < 0:
            return {'active': False, 'rigs': []}
        buffer = ctypes.create_string_buffer(size+1)
        if self.read(*args, buffer, len(buffer)) != size:
            raise RuntimeError('Live snapshot changed during copy')
        return json.loads(buffer.value)


class LiveSession:
    def __init__(self, api, rig='', transport=None):
        self.api, self.rig = api, rig
        self.transport = transport or NativeTransport()
        self.owner = threading.get_ident()
        self.stage_id = 0
        self.graph = {}
        self.graph_key = self.generation = ''
        self.recording = True
        self.history = deque()
        self.max_frames = 300
        self.max_events = 1000000
        self.dropped_frames = 0
        self.latest = {}

    def _check(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError('Live inspection must run on the usdview owner thread')

    def close(self):
        self._check()
        if self.stage_id and self.rig:
            self.transport.record(self.stage_id, self.rig.encode(), 0)

    def poll(self):
        self._check()
        from pxr import UsdUtils
        stage = self.api.stage
        stage_id = UsdUtils.StageCache.Get().GetId(stage).ToLongInt() if stage else 0
        return self.sample(stage_id)

    def sample(self, stage_id):
        """Read an already-owned stage ID; exposed separately for model tests."""
        self._check()
        if stage_id != self.stage_id:
            self.close()
            self.stage_id = stage_id
            self.graph_key = self.generation = ''
            self.graph.clear()
            self.history.clear()
            self.dropped_frames = 0
        reply = self.transport.snapshot(stage_id, self.rig, self.graph_key, self.generation)
        if not reply.get('active') and reply.get('rigs') and self.rig not in reply['rigs']:
            self.rig = reply['rigs'][0]
            reply = self.transport.snapshot(stage_id, self.rig, '', '')
        if reply.get('active'):
            if reply['recording'] != self.recording:
                self.transport.record(stage_id, self.rig.encode(), int(self.recording))
            if 'graph' in reply:
                self.graph = {int(op['step']): op for op in reply.pop('graph')}
                self.history.clear()
                self.dropped_frames = 0
            self.graph_key, self.generation = reply['graph_key'], reply['generation']
            if 'trace' in reply:
                self.history.append(reply)
                count = sum(len(frame['trace']) for frame in self.history)
                while len(self.history) > 1 and (len(self.history) > self.max_frames or count > self.max_events):
                    count -= len(self.history.popleft()['trace'])
                    self.dropped_frames += 1
        else:
            self.graph.clear()
            self.history.clear()
            self.dropped_frames = 0
            self.graph_key = self.generation = ''
        self.latest = reply
        return reply
