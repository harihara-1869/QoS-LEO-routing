"""Loader and parser for LENS LEO satellite empirical measurement traces.

Implements strict validation of LENS IRTT and Ping CSV formats:
- Nanosecond timestamp conversion preserving high-precision integer timing.
- Correct IRTT loss handling (-1 is loss; companion 0s are not treated as 0 ms latency).
- Directional loss tracking (uplink, downlink, bilateral).
- Summary statistics (delay percentiles, loss rates, jitter, outage gap durations).
"""

from dataclasses import asdict, dataclass
import csv
import math
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any


@dataclass(frozen=True)
class MeasurementSample:
    """Individual parsed measurement probe."""
    timestamp_ns: int
    time_s: float
    rtt_ms: Optional[float]
    uplink_ms: Optional[float]
    downlink_ms: Optional[float]
    is_loss: bool
    loss_type: str  # 'none', 'bilateral', 'uplink', 'downlink'


class LensLoader:
    """Loads and preprocesses LENS measurement traces."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"LENS trace file not found: {self.path}")

    @staticmethod
    def parse_timestamp_ns(raw_val: str | int | float) -> int:
        """Parse raw timestamp into integer nanoseconds with magnitude detection."""
        val = int(float(raw_val))
        if val > 10**17:  # Nanoseconds (~1.7e18 for 2024)
            return val
        elif val > 10**14:  # Microseconds
            return val * 1_000
        elif val > 10**11:  # Milliseconds
            return val * 1_000_000
        else:  # Seconds
            return int(float(raw_val) * 1_000_000_000)

    def load(self) -> List[MeasurementSample]:
        """Parse the CSV trace into strongly-typed MeasurementSample records."""
        samples: List[MeasurementSample] = []
        with open(self.path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = [fn.strip().lower() for fn in (reader.fieldnames or [])]
            
            is_irtt = "uplink" in fieldnames and "downlink" in fieldnames
            
            start_ns: Optional[int] = None
            
            for row in reader:
                # Normalizing keys
                clean_row = {k.strip().lower(): v.strip() for k, v in row.items()}
                raw_ts = clean_row.get("timestamp") or clean_row.get("time")
                if not raw_ts:
                    continue
                
                t_ns = self.parse_timestamp_ns(raw_ts)
                if start_ns is None:
                    start_ns = t_ns
                time_s = (t_ns - start_ns) / 1e9

                if is_irtt:
                    raw_rtt = float(clean_row["rtt"])
                    raw_up = float(clean_row["uplink"])
                    raw_down = float(clean_row["downlink"])

                    # Interpret IRTT loss rules per clarkzjw/LENS specification:
                    # -1 in any field indicates loss.
                    # When true: rtt=-1, up=0, down=0 (or all -1) -> bilateral
                    # When true_up: up=-1, rtt=0, down=0 -> uplink loss
                    # When true_down: down=-1, rtt=0, up=0 -> downlink loss
                    is_loss = False
                    loss_type = "none"
                    rtt_val: Optional[float] = None
                    up_val: Optional[float] = None
                    down_val: Optional[float] = None

                    if (raw_rtt < 0 and raw_up < 0 and raw_down < 0) or (raw_rtt < 0 and raw_up == 0.0 and raw_down == 0.0):
                        is_loss = True
                        loss_type = "bilateral"
                    elif raw_up < 0 or (raw_rtt == 0.0 and raw_up < 0 and raw_down == 0.0):
                        is_loss = True
                        loss_type = "uplink"
                    elif raw_down < 0 or (raw_rtt == 0.0 and raw_up == 0.0 and raw_down < 0):
                        is_loss = True
                        loss_type = "downlink"
                    elif raw_rtt < 0:
                        is_loss = True
                        loss_type = "bilateral"
                    elif raw_rtt == 0.0 and raw_up == 0.0 and raw_down == 0.0:
                        is_loss = True
                        loss_type = "bilateral"

                    if not is_loss:
                        rtt_val = raw_rtt
                        up_val = raw_up if raw_up > 0 else None
                        down_val = raw_down if raw_down > 0 else None
                    else:
                        # CRITICAL: Never turn loss flags or companion zeros into 0 ms delay!
                        rtt_val = None
                        up_val = None
                        down_val = None

                    samples.append(MeasurementSample(
                        timestamp_ns=t_ns,
                        time_s=time_s,
                        rtt_ms=rtt_val,
                        uplink_ms=up_val,
                        downlink_ms=down_val,
                        is_loss=is_loss,
                        loss_type=loss_type
                    ))
                else:
                    # Ping format: timestamp, rtt (or icmp_seq, rtt)
                    raw_rtt = float(clean_row["rtt"])
                    if raw_rtt < 0:
                        samples.append(MeasurementSample(
                            timestamp_ns=t_ns,
                            time_s=time_s,
                            rtt_ms=None,
                            uplink_ms=None,
                            downlink_ms=None,
                            is_loss=True,
                            loss_type="bilateral"
                        ))
                    else:
                        samples.append(MeasurementSample(
                            timestamp_ns=t_ns,
                            time_s=time_s,
                            rtt_ms=raw_rtt,
                            uplink_ms=None,
                            downlink_ms=None,
                            is_loss=False,
                            loss_type="none"
                        ))

        return samples


def compute_statistics(samples: List[MeasurementSample]) -> Dict[str, Any]:
    """Compute empirical distribution metrics on parsed measurement samples."""
    total = len(samples)
    if total == 0:
        return {"total_samples": 0}

    lost_samples = [s for s in samples if s.is_loss]
    delivered_samples = [s for s in samples if not s.is_loss and s.rtt_ms is not None]
    
    total_loss_count = len(lost_samples)
    loss_rate = total_loss_count / total
    
    up_loss_count = sum(1 for s in lost_samples if s.loss_type in ("uplink", "bilateral"))
    down_loss_count = sum(1 for s in lost_samples if s.loss_type in ("downlink", "bilateral"))
    
    rtts = sorted(s.rtt_ms for s in delivered_samples if s.rtt_ms is not None)
    
    def percentile(data: List[float], p: float) -> float:
        if not data:
            return 0.0
        k = (len(data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return data[int(k)]
        d0 = data[int(f)] * (c - k)
        d1 = data[int(c)] * (k - f)
        return d0 + d1

    rtt_stats = {}
    if rtts:
        mean_rtt = sum(rtts) / len(rtts)
        variance = sum((x - mean_rtt) ** 2 for x in rtts) / len(rtts)
        rtt_stats = {
            "count": len(rtts),
            "min_ms": round(rtts[0], 3),
            "p25_ms": round(percentile(rtts, 25), 3),
            "median_ms": round(percentile(rtts, 50), 3),
            "p75_ms": round(percentile(rtts, 75), 3),
            "p95_ms": round(percentile(rtts, 95), 3),
            "p99_ms": round(percentile(rtts, 99), 3),
            "max_ms": round(rtts[-1], 3),
            "mean_ms": round(mean_rtt, 3),
            "stddev_ms": round(math.sqrt(variance), 3)
        }

    # Inter-Packet Delay Variation (IPDV / Jitter)
    ipdv_values: List[float] = []
    for i in range(1, len(delivered_samples)):
        dt = delivered_samples[i].rtt_ms - delivered_samples[i - 1].rtt_ms
        ipdv_values.append(abs(dt))

    ipdv_stats = {}
    if ipdv_values:
        ipdv_values.sort()
        mean_ipdv = sum(ipdv_values) / len(ipdv_values)
        ipdv_stats = {
            "mean_jitter_ms": round(mean_ipdv, 3),
            "median_jitter_ms": round(percentile(ipdv_values, 50), 3),
            "p95_jitter_ms": round(percentile(ipdv_values, 95), 3),
            "p99_jitter_ms": round(percentile(ipdv_values, 99), 3)
        }

    # Outage gap analysis (consecutive loss runs)
    outage_gaps = []
    current_gap_start = None
    current_gap_len = 0
    for s in samples:
        if s.is_loss:
            if current_gap_start is None:
                current_gap_start = s.time_s
            current_gap_len += 1
        else:
            if current_gap_start is not None:
                gap_duration = s.time_s - current_gap_start
                outage_gaps.append({"duration_s": round(gap_duration, 3), "packets": current_gap_len})
                current_gap_start = None
                current_gap_len = 0

    return {
        "total_probes": total,
        "delivered_probes": len(delivered_samples),
        "lost_probes": total_loss_count,
        "loss_rate_pct": round(loss_rate * 100.0, 3),
        "uplink_loss_rate_pct": round((up_loss_count / total) * 100.0, 3),
        "downlink_loss_rate_pct": round((down_loss_count / total) * 100.0, 3),
        "rtt_ms": rtt_stats,
        "jitter_ms": ipdv_stats,
        "outage_events": len(outage_gaps),
        "max_outage_duration_s": max((g["duration_s"] for g in outage_gaps), default=0.0)
    }
