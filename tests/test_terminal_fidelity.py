"""Terminal lifecycle, time resolution, gateway restrictions and reference vectors."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np
from skyfield.api import EarthSatellite,load
from skyfield.sgp4lib import TEME

from logic_module import LogicalConfig,LinkType
from terminal_model import TerminalState
from packet_backend.controller import shortest_routes,validate_routes,resolve_policy
from packet_backend.orbital_workloads import orbital_workload
from packet_backend.scenario import prepare
from fidelity_experiments import scaled_scenario


def node(name):
    return SimpleNamespace(sat=SimpleNamespace(name=name))


class TerminalTests(unittest.TestCase):
    def test_ground_hysteresis_dwell_and_satellite_beam_budget(self):
        cfg=LogicalConfig(ground_links_per_station=1,ground_beams_per_satellite=1,
                          ground_hysteresis_deg=2,ground_min_dwell_s=1)
        t=TerminalState(cfg);a,b=node('a'),node('b')
        self.assertEqual(t.select_ground({'GS':[(20,'a',a),(19,'b',b)]},0)[0][0],a)
        self.assertEqual(t.select_ground({'GS':[(20,'a',a),(30,'b',b)]},.5)[0][0],a)
        self.assertEqual(t.select_ground({'GS':[(20,'a',a),(21,'b',b)]},1)[0][0],a)
        self.assertEqual(t.select_ground({'GS':[(20,'a',a),(23,'b',b)]},1.1)[0][0],b)
        chosen=t.select_ground({'GS':[(25,'a',a)],'OTHER':[(24,'a',a)]},2)
        self.assertEqual(len(chosen),1)

    def test_isl_cap_includes_optional_optical_links(self):
        class Node:
            def __init__(self,name):self.sat=SimpleNamespace(name=name)
        a,b,c=map(Node,'abc');t=TerminalState(LogicalConfig(isl_terminals_per_satellite=1))
        result=t.admit([(LinkType.ISL_INTRA,a,b),(LinkType.IOL,a,c)],0)
        self.assertEqual(len(result),1)

    def test_lifecycle_with_hashable_nodes(self):
        class Node:
            def __init__(self,name):self.sat=SimpleNamespace(name=name)
        t=TerminalState(LogicalConfig(ground_acquisition_s=.15,initial_links_ready=False))
        edge=(LinkType.UDL,Node('sat'),'GS')
        self.assertFalse(t.admit([edge],0));self.assertFalse(t.admit([edge],.1))
        self.assertIn(edge,t.admit([edge],.15))
        t.admit([],.2)
        self.assertFalse(t.admit([edge],.3));self.assertIn(edge,t.admit([edge],.45))
        with self.assertRaises(ValueError):t.admit([edge],.1)

    def test_validation(self):
        from logic_module import LogicalTopology
        for key,value in [('ground_acquisition_s',-1),('ground_hysteresis_deg',float('nan')),
                          ('ground_beams_per_satellite',0),('initial_links_ready',1)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                LogicalTopology([SimpleNamespace(name='sat',model=SimpleNamespace(inclo=0,nodeo=0,mo=0))],LogicalConfig(ground_links_per_station=1,**{key:value}),[])


class ScenarioFidelityTests(unittest.TestCase):
    def test_rate_sensitivity_preserves_physics_and_makes_demand_mode_explicit(self):
        base=orbital_workload('normal');fixed=scaled_scenario(base,2);matched=scaled_scenario(base,2,True)
        self.assertEqual(fixed['flows'],base['flows'])
        self.assertEqual(matched['flows'][0]['data_rate_bps'],base['flows'][0]['data_rate_bps']*2)
        for key in ('epoch','orbital_start_s','step_s','control_interval_s','qos'):
            self.assertEqual(base[key],fixed[key])
        self.assertEqual(base['links']['ground_capacity_bps']*2,fixed['links']['ground_capacity_bps'])

    def test_bursts_are_observed_even_in_shortened_runs(self):
        for duration in (1.1,3,5):
            cfg=orbital_workload('burst',duration=duration)
            ticks=np.arange(0,duration,cfg['control_interval_s'])
            for flow in cfg['flows'][5:]:
                self.assertTrue(any(flow['start_time']<=t<flow['end_time'] for t in ticks))

    def test_attachments_change_and_forecast_replays_terminal_history(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=orbital_workload('normal');p=Path(temp)
            plan=prepare(cfg,p,class_routing=True)
            physical=[s for s in plan['snapshots'] if abs(s['time_s']/.1-round(s['time_s']/.1))<1e-6]
            sets=[{e['id'] for e in s['links']} for s in physical]
            self.assertTrue(any(a!=b for a,b in zip(sets,sets[1:])))
            orbital=resolve_policy('predictive',plan,p).orbital
            for snapshot in plan['snapshots']:
                orbital.geometry(snapshot['time_s']+.5)  # Future evaluation must not corrupt earlier state.
                prediction=orbital.geometry(snapshot['time_s'])
                actual={tuple(sorted((plan['nodes'][plan['links'][e['id']]['a']],plan['nodes'][plan['links'][e['id']]['b']]))):e['delay_s'] for e in snapshot['links']}
                self.assertEqual(set(prediction),set(actual))
                for pair in actual:self.assertAlmostEqual(prediction[pair],actual[pair],places=12)

    def test_gateway_transit_excluded_but_gateway_origin_allowed(self):
        obs={'nodes':['source','gateway','alternate','dest'],'destinations':[3], 'queues':[],
             'non_transit_nodes':[1], 'links':[{'id':i,'a':a,'b':b,'delay_s':delay} for i,(a,b,delay) in enumerate([(0,1,.001),(1,3,.001),(0,2,.01),(2,3,.01)])]}
        routes=shortest_routes(obs)
        self.assertEqual(routes[0,3],2);self.assertEqual(routes[1,3],3)
        validate_routes(routes,obs)
        with self.assertRaisesRegex(ValueError,'non-transit'):
            validate_routes({(0,3):1,(1,3):3},obs)

    def test_vallado_teme_position_and_velocity_vectors(self):
        fixture=json.loads((Path(__file__).parent/'data/vallado_00005.json').read_text())
        ts=load.timescale();sat=EarthSatellite(*fixture['tle'],name='Vallado 00005',ts=ts)
        for vector in fixture['vectors']:
            t=ts.tt_jd(sat.epoch.whole,sat.epoch.tt_fraction+vector['minutes']/1440)
            position,velocity=sat.at(t).frame_xyz_and_velocity(TEME)
            np.testing.assert_allclose(position.km,vector['position_km'],atol=1e-3,rtol=0)
            np.testing.assert_allclose(velocity.km_per_s,vector['velocity_km_s'],atol=1e-6,rtol=0)
