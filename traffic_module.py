import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum, auto
import heapq

# Flow definition

class FlowType(Enum):
    BULK = auto()
    REALTIME = auto()
    STREAMING = REALTIME  # backwards-compatible name
    CONTROL = auto()

class FlowState(Enum):
    WAITING = auto()
    ACTIVE = auto()
    COMPLETED = auto()

@dataclass
class Flow:
    flow_id: int
    src: str
    dst: str

    start_time: float
    end_time: float

    data_rate_bps: float
    packet_size_bytes: int = 1500

    flow_type: FlowType = FlowType.BULK
    flow_state: FlowState = FlowState.WAITING

    bytes_generated: int = 0
    bytes_delivered: int = 0
    packets_generated: int = 0

    def is_active(self, t: float) -> bool:
        return self.start_time <= t < self.end_time
    
    def is_finished(self, t: float) -> bool:
        return t >= self.end_time

# Packet definition

class PacketType(Enum):
    DATA = auto()
    CONTROL = auto()

@dataclass
class Packet:
    packet_id: int
    flow_id: int
    src: str
    dst: str

    size_bytes: int
    creation_time: float

    packet_type: PacketType = PacketType.DATA
    
    delivered: bool = False
    delivery_time: Optional[float] = None

# Traffic Module

class TrafficModule:
    
    def __init__(self, network_module):
        self.network = network_module
        self.flows: Dict[int, Flow] = {}
        self.active_flows: set[int] = set()
        self._packet_counter: int = 0

    def on_flow_start(self, time: float, flow_id: int):
        flow = self.flows.get(flow_id)
        if flow is not None and flow.is_active(time):
            flow.flow_state = FlowState.ACTIVE
            self.active_flows.add(flow_id)

    def on_packet_generation(self, time: float, interval: float):
        """Generate bytes earned in [time-interval, time); retain fractional packets."""
        if interval <= 0 or not math.isfinite(interval):
            raise ValueError("Generation interval must be positive and finite")
        for flow_id, flow in sorted(self.flows.items()):
            elapsed = max(0.0, min(time, flow.end_time) - max(time - interval, flow.start_time))
            if flow.packet_size_bytes <= 0 or flow.data_rate_bps < 0:
                raise ValueError("Invalid packet size or data rate")
            earned = getattr(flow, "_pending_bytes", 0.0) + flow.data_rate_bps * elapsed / 8
            count = int((earned + 1e-9) // flow.packet_size_bytes)
            flow._pending_bytes = earned - count * flow.packet_size_bytes
            for _ in range(count):
                packet = Packet(self._packet_counter, flow_id, flow.src, flow.dst,
                                flow.packet_size_bytes, time)
                self._packet_counter += 1
                flow.packets_generated += 1
                flow.bytes_generated += packet.size_bytes
                self.network.inject_packet(packet)
            flow.flow_state = (FlowState.COMPLETED if flow.is_finished(time) else
                               FlowState.ACTIVE if flow.is_active(time) else FlowState.WAITING)
            if flow.flow_state == FlowState.ACTIVE:
                self.active_flows.add(flow_id)
            else:
                self.active_flows.discard(flow_id)

    def on_packet_delivered(self, packet: Packet, time: float):
        packet.delivered = True
        packet.delivery_time = time

        flow = self.flows.get(packet.flow_id)
        if flow:
            flow.bytes_delivered += packet.size_bytes