"""Deterministic discrete-event clock; times are seconds from the scenario epoch."""
from dataclasses import dataclass, field
from typing import Callable
import heapq
import itertools
import math

@dataclass(order=True)
class Event:
    time: float
    priority: int
    sequence: int
    action: Callable = field(compare=False)
    args: tuple = field(compare=False, default=())

class ScheduleCore:
    def __init__(self):
        self.current_time = 0.0
        self._event_queue = []
        self._sequence = itertools.count()

    def schedule(self, time, priority, action, *args):
        if not math.isfinite(time) or time < self.current_time:
            raise ValueError("Event time must be finite and cannot precede the clock")
        heapq.heappush(self._event_queue, Event(time, priority, next(self._sequence), action, args))

    def run(self, until):
        if not math.isfinite(until) or until < self.current_time:
            raise ValueError("Run horizon must be finite and cannot precede the clock")
        while self._event_queue and self._event_queue[0].time <= until:
            event = heapq.heappop(self._event_queue)
            self.current_time = event.time
            event.action(self.current_time, *event.args)
        self.current_time = until
