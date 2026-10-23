# Working research gap matrix

Initial screen: 23 October 2026. These entries describe official abstracts/repository documentation, not an exhaustive full-paper review or an established novelty claim. Revisit full texts and released code before finalising Phase 4/5.

| Reference | Established overlap from source | Question for our evaluation |
| --- | --- | --- |
| [Hypatia, IMC 2020](https://github.com/snkas/hypatia) | Time-indexed satellite network generation and packet-level ns-3 evaluation. | Reuse/reference the simulation methodology; this engine is not our contribution. |
| [Queue-Aware and Resilient Routing, 2026](https://arxiv.org/abs/2605.04448) | Distributed MA-DRL with queue dynamics, background traffic and resilience; comparison with SARSA/Dijkstra. | Does short-horizon link lifetime plus queue forecasting improve on a strong predictive heuristic under the same packet model? Queue-aware RL alone is not new. |
| [QoS- and Physics-Aware Routing, 2025](https://arxiv.org/abs/2512.20835) | Geometry, optical feasibility masking, congestion indicators and DRL next hops. | Distinguish practical class deadlines/fairness and forecast ablations from existing feasible-action masking. |
| [Joint Geometric and QoS-Aware Routing, 2026](https://arxiv.org/abs/2610.01631) | Optical outage/range constraints, masked DQN and geometry filtering. | Our simple range model cannot claim equivalent optical fidelity; compare constraints and clarify the intended scope. |

Candidate contribution remains the controlled combination of forecasts, service safeguards and measured comparisons. PPO by itself, shortest-path imitation and queue-aware costs do not establish novelty. Pending: full-text comparison of forecast horizons, traffic classes, training/test separation, safeguards, baselines and simulator fidelity; record exact revisions and reproducible baselines before claiming a research gap.
