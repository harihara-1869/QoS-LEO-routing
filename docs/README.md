# Documentation

Start with the [project README](../README.md) for setup, operation, research context and phase progress. Use [REMAINING_WORK.md](REMAINING_WORK.md) for the maintained checklist and ownership across four contributors.

## Current contracts and guides

| Topic | Read this |
| --- | --- |
| Packet lifecycle, controller interface, scenario/results and metrics | [architecture/PACKET_BACKEND.md](architecture/PACKET_BACKEND.md) |
| Class scheduling, targets, deadlines, fairness and baseline comparisons | [architecture/QOS.md](architecture/QOS.md) |
| Heuristic predictors, class routing, safeguards and forecast scoring | [architecture/PREDICTIVE_ROUTING.md](architecture/PREDICTIVE_ROUTING.md) |
| Using Mission Control, native development and mentor walkthrough | [dashboard/GUIDE.md](dashboard/GUIDE.md) |
| Dashboard architecture, contracts and release acceptance specification | [dashboard/DESIGN.md](dashboard/DESIGN.md) |
| Current physical assumptions, terminal/timing refinement and measured cases | [research/FIDELITY.md](research/FIDELITY.md) |
| Research positioning, literature screen and measurement preparation | [research/RESEARCH_SCOPE.md](research/RESEARCH_SCOPE.md) |
| Starting the deferred learned-controller work | [research/LEARNING_HANDOFF.md](research/LEARNING_HANDOFF.md) |

The fidelity document supersedes older physical assumptions and numerical benchmarks. The root README and remaining-work checklist describe current progress/ownership; historical phase documents do not assign new work.

## Historical validation and provenance

[archive/README.md](archive/README.md) indexes the early engine decision, phase validation, earlier learning-environment notes and repository migration record. These are historical context, with their scope and dates preserved.

[evidence/README.md](evidence/README.md) explains the retained transcripts, source/result hashes and platform records. Raw evidence is intentionally left unchanged: an old source filename in a manifest is provenance, not a current import or runnable instruction. Saved experiments under `runs/` are generated local artifacts; they are not the checked-in documentation source.
