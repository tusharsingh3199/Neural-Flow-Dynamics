export type IsoDateTime = string;

export type ProductClass =
  | "observation"
  | "official_warning"
  | "numerical_forecast"
  | "experimental_ai"
  | "simulated"
  | "unvalidated_risk";

export type Unit =
  | "m s-1"
  | "km h-1"
  | "kn"
  | "m"
  | "mm"
  | "mm h-1"
  | "kg m-2"
  | "K"
  | "degC"
  | "Pa"
  | "hPa"
  | "W m-2"
  | "kg kg-1"
  | "m2 s-2"
  | "degrees_east"
  | "degrees_north"
  | "people"
  | "count"
  | "1";

export interface Provenance {
  source_id: string;
  source_url: string;
  licence: string;
  retrieved_at: IsoDateTime;
  ingested_at: IsoDateTime;
  checksum: `sha256:${string}`;
  transformation_history: string[];
}

export interface ForecastRun {
  model: string;
  init_time: IsoDateTime;
  lead_times_hours: number[];
  source_run_id: string;
}

export interface GridMetadata {
  description: string;
  crs: string;
  resolution_degrees: [number, number] | null;
}

export interface LayerLegend {
  minimum: number;
  maximum: number;
  colours: string[];
}

export interface LayerMeta {
  id: string;
  name: string;
  variable: string;
  unit: Unit;
  product_class: ProductClass;
  grid: GridMetadata;
  valid_times: IsoDateTime[];
  provenance: Provenance;
  description: string;
  colormap: string;
  legend: LayerLegend;
}

export interface HazardAssessment {
  id: string;
  product_class: "unvalidated_risk";
  source_layer_id: string;
  forecast_run_id: string;
  valid_start: IsoDateTime;
  valid_end: IsoDateTime;
  threshold: number;
  unit: Unit;
  resolution_description: string;
  limitations: string[];
}

export interface ExposureSummary {
  hazard_id: string;
  geography_id: string;
  exposed_population: number;
  population_reference_year: number;
  exposed_facilities: number;
  vulnerability_limitations: string[];
  provenance: Provenance;
}

export interface GeoPoint {
  latitude: number;
  longitude: number;
}

export interface Incident {
  id: string;
  description: string;
  location: GeoPoint;
  severity: 1 | 2 | 3 | 4 | 5;
  status: "unverified" | "verified" | "closed";
  product_class: ProductClass;
  reported_at: IsoDateTime;
}

export interface Team {
  id: string;
  capabilities: string[];
  location: GeoPoint;
  location_source: "live" | "last_known" | "manual" | "simulated";
  location_observed_at: IsoDateTime;
  available: boolean;
  product_class: ProductClass;
}

export interface Shelter {
  id: string;
  location: GeoPoint;
  capacity: number;
  occupancy: number;
  product_class: ProductClass;
}

export type TaskStatus =
  | "proposed"
  | "approved"
  | "acknowledged"
  | "in_progress"
  | "completed"
  | "delayed"
  | "cancelled"
  | "rejected";

export interface Task {
  id: string;
  title: string;
  status: TaskStatus;
  assigned_team_ids: string[];
  product_class: ProductClass;
  created_at: IsoDateTime;
}

export interface AuditEvent {
  id: string;
  actor_id: string;
  action: string;
  record_id: string;
  occurred_at: IsoDateTime;
  details: Record<string, string>;
}

export interface OfficialWarning {
  id: string;
  sender: string;
  sent: IsoDateTime;
  effective: IsoDateTime;
  expires: IsoDateTime;
  message_type: "Alert" | "Update" | "Cancel";
  scope: "Public" | "Restricted" | "Private";
  event: string;
  severity: "Extreme" | "Severe" | "Moderate" | "Minor" | "Unknown";
  urgency: "Immediate" | "Expected" | "Future" | "Past" | "Unknown";
  certainty: "Observed" | "Likely" | "Possible" | "Unlikely" | "Unknown";
  headline: string;
  description: string;
  product_class: "official_warning";
  provenance: Provenance;
}
