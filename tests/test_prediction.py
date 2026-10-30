"""Causal forecast arithmetic, routing safeguards and packet-engine integration."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from packet_backend.build import ROOT
from packet_backend.controller import validate_routes
from packet_backend.prediction import OrbitalForecaster, QueueForecaster, settings, unknown_links
from packet_backend.prediction_metrics import summarize_predictions
from packet_backend.predictive import PredictivePolicy
from packet_backend.qos import CLASSES, normalize
from packet_backend.workloads import workload
from run_packet_scenario import run


def observation():
    edges = [{'id':i, 'a':a, 'b':b, 'delay_s':delay, 'capacity_bps':1000000, 'queue_packets':60}
             for i,(a,b,delay) in enumerate([(0,1,.001),(1,3,.001),(0,2,.005),(2,3,.005)])]
    queues = [{'link_id':e['id'], 'direction':d, 'packets':0,'bytes':0,
               'classes':{name:dict(packets=0,bytes=0,arrived_bytes=0,served_bytes=0,rejected_bytes=0) for name in CLASSES}}
              for e in edges for d in (0,1)]
    return {'time_s':0, 'nodes':list('abcd'), 'links':edges, 'queues':queues,
            'destinations':[3], 'qos':normalize({}), 'mtu_bytes':9000,
            'active_flows':[dict(id=1,src=0,dst=3,class_id=0,flow_type='CONTROL',protocol='udp',size=128,
                                 deadline_s=.05,min_goodput_bps=None)]}


class ForecastUnitTests(unittest.TestCase):
    def test_forecast_configuration_validation(self):
        for key,value in [('ewma_alpha',2),('queue_horizon_s',0),('orbital_step_s',float('nan')),
                          ('change_penalty_s',True),('link_guard_s',-1),('unknown',1)]:
            with self.subTest(key=key),self.assertRaises(ValueError): settings({key:value})
        self.assertEqual(settings({'change_penalty_s':0})['change_penalty_s'],0)

    def test_cold_start_rate_arithmetic_and_link_reset(self):
        obs=observation();obs['links'][0]['capacity_bps']=8000
        queue=obs['queues'][0]['classes']['CONTROL'];queue.update(bytes=200,packets=2)
        model=QueueForecaster(settings({'ewma_alpha':1}))
        first=model.predict(obs)[0]
        self.assertTrue(first['warmup'])
        self.assertEqual(first['classes']['CONTROL']['predicted_bytes'],200)
        obs['time_s']=.1;queue.update(arrived_bytes=100,served_bytes=100)
        second=model.predict(obs)[0]['classes']['CONTROL']
        self.assertEqual(second['arrival_bytes_s'],1000)
        self.assertEqual(second['predicted_bytes'],200)
        obs['time_s']=.2;queue.update(bytes=300,arrived_bytes=300,served_bytes=200)
        third=model.predict(obs)[0]['classes']['CONTROL']
        self.assertAlmostEqual(third['predicted_bytes'],400)
        removed=obs['links'].pop(0);obs['time_s']=.3;model.predict(obs)
        obs['links'].insert(0,removed);obs['time_s']=.4
        self.assertTrue(model.predict(obs)[0]['warmup'])

    def test_forecast_scoring_arithmetic_and_censoring(self):
        first=observation();model=QueueForecaster(settings())
        first['prediction']={'queue_forecasts':model.predict(first)}
        second=observation();second['time_s']=.1
        second['queues'][0]['classes']['CONTROL']['bytes']=80
        result=summarize_predictions([first,second],settings())
        self.assertEqual(result['queue']['samples'],24)
        self.assertAlmostEqual(result['queue']['mae_bytes'],80/24)
        self.assertEqual(result['queue']['busy_mae_bytes'],80)
        missing=summarize_predictions([first],settings())
        self.assertEqual(missing['queue']['samples'],0)
        self.assertIsNone(missing['queue']['mae_bytes'])

    def test_unknown_link_lifetime_is_not_an_infinite_promise(self):
        self.assertTrue(all(x['lifetime_lower_s'] is None and not x['samples'] for x in unknown_links(observation())))
        policy=PredictivePolicy('lifetime',settings())
        validate_routes(policy(observation()),observation())
        self.assertEqual(policy.last_diagnostics['fallbacks'][0]['reasons'],['link_forecast_unavailable'])

    def test_urgent_classes_avoid_bulk_only_queue_pressure(self):
        obs=observation();q=obs['queues'][0]['classes']['BULK'];q.update(bytes=20000,packets=20)
        policy=PredictivePolicy('qos_current',settings())
        routes=policy(obs)
        self.assertEqual(routes[0,0,3],1)
        self.assertEqual(routes[2,0,3],2)
        validate_routes(routes,obs)

    def test_link_prediction_avoids_short_lived_edge(self):
        class Contacts:
            def predict(self, obs):
                result=unknown_links(obs)
                for edge in result:
                    edge['lifetime_lower_s']=.01 if edge['link_id']==0 else 10
                return result
        policy=PredictivePolicy('predictive',settings(),Contacts())
        obs=observation();routes=policy(obs)
        self.assertEqual(routes[0,0,3],2)
        validate_routes(routes,obs)

    def test_queue_growth_changes_route_before_current_backlog_does(self):
        obs=observation();config=settings({'ewma_alpha':1})
        current=PredictivePolicy('qos_current',config)
        predicted=PredictivePolicy('queue_forecast',config)
        self.assertEqual(current(obs)[0,0,3],1)
        self.assertEqual(predicted(obs)[0,0,3],1)
        obs['time_s']=.005
        obs['queues'][0]['classes']['CONTROL'].update(bytes=375,packets=3,arrived_bytes=1000,served_bytes=625)
        self.assertEqual(current(obs)[0,0,3],1)
        self.assertEqual(predicted(obs)[0,0,3],2)
        self.assertGreater(predicted.last_diagnostics['queue_forecasts'][0]['classes']['CONTROL']['predicted_bytes'],375)

    def test_switch_penalty_and_deadline_override(self):
        obs=observation();policy=PredictivePolicy('qos_current',settings({'change_penalty_s':.02}))
        self.assertEqual(policy(obs)[0,0,3],1)
        obs['time_s']=.05
        obs['links'][0]['delay_s']=.009
        obs['links'][1]['delay_s']=.009
        self.assertEqual(policy(obs)[0,0,3],1)  # Avoid switching for a small improvement.
        obs['active_flows'][0]['deadline_s']=.015
        self.assertEqual(policy(obs)[0,0,3],2)  # Deadline overrides switching cost.

    def test_impossible_deadline_and_bulk_floor_are_logged(self):
        obs=observation();obs['active_flows'][0]['deadline_s']=1e-6
        obs['active_flows'].append(dict(id=2,src=0,dst=3,class_id=2,flow_type='BULK',protocol='udp',size=1200,
                                       deadline_s=None,min_goodput_bps=2000000))
        policy=PredictivePolicy('predictive',settings())
        routes=policy(obs);validate_routes(routes,obs)
        self.assertEqual(len(policy.last_diagnostics['fallbacks']),2)
        self.assertTrue(policy.last_diagnostics['decisions'][0]['deadline_at_risk'])
        self.assertTrue(policy.last_diagnostics['decisions'][1]['bulk_floor_at_risk'])

    def test_class_loop_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'forwarding loop'):
            validate_routes({(0,0,3):1,(0,1,3):0},observation())

    def test_orbital_lifetime_brackets_actual_elevation_loss(self):
        from setup import generate_omm_csv, get_satellite_data
        from skyfield.api import load, wgs84
        with tempfile.TemporaryDirectory() as temp:
            filename=Path(temp)/'orbit.csv'
            generate_omm_csv(filename,1,sats_per_plane=1)
            satellites=get_satellite_data(csv_file=filename)
            point=wgs84.subpoint(satellites[0].at(load.timescale().utc(2025,1,1)))
            gs=[['ground',point.latitude.degrees,point.longitude.degrees,0]]
            config=settings({'orbital_horizon_s':1000,'orbital_step_s':50})
            model=OrbitalForecaster(satellites,'2025-01-01T00:00:00+00:00',{},gs,config)
            obs={'time_s':0,'nodes':['SAT-00-00','ground'],
                 'links':[dict(id=0,a=0,b=1,delay_s=.002)]}
            forecast=model.predict(obs)[0]
            self.assertIsNotNone(forecast['lifetime_upper_s'])
            ground=wgs84.latlon(gs[0][1],gs[0][2])
            before=(satellites[0]-ground).at(model.model.get_sim_time(forecast['lifetime_lower_s'])).altaz()[0].degrees
            after=(satellites[0]-ground).at(model.model.get_sim_time(forecast['lifetime_upper_s'])).altaz()[0].degrees
            self.assertGreaterEqual(before,5)
            self.assertLess(after,5)
            self.assertEqual(forecast['lifetime_upper_s']-forecast['lifetime_lower_s'],50)
            self.assertEqual(model.predict(obs)[0],forecast)


@unittest.skipUnless(shutil.which('g++') and Path(os.environ.get('LEO_NS3_PYTHON',str(ROOT/'.venv-ns3/bin/python'))).exists(),
                     'Install the pinned ns-3 environment and g++')
class PredictiveEngineTests(unittest.TestCase):
    def simulate(self, config, policy='predictive'):
        with tempfile.TemporaryDirectory() as temp:
            result=run(config,temp,policy=policy)
            self.assertEqual((Path(temp)/'engine.stderr').read_text(),'')
            control=json.loads((Path(temp)/'control.json').read_text())
            return result,control

    def test_real_packets_follow_distinct_class_tables(self):
        config=workload('low');config['prediction']={}
        config['duration_s']=.3
        for f in config['flows']:f['end_time']=.25
        def split(obs):
            # source(0) uses short(1) for urgent, alternate(2) for Bulk; sink is 3.
            routes={(c,1,3):3 for c in range(3)}
            routes.update({(c,2,3):3 for c in range(3)})
            routes.update({(c,0,3):2 if c==2 else 1 for c in range(3)})
            return routes
        result,_=self.simulate(config,split)
        for packet in result['udp_packets']:
            self.assertEqual(packet['status'],'delivered')
            self.assertEqual(packet['path'],['source','short' if packet['flow_id']<3 else 'alternate','sink'])
        self.assertEqual(result['schema_version'],4)

    def test_counters_include_overflow_and_forecasts_are_scored(self):
        config=workload('overload');config['prediction']={}
        result,control=self.simulate(config)
        self.assertGreater(result['prediction']['queue']['samples'],0)
        self.assertGreater(result['prediction']['queue']['busy_samples'],0)
        self.assertTrue(any(v['rejected_bytes'] for o in control for q in o['queues'] for v in q['classes'].values()))
        final=control[-1]
        for queue in final['queues']:
            for values in queue['classes'].values():
                self.assertEqual(values['arrived_bytes']-values['served_bytes']-values['rejected_bytes'],values['bytes'])

    def test_future_workload_and_topology_suffix_cannot_change_prefix(self):
        first=workload('normal');first['prediction']={}
        second=deepcopy(first)
        second['flows'].append({**second['flows'][0],'flow_id':99,'start_time':2,'data_rate_bps':10000000})
        second['flows'].append({**second['flows'][0],'flow_id':100,'start_time':0,'data_rate_bps':0})
        second['topology']['snapshots'].append({'time_s':2,'links':[]})
        _,a=self.simulate(first);_,b=self.simulate(second)
        self.assertEqual([o for o in a if o['time_s']<2],[o for o in b if o['time_s']<2])
        for obs in a:
            for flow in obs['active_flows']:
                self.assertNotIn('rate',flow)
                self.assertNotIn('end',flow)
            self.assertNotIn('snapshots',obs)

    def test_stateful_policy_resets_between_runs(self):
        config=workload('burst');config['prediction']={}
        policy=PredictivePolicy('predictive',settings())
        a,_=self.simulate(config,policy);b,_=self.simulate(config,policy)
        self.assertEqual(a,b)

    def test_tcp_bulk_survives_class_routing_and_failure(self):
        config=json.loads((ROOT/'scenarios/phase2/tcp_reroute.json').read_text())
        config.update(qos={},prediction={})
        result,_=self.simulate(config)
        self.assertTrue(result['flows'][0]['complete'])
        self.assertGreater(result['flows'][0]['route_changes'],0)

    def test_orbital_forecasts_integrate_with_backend(self):
        config=json.loads((ROOT/'scenarios/packet_baseline.json').read_text())
        config.update(qos={},prediction={'queue_horizon_s':1,'orbital_step_s':1,'orbital_horizon_s':2})
        config['flows'].append({**config['flows'][0], 'flow_id':2, 'flow_type':'CONTROL', 'packet_size_bytes':128, 'data_rate_bps':1024})
        result,control=self.simulate(config)
        self.assertGreater(result['prediction']['orbital']['samples'],0)
        self.assertEqual(result['prediction']['orbital']['availability_accuracy'],1)
        self.assertEqual(result['flows'][0]['delivered'],10)
        self.assertTrue(any(p['source']=='orbital_model' for o in control for p in o['prediction']['link_forecasts']))


if __name__=='__main__':
    unittest.main()
