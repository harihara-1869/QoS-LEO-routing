"""Seeded Phase 3 fixtures with shared bottlenecks and a longer alternate path."""
import random

CASES = ('low', 'normal', 'burst', 'hotspot', 'overload')


def workload(case, seed=7):
    if case not in CASES:
        raise ValueError(f'Unknown workload {case}')
    rng = random.Random(seed)
    config = {'schema_version': 1, 'seed': seed, 'duration_s': 4,
              'control_interval_s': .05, 'qos': {},
              'network': {'capacity_bps': 1000000, 'queue_packets': 60},
              'topology': {'nodes': ['source', 'short', 'alternate', 'sink', 'hotspot'],
                           'snapshots': [{'time_s': 0, 'links': [
                               {'a':'source','b':'short','delay_s':.002,'capacity_bps':10000000},
                               {'a':'short','b':'sink','delay_s':.002},
                               {'a':'source','b':'alternate','delay_s':.01,'capacity_bps':10000000},
                               {'a':'alternate','b':'sink','delay_s':.01},
                               {'a':'hotspot','b':'short','delay_s':.001,'capacity_bps':10000000}]}]},
              'flows': []}
    scale = {'low':.1, 'normal':.75, 'burst':.5, 'hotspot':.5, 'overload':4}[case]
    def add(name, rate, size, start=.1, end=3.5, source='source'):
        config['flows'].append({'flow_id':len(config['flows'])+1, 'flow_type':name,
                                'protocol':'udp', 'src':source, 'dst':'sink',
                                'start_time':round(start+rng.uniform(0,.005),6), 'end_time':end,
                                'packet_size_bytes':size, 'data_rate_bps':rate})
    for name,rate,size in [('CONTROL',80000,128),('REALTIME',320000,800),('BULK',300000,1200),('BULK',300000,1200)]:
        add(name,rate*scale,size)
    if case == 'burst':
        for start in (1,2):
            add('CONTROL',1000000,128,start,start+.25)
            add('REALTIME',1500000,800,start,start+.25)
    if case == 'hotspot':
        add('BULK',1800000,1200,.5,3.2,'hotspot')
    return config
