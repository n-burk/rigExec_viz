import unittest
from rigexec_viz.session import neighborhood, trace_stats, chrome_trace


class LiveModelsTest(unittest.TestCase):
    def test_neighborhood_bound_and_cycles(self):
        graph = {i: {'preds': [i-1], 'succs': [(i+1)%200]} for i in range(200)}
        self.assertEqual(len(neighborhood(graph, 50, 32)), 32)
        self.assertEqual(neighborhood(graph, 999), [])

    def test_measured_overlap_and_touching_boundaries(self):
        events = [[0, 100, 20, 'a', 1], [1, 110, 20, 'b', 2],
                  [2, 130, 10, 'b', 3], [3, 0, 0, '', 4]]
        self.assertEqual(trace_stats(events), dict(span=40, work=50, threads=2, peak=2))
        self.assertEqual(trace_stats([])['threads'], 0)
        self.assertEqual(trace_stats([[0, 1, 1, 'a', 1], [1, 2, 1, 'b', 2]])['peak'], 1)

    def test_export_preserves_thread_and_graph_identity(self):
        trace = chrome_trace({9: {'label':'arm', 'kind':'Solve'}},
             {'trace': [[9, 50, 12, 'worker7', 1]], 'generation':'5', 'graph_key':'epoch3'})
        event = trace['traceEvents'][0]
        self.assertEqual((event['tid'], event['ts'], event['dur']), ('worker7', 50, 12))
        self.assertEqual(event['args']['graph_key'], 'epoch3')
        self.assertEqual(event['name'], 'arm')

class FakeTransport:
    def __init__(self):
        self.calls, self.recordings = [], []
        self.key, self.generation, self.active = 'g1', '1', True

    def record(self, *args):
        self.recordings.append(args)
        return 1

    def snapshot(self, stage, rig, graph, generation):
        self.calls.append((stage, rig, graph, generation))
        if not self.active:
            return dict(active=False, rigs=[])
        if not rig:
            return dict(active=False, rigs=['/Rig'])
        result = dict(active=True, rigs=['/Rig'], graph_key=self.key,
                      generation=self.generation, recording=False)
        if graph != self.key:
            result['graph'] = [dict(step=0, preds=[], succs=[], label='solve', kind='Solve')]
        if graph != self.key or generation != self.generation:
            result['trace'] = [[0, 100, 10, 'worker', 1]]
        return result


class LiveSessionTest(unittest.TestCase):
    def test_incremental_reads_epoch_reset_and_close(self):
        from rigexec_viz.session import LiveSession
        transport = FakeTransport()
        session = LiveSession(None, transport=transport)
        session.max_frames = 4
        session.sample(42)
        self.assertEqual(session.rig, '/Rig')
        self.assertEqual(len(session.graph), 1)
        session.sample(42)
        self.assertEqual(transport.calls[-1], (42, '/Rig', 'g1', '1'))
        self.assertEqual(len(session.history), 1)
        for i in range(2, 10):
            transport.generation = str(i)
            session.sample(42)
        self.assertEqual(len(session.history), 4)
        transport.key = 'g2'
        session.sample(42)
        self.assertEqual(len(session.history), 1)
        session.sample(43)
        self.assertIn((42, b'/Rig', 0), transport.recordings)
        session.close()
        self.assertEqual(transport.recordings[-1], (43, b'/Rig', 0))
        transport.active = False
        session.sample(43)
        self.assertFalse(session.graph)
        self.assertFalse(session.history)

    def test_other_thread_cannot_access_live_evaluator(self):
        from rigexec_viz.session import LiveSession
        session = LiveSession(None, transport=FakeTransport())
        session.owner = -1
        with self.assertRaises(RuntimeError):
            session.sample(42)

class OperationPhasesTest(unittest.TestCase):
    def test_phases_extend_each_op_from_memo_to_publication(self):
        from rigexec_viz.session import timeline_events, op_extent, frame_extent, trace_phases, held_time
        frame = dict(generation='4', graph_key='g', time=12,
                     trace=[[3, 100, 20, 'a', 1], [5, 130, 10, 'a', 2], [6, 0, 0, '', 3]],
                     trace_phases=[[4, 6], [2, 30], [0, 0]])
        events = timeline_events([frame])
        self.assertEqual(events[0], [3, 100, 20, 'a', 1, 12, '4', 4, 6])
        self.assertEqual(op_extent(events[0]), (96, 126))
        self.assertEqual(op_extent(events[1]), (128, 170))
        self.assertEqual(frame_extent(frame), (96, 170))
        stats = trace_stats(events)
        self.assertEqual((stats['span'], stats['work'], held_time(events)), (40, 30, 72))
        self.assertEqual(held_time([[3, 100, 20, 'a', 1]]), 20)
        exported = chrome_trace({}, frame)['traceEvents']
        self.assertEqual((exported[0]['ts'], exported[0]['dur']), (100, 20))
        self.assertEqual((exported[0]['args']['memo_us'], exported[0]['args']['publish_us']), (4, 6))
        markers = chrome_trace({}, {'frames': [frame]})['traceEvents']
        self.assertEqual([(e['ts'], e['dur']) for e in markers if e['cat'] == 'frame'], [(96, 74)])
        # A host without phases, or with misaligned rows, draws bodies only.
        older = {k: v for k, v in frame.items() if k != 'trace_phases'}
        misaligned = dict(frame, trace_phases=[[1, 1]])
        for case in (older, misaligned):
            self.assertEqual(trace_phases(case), [(0, 0)]*3)
            self.assertEqual(op_extent(timeline_events([case])[0]), (100, 120))
            self.assertEqual(frame_extent(case), (100, 140))
        self.assertNotIn('memo_us', chrome_trace({}, older)['traceEvents'][0]['args'])
        self.assertEqual(op_extent([3, 100, 20, 'a', 1]), (100, 120))


class MultiFrameTraceTest(unittest.TestCase):
    def test_export_keeps_frames_and_elapsed_gaps(self):
        frames = [dict(generation=str(i), graph_key='g', time=10+i,
                       trace=[[7, start, 20, 'worker', 1]])
                  for i, start in enumerate((100, 1000, 3000))]
        result = chrome_trace({7: {'label': 'solve', 'kind': 'Solve'}}, {'frames': frames})
        ops = [e for e in result['traceEvents'] if e['cat'] != 'frame']
        markers = [e for e in result['traceEvents'] if e['cat'] == 'frame']
        self.assertEqual([e['ts'] for e in ops], [100, 1000, 3000])
        self.assertEqual([e['args']['frame'] for e in ops], [10, 11, 12])
        self.assertEqual(len(markers), 3)
