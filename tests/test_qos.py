"""Phase 3 service semantics, directional routing and real ns-3 integration."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from packet_backend.build import ROOT
from packet_backend.controller import congestion_routes, shortest_routes
from packet_backend.qos_metrics import deadlines, jain, service_gaps
from packet_backend.scenario import prepare
from packet_backend.workloads import workload
from run_packet_scenario import run
from compare_policies import compare


def single():
    return {'schema_version':1, 'duration_s':1, 'qos':{},
            'network':{'capacity_bps':1000000,'queue_packets':300},
            'topology':{'nodes':['a','b'],'snapshots':[{'time_s':0,'links':[{'a':'a','b':'b','delay_s':.001}]}]},
            'flows':[{'flow_id':1,'flow_type':'CONTROL','src':'a','dst':'b',
                      'start_time':.01,'end_time':.02,'packet_size_bytes':1000,'data_rate_bps':800000}]}


class QosUnitTests(unittest.TestCase):
    def test_deadline_boundary_loss_and_censoring(self):
        packets = [dict(status='delivered',delay_s=.05),dict(status='delivered',delay_s=.051),
                   dict(status='dropped'),dict(status='in_flight',created_s=.9),
                   dict(status='in_flight',created_s=.99)]
        result = deadlines(packets,.05,1)
        self.assertEqual([result[k] for k in ('on_time','late','dropped','overdue','pending_not_due')],[1]*5)
        self.assertEqual(result['success_ratio'],.25)
        self.assertEqual(result['success_ratio_lower_bound'],.2)

    def test_fairness_and_idle_exclusion(self):
        self.assertEqual(jain([10,10]),1)
        self.assertEqual(jain([10,0]),.5)
        self.assertIsNone(jain([0,0]))
        events = [dict(kind=kind,item=0,a=0,b=2,time_s=t,value=value) for kind,t,value in
                  [('class_queue',.1,1),('class_service',.2,100),('class_queue',.6,0),('class_queue',.9,1)]]
        result = service_gaps(events,1,.25)
        self.assertAlmostEqual(result['max_backlogged_service_gap_s'],.4)
        self.assertEqual(len(result['starvation_intervals']),1)
        self.assertEqual(result['starvation_intervals'][0]['start_s'],.2)

    def test_congestion_uses_forward_not_reverse_queue(self):
        obs = {'nodes':list('abcd'),'destinations':[3], 'queues':[{'link_id':0,'direction':0,'bytes':10000}],
               'links':[{'id':i,'a':a,'b':b,'delay_s':delay,'capacity_bps':1000000}
                        for i,(a,b,delay) in enumerate([(0,1,.001),(1,3,.001),(0,2,.005),(2,3,.005)])]}
        self.assertEqual(shortest_routes(obs)[0,3],1)
        self.assertEqual(congestion_routes(obs)[0,3],2)
        obs['queues'][0]['direction']=1
        self.assertEqual(congestion_routes(obs)[0,3],1)

    def test_seeded_workloads(self):
        self.assertEqual(workload('burst',7),workload('burst',7))
        self.assertNotEqual(workload('burst',7),workload('burst',8))
        for case in ('low','normal','burst','hotspot','overload'):
            saved=json.loads((ROOT/'scenarios/phase3'/f'{case}.json').read_text())
            self.assertEqual(workload(case),saved)

    def test_alias_control_ticks_and_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            config=single();config['flows'][0]['flow_type']='STREAMING';config['control_interval_s']=.3
            plan=prepare(config,Path(temp))
            self.assertEqual(plan['flows'][0]['flow_type'],'REALTIME')
            self.assertEqual(plan['flows'][0]['deadline_s'],.1)
            self.assertEqual(len(plan['snapshots']),4)
            config['control_interval_s']=.1
            config['topology']['snapshots'].append({'time_s':.3,'links':[]})
            plan=prepare(config,Path(temp))
            self.assertEqual(len(plan['snapshots']),10)
            self.assertEqual(plan['snapshots'][3]['links'],[])
            self.assertEqual(plan['snapshots'][4]['links'],[])
            for change in ('weight','queue','tcp','deadline','targets'):
                config=single()
                if change=='weight': config['qos']['weights']={'CONTROL':4,'REALTIME':2,'BULK':0}
                if change=='queue': config['network']['queue_packets']=2
                if change=='tcp': config['flows'][0].update(protocol='tcp',max_bytes=1000,data_rate_bps=0)
                if change=='deadline': config['flows'][0]['deadline_s']=float('nan')
                if change=='targets': config['qos']['targets']=[]
                with self.subTest(change=change),self.assertRaises(ValueError): prepare(config,Path(temp))


@unittest.skipUnless(shutil.which('g++') and Path(os.environ.get('LEO_NS3_PYTHON',str(ROOT/'.venv-ns3/bin/python'))).exists(),
                     'Install the pinned ns-3 environment and g++')
class QosEngineTests(unittest.TestCase):
    def simulate(self, config, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            result=run(config,temp,**kwargs)
            self.assertEqual((Path(temp)/'engine.stderr').read_text(),'')
            return result

    def test_weighted_bytes_and_bulk_service_under_saturation(self):
        config=single();config['duration_s']=.6;config['flows']=[]
        for i,(name,size) in enumerate([('CONTROL',100),('REALTIME',700),('BULK',1400)]):
            config['flows'].append(dict(flow_id=i,flow_type=name,src='a',dst='b',start_time=.001,
                                        end_time=.5,packet_size_bytes=size,data_rate_bps=10000000))
        result=self.simulate(config)
        service=[sum(e['value'] for e in result['events'] if e['kind']=='class_service' and e['b']==i and .1<e['time_s']<.45) for i in range(3)]
        self.assertAlmostEqual(service[0]/service[2],4,delta=.65)
        self.assertAlmostEqual(service[1]/service[2],2,delta=.4)
        self.assertLess(result['qos']['bulk_service']['max_backlogged_service_gap_s'],.1)
        self.assertFalse(result['qos']['bulk_service']['starvation_intervals'])
        self.assertTrue(all(f['delivered']>0 and f['dropped']>0 for f in result['flows']))
        for f in result['flows']:
            self.assertEqual(f['generated'],f['delivered']+f['dropped']+f['in_flight'])
        for c in range(3):
            counts=[e['value'] for e in result['events'] if e['kind']=='class_queue' and e['b']==c]
            self.assertEqual(max(counts),100)

    def test_live_class_observations_and_no_future_state(self):
        config=workload('overload');seen=[]
        def policy(obs):
            seen.append(obs)
            return congestion_routes(obs)
        self.simulate(config,policy=policy)
        self.assertTrue(any(q['classes']['BULK']['packets'] for obs in seen for q in obs['queues']))
        for obs in seen:
            self.assertNotIn('snapshots',obs)
            self.assertNotIn('flows',obs)
            for q in obs['queues']:
                self.assertEqual(q['bytes'],sum(c['bytes'] for c in q['classes'].values()))
                self.assertEqual(q['packets'],sum(c['packets'] for c in q['classes'].values()))

    def test_qos_preserves_link_failure_accounting(self):
        config=json.loads((ROOT/'scenarios/phase2/disappearing_link.json').read_text());config['qos']={}
        config['network']['queue_packets']=30
        result=self.simulate(config)
        reasons=result['flows'][0]['drop_reasons']
        self.assertGreater(reasons['link_down_queued'],0)
        self.assertGreater(reasons['link_down_in_flight'],0)
        self.assertGreater(reasons['no_route'],0)
        self.assertGreater(result['flows'][0]['delivered'],0)

    def test_tcp_is_bulk_and_completes(self):
        config=json.loads((ROOT/'scenarios/phase2/tcp_reno_clean.json').read_text());config['qos']={}
        result=self.simulate(config)
        self.assertTrue(result['flows'][0]['complete'])
        self.assertEqual(result['flows'][0]['flow_type'],'BULK')
        self.assertIsNone(result['flows'][0]['deadline'])
        self.assertTrue(all(e['b']==2 for e in result['events'] if e['kind']=='class_service'))

    def test_matched_comparison_and_repeatability(self):
        with tempfile.TemporaryDirectory() as temp:
            first=compare('burst',Path(temp)/'a');second=compare('burst',Path(temp)/'b')
            self.assertEqual(first,second)
            policies=first['policies']
            self.assertEqual(policies['propagation']['scenario_sha256'],policies['congestion']['scenario_sha256'])
            self.assertEqual(policies['propagation']['qos']['config'],policies['congestion']['qos']['config'])
            self.assertGreater(policies['congestion']['qos']['classes']['REALTIME']['delivered_bytes'],
                               policies['propagation']['qos']['classes']['REALTIME']['delivered_bytes'])
            with patch('compare_policies.run',side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError): compare('burst',Path(temp)/'a')
            self.assertFalse((Path(temp)/'a/comparison.json').exists())


if __name__=='__main__':
    unittest.main()
