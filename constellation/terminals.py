"""Deterministic terminal reservations and acquisition; parameters are assumptions."""


class TerminalState:
    def __init__(self, config):
        self.config = config
        self.attachments = {}
        self.since = {}
        self.last_time = None

    def select_ground(self, visible, now):
        cfg = self.config
        ranked = []
        for station, candidates in visible.items():
            for elevation, name, node in candidates:
                incumbent = self.attachments.get((station, name))
                bonus = 0.0
                if incumbent is not None:
                    bonus = cfg.ground_hysteresis_deg
                    if now - incumbent < cfg.ground_min_dwell_s:
                        bonus += 1000
                ranked.append((-(elevation + bonus), station, name, node))
        counts, beams, chosen = {}, {}, {}
        result = []
        for _, station, name, node in sorted(ranked, key=lambda row: row[:3]):
            if counts.get(station, 0) >= cfg.ground_links_per_station:
                continue
            if beams.get(name, 0) >= cfg.ground_beams_per_satellite:
                continue
            counts[station] = counts.get(station, 0) + 1
            beams[name] = beams.get(name, 0) + 1
            chosen[station, name] = self.attachments.get((station, name), now)
            result.append((node, station))
        self.attachments = chosen
        return result

    def admit(self, candidates, now):
        if self.last_time is not None and now < self.last_time - 1e-6:
            raise ValueError("Terminal model must advance monotonically")
        first = self.last_time is None
        cfg = self.config
        degree, selected, pairs = {}, {}, set()

        def identity(link):
            kind, a, b = link
            return (kind.name, a.sat.name, b if isinstance(b, str) else b.sat.name)

        # Preserve established reservations; intra-plane first among new links.
        for link in sorted(
            candidates,
            key=lambda link: (
                identity(link) not in self.since,
                link[0].value,
                identity(link),
            ),
        ):
            kind, a, b = link
            key = identity(link)
            pair = frozenset(key[1:])
            if pair in pairs:
                continue
            if not isinstance(b, str):
                if any(
                    degree.get(n.sat.name, 0) >= cfg.isl_terminals_per_satellite
                    for n in (a, b)
                ):
                    continue
                for n in (a, b):
                    degree[n.sat.name] = degree.get(n.sat.name, 0) + 1
            pairs.add(pair)
            delay = (
                cfg.ground_acquisition_s
                if isinstance(b, str)
                else cfg.isl_acquisition_s
            )
            selected[key] = self.since.get(
                key, now - delay if first and cfg.initial_links_ready else now
            )
        self.since = selected
        self.last_time = now
        return {
            link
            for link in candidates
            if identity(link) in selected
            and now - selected[identity(link)] + 1e-6
            >= (
                cfg.ground_acquisition_s
                if isinstance(link[2], str)
                else cfg.isl_acquisition_s
            )
        }
