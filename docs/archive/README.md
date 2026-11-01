# Historical implementation records

These records explain how the current simulator was established. They are not the current setup instructions or ownership plan. Read the [project README](../../README.md), [current contracts](../README.md) and [remaining-work roadmap](../REMAINING_WORK.md) first.

| Record | Scope |
| --- | --- |
| [PHASE1_FOUNDATION.md](PHASE1_FOUNDATION.md) | Original foundation milestone and which geometry components remain after retirement of the old workflow |
| [PACKET_ENGINE_DECISION.md](PACKET_ENGINE_DECISION.md) | Original ns-3/Hypatia compatibility decision and bounded probe evidence |
| [PHASE2_VALIDATION.md](PHASE2_VALIDATION.md) | Controlled forwarding, queue/failure and TCP validation of the compiled engine |
| [LEARNING_ENVIRONMENT_NOTES.md](LEARNING_ENVIRONMENT_NOTES.md) | Earlier learning design and benchmark notes; later timing/terminal refinements supersede their dimensions/resource figures |
| [REPOSITORY_CLEANUP.md](REPOSITORY_CLEANUP.md) | File/module migration, retired workflows and validation after repository cleanup |

Numerical tables, source/result hashes and transcript references are historical. Do not present old baselines as current measurements or mix records from different physical assumptions into a policy-effect comparison. The original binding probe is retired; current acceptance checks use the compiled backend and `tests/`.
