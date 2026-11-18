export interface User {
  id: number;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface Role {
  name: string;
  title: string;
  permissions: string[];
}

export interface Floor {
  id: number;
  name: string;
  level: number;
  width: number;
  height: number;
}

export type ResourceKind = "room" | "desk";

export interface Resource {
  id: number;
  floor_id: number;
  kind: ResourceKind;
  name: string;
  capacity: number;
  x: number;
  y: number;
  w: number;
  h: number;
  equipment: string[];
  active: boolean;
  version: number;
}

export interface MapResource extends Resource {
  busy: boolean;
  /** занято бронью того, кто смотрит карту */
  mine: boolean;
}

export interface FloorMap {
  floor: Floor;
  at: string;
  resources: MapResource[];
}

export type BookingStatus = "pending" | "confirmed" | "checked_in" | "cancelled" | "expired" | "no_show";

export interface Booking {
  id: number;
  resource_id: number;
  user_id: number;
  user_email: string;
  start: string;
  end: string;
  status: BookingStatus;
  created_at: string;
  updated_at: string;
  cancelled_by: number | null;
  checked_in_at: string | null;
}

export interface JobInfo {
  name: string;
  schedule: string;
  mode: string;
  next_run_at: string | null;
  last_run: JobRun | null;
}

export interface JobRun {
  job: string;
  status: "ok" | "failed";
  trigger: string;
  started_at: string;
  finished_at: string;
  result: Record<string, unknown>;
}

export type Settings = Record<string, number>;
