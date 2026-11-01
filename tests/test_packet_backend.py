"""Independent arithmetic and failure/transport checks against the real ns-3 engine."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from packet_backend.build import ROOT, build_engine
from packet_backend.controller import shortest_routes
from packet_backend.scenario import prepare
from experiments.run import run


def fixture(name):
    return json.loads((ROOT/'scenarios/phase2'/f'{name}.json').read_text())


class ScenarioValidationTests(unittest.TestCase):
    def test_rejects_invalid_scenarios_before_backend(self):
        cases=[]
        for key,value in [('duration_s',float('nan')),('seed',True)]:
            c=fixture('single_link');c[key]=value;cases.append(c)
        c=fixture('single_link');c['flows'][0]['packet_size_bytes']=9000;cases.append(c)
        c=fixture('single_link');c['topology']['snapshots'][0]['links'][0]['delay_s']=-1;cases.append(c)
        c=fixture('single_link');c['topology']['nodes']=['a','a'];cases.append(c)
        c=fixture('tcp_reno_clean');c['flows'][0]['data_rate_bps']=100;cases.append(c)
        with tempfile.TemporaryDirectory() as temp:
            for config in cases:
                with self.subTest(config=config), self.assertRaises(ValueError):
                    prepare(config,Path(temp))


@unittest.skipUnless(shutil.which('g++') and Path(os.environ.get('LEO_NS3_PYTHON',str(ROOT/'.venv-ns3/bin/python'))).exists(),
                     'Install requirements/ns3.txt in .venv-ns3 and g++ to run packet integration tests')
class PacketBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=build_engine()

    def simulate(self,config,**kwargs):
        with tempfile.TemporaryDirectory() as temp:
            result=run(config,temp,**kwargs)
            self.assertEqual((Path(temp)/'engine.stderr').read_text(),'')
            return result

    def test_single_link_serialization_and_propagation(self):
        r=self.simulate(fixture('single_link'))
        p=r['udp_packets'][0]
        self.assertEqual(p['status'],'delivered')
        # 1000 payload + 8 UDP + 20 IPv4 + 2 PPP bytes.
        self.assertAlmostEqual(p['ended_s'],.01+1030*8/1000000+.005,places=9)
        self.assertEqual(p['path'],['a','b'])
        self.assertEqual(r['flows'][0]['goodput_bps'],8000)

    def test_short_path_and_hop_accounting(self):
        r=self.simulate(fixture('short_path'));p=r['udp_packets'][0]
        self.assertEqual(p['path'],['a','b','c'])
        self.assertAlmostEqual(p['delay_s'],2*1030*8/1e6+.005+.003,places=9)

    def test_bottleneck_serializes_packets(self):
        r=self.simulate(fixture('bottleneck'))
        first=.01+1030*8/8e6+.005+1030*8/1e6+.003
        self.assertEqual(r['flows'][0]['delivered'],3)
        for i,p in enumerate(r['udp_packets']):
            self.assertAlmostEqual(p['ended_s'],first+i*1030*8/1e6,places=9)
        self.assertGreater(r['udp_packets'][-1]['delay_s'],r['udp_packets'][0]['delay_s'])

    def test_overflow_and_accounting(self):
        r=self.simulate(fixture('overflow'));f=r['flows'][0]
        self.assertEqual((f['generated'],f['delivered'],f['dropped'],f['in_flight']),(100,15,85,0))
        self.assertEqual(f['drop_reasons'],{'queue_overflow':85})
        self.assertEqual(max(q['max_packets'] for q in r['queues']),2)
        self.assertTrue(any(q['mean_packets']>0 for q in r['queues']))

    def test_down_drops_waiting_and_in_flight_even_after_restore(self):
        r=self.simulate(fixture('disappearing_link'));p=r['udp_packets'];f=r['flows'][0]
        self.assertEqual(p[0]['reason'],'link_down_in_flight')
        self.assertEqual([x['reason'] for x in p[1:3]],['link_down_queued']*2)
        self.assertEqual(p[3]['reason'],'no_route') # down event wins same-time send
        self.assertEqual(p[8]['status'],'delivered')
        self.assertEqual(f['drop_reasons']['no_route'],5)
        self.assertEqual(f['route_changes'],2)
        self.assertEqual(sum(e['kind']=='link' and e['value']==0 for e in r['events']),1)

    def test_reroute_uses_alternate_path(self):
        r=self.simulate(fixture('reroute'))
        self.assertEqual(r['udp_packets'][0]['path'],['a','b','d'])
        self.assertEqual(r['udp_packets'][1]['path'],['a','c','d'])
        self.assertEqual(r['flows'][0]['delivered'],3)
        self.assertEqual(r['flows'][0]['route_changes'],1)

    def test_unreachable_and_horizon_are_distinct(self):
        c=fixture('single_link');c['topology']['snapshots'][0]['links']=[]
        r=self.simulate(c)
        self.assertEqual(r['flows'][0]['drop_reasons'],{'no_route':1})
        c=fixture('single_link');c['duration_s']=.02
        r=self.simulate(c)
        self.assertEqual((r['flows'][0]['dropped'],r['flows'][0]['in_flight']),(0,1))
        self.assertIsNone(r['udp_packets'][0]['delay_s'])

    def test_zero_rate_and_ttl_expiration(self):
        c=fixture('single_link');c['flows'][0]['data_rate_bps']=0
        self.assertEqual(self.simulate(c)['flows'][0]['generated'],0)
        c=fixture('short_path');c['network']['ttl']=1
        self.assertEqual(self.simulate(c)['flows'][0]['drop_reasons'],{'ttl_expired':1})

    def test_feedback_receives_queue_and_can_change_route(self):
        c=fixture('overflow');edge=c['topology']['snapshots'][0]['links']
        c['topology']['snapshots'] += [{'time_s':t,'links':edge} for t in (.012,.03,.06)]
        seen=[]
        def controller(obs):
            seen.append(deepcopy(obs))
            return {} if obs['time_s']==.03 else shortest_routes(obs)
        r=self.simulate(c,policy=controller)
        self.assertGreater(seen[1]['queues'][0]['packets'],0)
        self.assertNotIn('snapshots',seen[0])
        self.assertEqual(r['flows'][0]['drop_reasons']['no_route'],30)
        self.assertTrue(any(p['status']=='delivered' and p['created_s']>=.06 for p in r['udp_packets']))

    def test_loop_action_rejected(self):
        c=fixture('short_path')
        with self.assertRaisesRegex(ValueError,'forwarding loop'):
            self.simulate(c,policy=lambda obs:{(0,2):1,(1,2):0})

    def test_failed_rerun_cannot_leave_stale_success(self):
        with tempfile.TemporaryDirectory() as temp:
            run(fixture('single_link'),temp)
            invalid=fixture('single_link');invalid['duration_s']=-1
            with self.assertRaises(ValueError):
                run(invalid,temp)
            self.assertFalse((Path(temp)/'results.json').exists())
            self.assertFalse((Path(temp)/'manifest.json').exists())
            self.assertEqual(json.loads((Path(temp)/'status.json').read_text())['status'],'failed')

    def test_reset_and_repeatability(self):
        c=fixture('disappearing_link')
        self.assertEqual(self.simulate(c),self.simulate(c))

    def test_reno_reference_arithmetic(self):
        process=subprocess.run([str(self.binary),'--check-reno'],capture_output=True,text=True,check=True)
        self.assertEqual(process.stdout.strip(),'11000 5000 21000')
        self.assertEqual(process.stderr,'')

    def test_reno_loss_retransmits_reduces_window_and_completes(self):
        clean=self.simulate(fixture('tcp_reno_clean'))
        loss=self.simulate(fixture('tcp_reno_loss'))
        self.assertEqual(clean['flows'][0]['delivered_bytes'],100000)
        self.assertEqual(clean['flows'][0]['retransmissions'],0)
        self.assertEqual(loss['flows'][0]['delivered_bytes'],100000)
        self.assertGreater(loss['flows'][0]['retransmissions'],0)
        windows=[e for e in loss['events'] if e['kind']=='cwnd']
        self.assertTrue(any(e['value']>e['a'] for e in windows))
        self.assertTrue(any(e['value']<e['a'] for e in windows))
        self.assertTrue(any(e['kind']=='ssthresh' and e['value']<e['a'] for e in loss['events']))
        self.assertGreater(loss['flows'][0]['completion_delay_s'],clean['flows'][0]['completion_delay_s'])

    def test_tcp_recovers_across_route_change(self):
        r=self.simulate(fixture('tcp_reroute'))
        self.assertTrue(r['flows'][0]['complete'])
        self.assertEqual(r['flows'][0]['route_changes'],1)
        self.assertGreater(r['flows'][0]['retransmissions'],0)

    def test_orbital_topology_drives_packet_engine(self):
        c=json.loads((ROOT/'scenarios/packet_baseline.json').read_text())
        r=self.simulate(c)
        self.assertEqual(r['flows'][0]['delivered'],10)
        self.assertTrue(all(p['delay_s']>0 for p in r['udp_packets']))
        self.assertEqual(len(r['route_snapshots']),5)


if __name__=='__main__':
    unittest.main()
