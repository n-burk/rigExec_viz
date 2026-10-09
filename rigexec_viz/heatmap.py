"""Measured operation-body costs for one observed evaluator generation."""
import math


COLORS = ('#3266ad', '#328ba8', '#35ad98', '#81bd68',
          '#cfcb50', '#efad43', '#ee733b', '#df3838')


def operation_costs(events):
    """Ignore untimed operations; repeated step records contribute body time."""
    costs = {}
    for step, start, duration, thread, *_ in events:
        if start and thread and math.isfinite(duration) and duration >= 0:
            node_id = 'step:%d' % step
            costs[node_id] = costs.get(node_id, 0) + duration
    return costs


def color_bucket(duration, maximum):
    """Log scale preserves small costs across large timing ranges."""
    if maximum <= 0:
        return 0
    return min(len(COLORS)-1, max(0, int(
        math.log1p(duration)/math.log1p(maximum)*(len(COLORS)-1))))
