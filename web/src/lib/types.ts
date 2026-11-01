export type ClassName = "CONTROL" | "REALTIME" | "BULK";
export type View = "mission" | "studio" | "library" | "compare" | "policies";
export interface Traffic {
  flow_id: number;
  flow_type: ClassName;
  protocol: "udp" | "tcp";
  src: string;
  dst: string;
  start_time: number;
  end_time: number;
  packet_size_bytes: number;
  data_rate_bps?: number;
  max_bytes?: number;
  deadline_s?: number;
  min_goodput_bps?: number;
}
export interface Scenario {
  schema_version: 1;
  epoch: string;
  seed: number;
  duration_s: number;
  step_s: number;
  control_interval_s: number;
  orbital_start_s: number;
  constellation: {
    n_planes: number;
    sats_per_plane: number;
    inclination: number;
    altitude_km: number;
    phasing_f?: number;
  };
  ground_stations: [string, number, number, number][];
  links: Record<string, number | boolean>;
  network: Record<string, number>;
  qos: Record<string, unknown>;
  prediction: Record<string, number>;
  flows: Traffic[];
  allow_ground_transit?: boolean;
  record_control_details?: boolean;
}
export interface NodeData {
  id: number;
  name: string;
  kind: "satellite" | "ground" | "network";
  coordinates: number[] | null;
}
export interface LinkData {
  id: number;
  a: number;
  b: number;
  delay_s: number;
  capacity_bps: number;
  queue_packets: number;
}
export interface ClassMetrics {
  generated: number;
  delivered: number;
  dropped: number;
  in_flight: number;
  delivered_bytes: number;
  goodput_bps: number;
  delay_p95_s: number | null;
  deadline_success: number | null;
}
export interface Metrics {
  generated: number;
  delivered: number;
  dropped: number;
  in_flight: number;
  delivered_bytes: number;
  goodput_bps: number;
  delay_mean_s: number | null;
  delay_p95_s: number | null;
  delivery_ratio: number | null;
  classes: Record<ClassName, ClassMetrics>;
}
export interface FlowRoute {
  id: number;
  flow_type: ClassName;
  src: number;
  dst: number;
  path: number[];
}
export interface Frame {
  time_s: number;
  positions: number[][];
  links: LinkData[];
  metrics: Metrics | null;
  routes: FlowRoute[];
  queues: {
    link_id: number;
    direction: number;
    packets?: number;
    bytes?: number;
  }[];
  forecast?: {
    flow_id: number;
    estimated_delay_s: number | null;
    deadline_at_risk: boolean;
    fallback: boolean;
  }[];
}
export interface RunEvent {
  time_s: number;
  kind: string;
  title: string;
  detail: string;
}
export interface Replay {
  schema_version: 1;
  id: string;
  name: string;
  status: string;
  policy: string | null;
  scenario: Scenario;
  nodes: NodeData[];
  duration_s: number;
  frames: Frame[];
  events: RunEvent[];
  source: string;
  scenario_hash?: string;
  result_hash?: string;
  source_hashes?: Record<string, string>;
  frame: string;
  units: string;
  bundled?: boolean;
  capabilities: { metrics: boolean; geometry: boolean; forecast: boolean };
  summary?: {
    bulk_jain_active_goodput?: number | null;
    bulk_service?: {
      max_backlogged_service_gap_s?: number;
      threshold_s?: number;
    };
  };
  total_frames?: number;
  sampled?: boolean;
}
export interface RunRecord {
  id: string;
  name: string;
  status: string;
  policy: string;
  created_at: string;
  scenario_hash?: string;
  duration_s: number;
  metrics: Metrics | null;
  error?: string;
  progress?: number;
  command_requested?: string | null;
  wall_seconds?: number;
}
export interface Policy {
  id: string;
  label: string;
  kind: "heuristic" | "learned";
  available: boolean;
  checkpoint_required: boolean;
  observation_version: number;
  action_version: number;
}
export interface Capabilities {
  policies: Policy[];
  engine_available: boolean;
  training_available: boolean;
  version: string;
}
export interface LiveSnapshot {
  run: RunRecord;
  frame?: Frame;
  nodes?: NodeData[];
  events?: RunEvent[];
  sequence: number;
}
