# LENS preparation (Phase 1 discovery, Phase 6 implementation)

Inspected the [official LENS repository](https://github.com/clarkzjw/LENS) on 23 October 2026. Its processed CSV documentation provides IRTT columns `timestamp,rtt,uplink,downlink` and ping examples. The documented IRTT timestamp example is a nanosecond-scale Unix timestamp; verify units against the selected file/parser. Preserve integers until conversion to avoid precision loss.

The documentation explains that `-1` signals loss for a metric, and other zero fields can accompany a directional loss. Do not turn these zeros into valid RTT or one-way observations. Preserve loss direction and metric type, distinguish RTT from uplink/downlink, and do not infer internal queues or routing actions.

The [documented archive list](https://github.com/clarkzjw/LENS#processed-csv-dataset) links monthly Zenodo snapshots; for example November 2023 CSV is listed at 21 GB compressed / 68 GB extracted. A monthly download was deliberately not made for this bounded compatibility exercise. The linked portal is the next candidate for a station/day subset. No accessible bounded trace has yet been acquired or validated; this preparation is not calibration evidence.

Before Phase 6: obtain one station/day subset, save dataset version/file hash, station and measurement endpoints, timestamp units and collection settings; inspect converter semantics at the chosen revision; split chronologically before fitting anything. Preserve code/dataset licences and attribution (repository code GPLv3, Zenodo files documented as CC BY-SA 4.0), checking the exact selected snapshot's terms. Phase 1's core simulator gate does not imply that trace acquisition is complete.
