# Working research gap matrix

Initial screen: 23 October 2026. These entries describe official abstracts/repository documentation, not an exhaustive full-paper review or an established novelty claim. The heuristic prototype is now implemented; revisit full texts and released code before finalizing novelty claims or the learned-controller evaluation.

| Reference | Established overlap from source | Question for our evaluation |
| --- | --- | --- |
| [Hypatia, IMC 2020](https://github.com/snkas/hypatia) | Time-indexed satellite network generation and packet-level ns-3 evaluation. | Reuse/reference the simulation methodology; this engine is not our contribution. |
| [Queue-Aware and Resilient Routing, 2026](https://arxiv.org/abs/2605.04448) | Distributed MA-DRL with queue dynamics, background traffic and resilience; comparison with SARSA/Dijkstra. | Does short-horizon link lifetime plus queue forecasting improve on a strong predictive heuristic under the same packet model? Queue-aware RL alone is not new. |
| [QoS- and Physics-Aware Routing, 2025](https://arxiv.org/abs/2512.20835) | Geometry, optical feasibility masking, congestion indicators and DRL next hops. | Distinguish practical class deadlines/fairness and forecast ablations from existing feasible-action masking. |
| [Joint Geometric and QoS-Aware Routing, 2026](https://arxiv.org/abs/2610.01631) | Optical outage/range constraints, masked DQN and geometry filtering. | Our simple range model cannot claim equivalent optical fidelity; compare constraints and clarify the intended scope. |

Candidate contribution remains the controlled combination of forecasts, service safeguards and measured comparisons. PPO by itself, shortest-path imitation and queue-aware costs do not establish novelty. Pending: full-text comparison of forecast horizons, traffic classes, training/test separation, safeguards, baselines and simulator fidelity; record exact revisions and reproducible baselines before claiming a research gap.

## Measurement calibration preparation


Inspected the [official LENS repository](https://github.com/clarkzjw/LENS) on 23 October 2026. Its processed CSV documentation provides IRTT columns `timestamp,rtt,uplink,downlink` and ping examples. The documented IRTT timestamp example is a nanosecond-scale Unix timestamp; verify units against the selected file/parser. Preserve integers until conversion to avoid precision loss.

The documentation explains that `-1` signals loss for a metric, and other zero fields can accompany a directional loss. Do not turn these zeros into valid RTT or one-way observations. Preserve loss direction and metric type, distinguish RTT from uplink/downlink, and do not infer internal queues or routing actions.

The [documented archive list](https://github.com/clarkzjw/LENS#processed-csv-dataset) links monthly Zenodo snapshots; for example November 2023 CSV is listed at 21 GB compressed / 68 GB extracted. A monthly download was deliberately not made for this bounded compatibility exercise. The linked portal is the next candidate for a station/day subset. No accessible bounded trace has yet been acquired or validated; this preparation is not calibration evidence.

Before Phase 6: obtain one station/day subset, save dataset version/file hash, station and measurement endpoints, timestamp units and collection settings; inspect converter semantics at the chosen revision; split chronologically before fitting anything. Preserve code/dataset licences and attribution (repository code GPLv3, Zenodo files documented as CC BY-SA 4.0), checking the exact selected snapshot's terms. Phase 1's core simulator gate does not imply that trace acquisition is complete.
