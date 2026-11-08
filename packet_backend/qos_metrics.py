"""Deadline outcomes and scheduler service gaps, separate from transport accounting."""
from packet_backend.qos import CLASSES
from packet_backend.results import percentile


def deadlines(packets, deadline, horizon):
    counts = dict(on_time=0, late=0, dropped=0, overdue=0, pending_not_due=0)
    for p in packets:
        if p['status'] == 'delivered':
            counts['on_time' if p['delay_s'] <= deadline + 1e-9 else 'late'] += 1
        elif p['status'] == 'dropped':
            counts['dropped'] += 1
        else:
            counts['overdue' if p['created_s'] + deadline <= horizon else 'pending_not_due'] += 1
    resolved = len(packets) - counts['pending_not_due']
    return {**counts, 'resolved': resolved,
            'success_ratio': counts['on_time']/resolved if resolved else None,
            'success_ratio_lower_bound': counts['on_time']/len(packets) if packets else None}


def jain(values):
    return sum(values)**2/(len(values)*sum(v*v for v in values)) if any(values) else None


def service_gaps(events, horizon, threshold):
    """Intervals without transmission starts while Bulk is waiting in a device queue."""
    waiting, maximum, violations = {}, 0.0, []
    def close(key, time):
        nonlocal maximum
        start = waiting.pop(key, None)
        if start is not None:
            gap = time-start
            maximum = max(maximum, gap)
            if gap > threshold:
                violations.append({'link_id': key[0], 'direction': key[1],
                                   'start_s': start, 'end_s': time, 'duration_s': gap})
    for e in events:
        if e['kind'] not in ('class_queue', 'class_service') or e['b'] != 2:
            continue
        key, time = (e['item'], e['a']), e['time_s']
        if e['kind'] == 'class_queue':
            if e['value'] > 0:
                waiting.setdefault(key, time)
            else:
                close(key, time)
        elif key in waiting:
            close(key, time)
            waiting[key] = time
    for key in list(waiting):
        close(key, horizon)
    return {'max_backlogged_service_gap_s': maximum, 'threshold_s': threshold,
            'starvation_intervals': violations}


def summarize_qos(plan, result):
    by_id = {f['flow_id']: f for f in result['flows']}
    for flow in plan['flows']:
        summary = by_id[flow['id']]
        subset = [p for p in result['udp_packets'] if p['flow_id'] == flow['id']]
        active_end = min(flow['end'], plan['duration_s'])
        # Delivered payload during the offered-load window; drain deliveries excluded.
        active_bytes = sum(p['size_bytes'] for p in subset
                           if p['status'] == 'delivered' and p['ended_s'] < active_end)
        if flow['protocol'] == 'tcp':
            active_bytes = sum(e['value'] for e in result.get('events', [])
                              if e['kind'] == 'tcp_receive' and e['item'] == flow['id'] and e['time_s'] < active_end)
        goodput = active_bytes*8/(active_end-flow['start'])
        summary.update(flow_type=flow['flow_type'], active_goodput_bps=goodput,
                       deadline_s=flow['deadline_s'], min_goodput_bps=flow['min_goodput_bps'])
        summary['deadline'] = deadlines(subset, flow['deadline_s'], plan['duration_s']) if flow['deadline_s'] else None
        offered = flow['protocol'] == 'tcp' or flow['rate'] > 0
        summary['goodput_target_violated'] = bool(offered and not summary.get('complete', False) and flow['min_goodput_bps'] and goodput < flow['min_goodput_bps'])
    classes = {}
    for name in CLASSES:
        members = [f for f in result['flows'] if f['flow_type'] == name]
        ids = {f['flow_id'] for f in members}
        packets = [p for p in result['udp_packets'] if p['flow_id'] in ids]
        delays = [p['delay_s'] for p in packets if p['status'] == 'delivered' and p['delay_s'] is not None]
        deadline_counts = {key: sum(f['deadline'][key] for f in members if f['deadline'])
                           for key in ('on_time','late','dropped','overdue','pending_not_due','resolved')}

        udp_generated = len(packets)
        udp_delivered = sum(p['status'] == 'delivered' for p in packets)
        udp_dropped = sum(p['status'] == 'dropped' for p in packets)
        udp_in_flight = sum(p['status'] == 'in_flight' for p in packets)
        udp_undelivered = udp_dropped + udp_in_flight
        on_time = deadline_counts['on_time']
        late = deadline_counts['late']

        deadline_success_rate = (on_time / udp_generated * 100.0) if udp_generated > 0 else 0.0
        on_time_among_delivered = (on_time / udp_delivered * 100.0) if udp_delivered > 0 else 0.0
        deadline_miss_rate = ((udp_generated - on_time) / udp_generated * 100.0) if udp_generated > 0 else 0.0

        configured_deadline = None
        if plan.get('qos') and 'targets' in plan['qos'] and name in plan['qos']['targets']:
            configured_deadline = plan['qos']['targets'][name].get('deadline_s')
        if configured_deadline is None:
            member_deadlines = [f.get('deadline_s') for f in members if f.get('deadline_s') is not None]
            if member_deadlines:
                configured_deadline = member_deadlines[0]

        classes[name] = {
            'flow_count': len(members),
            'udp_generated': udp_generated,
            'udp_delivered': udp_delivered,
            'udp_dropped': udp_dropped,
            'udp_in_flight': udp_in_flight,
            'udp_undelivered': udp_undelivered,
            'on_time_count': on_time,
            'late_count': late,
            'generated': udp_generated,
            'delivered': udp_delivered,
            'dropped': udp_dropped,
            'deadline_met': on_time,
            'delivered_bytes': sum(f['delivered_bytes'] for f in members),
            'goodput_bps': sum(f['goodput_bps'] for f in members),
            'configured_deadline_s': configured_deadline,
            'sample_count': len(delays),
            'delay_mean_s': (sum(delays) / len(delays)) if delays else None,
            'delay_median_s': percentile(delays, 0.50),
            'delay_p95_s': percentile(delays, 0.95),
            'delay_p99_s': percentile(delays, 0.99),
            'deadline_success_rate_pct': deadline_success_rate,
            'on_time_among_delivered_pct': on_time_among_delivered,
            'deadline_miss_rate_pct': deadline_miss_rate,
            'deadline': {
                **deadline_counts,
                'success_ratio': deadline_counts['on_time'] / deadline_counts['resolved'] if deadline_counts['resolved'] else None,
                'success_ratio_lower_bound': deadline_counts['on_time'] / udp_generated if udp_generated else None,
            },
            'goodput_target_violations': [f['flow_id'] for f in members if f['goodput_target_violated']],
        }
    bulk = [by_id[f['id']]['active_goodput_bps'] for f in plan['flows']
            if f['flow_type'] == 'BULK' and (f['protocol']=='tcp' or f['rate']>0)]
    starvation_thresh = 0.25
    if plan.get('qos') and isinstance(plan['qos'], dict):
        starvation_thresh = plan['qos'].get('targets', {}).get('BULK', {}).get('starvation_s', 0.25)
    return {'classes': classes, 'bulk_jain_active_goodput': jain(bulk),
            'bulk_service': service_gaps(result.get('events', []), plan['duration_s'], starvation_thresh),
            'config': plan.get('qos'), 'fallback_decisions': [],
            'fallback_note': 'Conventional policies recompute reachable routes; unreachable destinations have no route. No target-based fallback.'}
