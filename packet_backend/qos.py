"""Scenario-level QoS configuration; targets are experimental, not universal guarantees."""
from copy import deepcopy
import math

CLASSES = ('CONTROL', 'REALTIME', 'BULK')
DEFAULTS = {
    'scheduler': 'drr',
    'weights': {'CONTROL': 4, 'REALTIME': 2, 'BULK': 1},
    'quantum_bytes': 1500,
    'targets': {
        'CONTROL': {'deadline_s': 0.05},
        'REALTIME': {'deadline_s': 0.1},
        'BULK': {'min_goodput_bps': 20000, 'starvation_s': 0.25},
    },
}


def number(value, name, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be positive and finite')
    if integer and (not isinstance(value, int) or value > 1000000):
        raise ValueError(f'{name} must be a positive integer at most 1000000')
    return value


def normalize(config):
    """Missing QoS preserves the Phase 2 FIFO behavior."""
    if config is None:
        return None
    if not isinstance(config, dict) or set(config)-set(DEFAULTS):
        raise ValueError('Unknown QoS configuration fields')
    qos = deepcopy(DEFAULTS)
    for key, value in config.items():
        if key == 'targets':
            if not isinstance(value, dict) or set(value)-set(CLASSES):
                raise ValueError('Unknown target class')
            for name, fields in value.items():
                if not isinstance(fields, dict) or set(fields)-set(qos['targets'][name]):
                    raise ValueError(f'Unknown {name} target fields')
                qos['targets'][name].update(fields)
        else:
            qos[key] = deepcopy(value)
    if qos['scheduler'] != 'drr':
        raise ValueError('Phase 3 supports the drr scheduler')
    if not isinstance(qos['weights'], dict) or set(qos['weights']) != set(CLASSES):
        raise ValueError('All three class weights are required')
    for name, weight in qos['weights'].items():
        number(weight, f'{name} weight', integer=True)
    number(qos['quantum_bytes'], 'quantum_bytes', integer=True)
    for name, fields in qos['targets'].items():
        for field, value in fields.items():
            number(value, f'{name} {field}')
    return qos


def classify(flow, qos):
    name = flow.get('flow_type', 'BULK')
    if not isinstance(name, str):
        raise ValueError('flow_type must be a string')
    name = name.upper()
    if name == 'STREAMING':
        name = 'REALTIME'
    if name not in CLASSES:
        raise ValueError(f'Unknown flow_type {name}')
    targets = qos['targets'][name] if qos else {}
    deadline = flow.get('deadline_s', targets.get('deadline_s'))
    if deadline is not None:
        number(deadline, 'deadline_s')
    minimum = flow.get('min_goodput_bps', targets.get('min_goodput_bps'))
    if minimum is not None:
        number(minimum, 'min_goodput_bps')
    return {'flow_type': name, 'class_id': CLASSES.index(name), 'deadline_s': deadline,
            'min_goodput_bps': minimum, 'starvation_s': targets.get('starvation_s')}
