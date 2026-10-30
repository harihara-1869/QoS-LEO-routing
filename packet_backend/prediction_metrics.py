"""Post-run forecast scoring. Realised future observations never enter policies."""
from collections import Counter

from packet_backend.qos import CLASSES


def mean(values):
    return sum(values)/len(values) if values else None


def summarize_predictions(observations, config):
    lookup = {round(o['time_s']*1e9): o for o in observations}
    queue_errors, persistence_errors, busy_errors = [], [], []
    per_class = {name: [] for name in CLASSES}
    queue_missing = 0
    availability = Counter()
    delay_errors, lifetime_errors = [], []
    fallbacks, decisions = [], []
    for obs in observations:
        report = obs.get('prediction', {})
        fallbacks.extend(report.get('fallbacks', []))
        decisions.extend(report.get('decisions', []))
        for prediction in report.get('queue_forecasts', []):
            target = lookup.get(round(prediction['at_s']*1e9))
            if target is None:
                queue_missing += 3
                continue
            actual = next(q for q in target['queues'] if q['link_id']==prediction['link_id'] and q['direction']==prediction['direction'])
            for name, values in prediction['classes'].items():
                outcome = actual['classes'][name]['bytes']
                error = abs(values['predicted_bytes']-outcome)
                queue_errors.append(error)
                persistence_errors.append(abs(values['current_bytes']-outcome))
                per_class[name].append(error)
                if outcome or values['current_bytes'] or values['predicted_bytes']:
                    busy_errors.append(error)
        for prediction in report.get('link_forecasts', []):
            matched = []
            for sample in prediction['samples']:
                if sample['at_s'] <= obs['time_s']:
                    continue
                target = lookup.get(round(sample['at_s']*1e9))
                if target is None:
                    availability['unscored'] += 1
                    continue
                actual = next((e for e in target['links'] if e['id']==prediction['link_id']), None)
                exists = actual is not None
                availability['samples'] += 1
                availability['correct'] += sample['available']==exists
                availability['false_available'] += sample['available'] and not exists
                availability['false_unavailable'] += not sample['available'] and exists
                if exists and sample['available']:
                    delay_errors.append(abs(sample['delay_s']-actual['delay_s']))
                matched.append((sample['at_s']-obs['time_s'], exists))
            first_down = next((time for time, up in matched if not up), None)
            if first_down is not None and prediction['lifetime_upper_s'] is not None:
                lifetime_errors.append(abs(first_down-prediction['lifetime_upper_s']))
    return {'config': config, 'queue': {'samples':len(queue_errors), 'unscored_samples':queue_missing,
                                       'mae_bytes':mean(queue_errors), 'persistence_mae_bytes':mean(persistence_errors),
                                       'busy_samples':len(busy_errors), 'busy_mae_bytes':mean(busy_errors),
                                       'class_mae_bytes':{name:mean(values) for name,values in per_class.items()}},
            'orbital': {**dict(availability), 'availability_accuracy': availability['correct']/availability['samples'] if availability['samples'] else None,
                        'delay_mae_s':mean(delay_errors), 'uncensored_lifetime_samples':len(lifetime_errors),
                        'uncensored_lifetime_mae_s':mean(lifetime_errors)},
            'fallbacks':fallbacks, 'fallback_count':len(fallbacks),
            'decision_count':len(decisions), 'predicted_deadline_risks':sum(d['deadline_at_risk'] for d in decisions),
            'bulk_floor_risks':sum(d['bulk_floor_at_risk'] for d in decisions),
            'scoring': 'Exact future observation timestamps only; missing/horizon outcomes are unscored. Orbital agreement is against the same sampled simulator model, not independent physical validation.'}
