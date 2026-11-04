import { request } from "./api";
export const net = <T>(path: string) => request<T>("/network" + path);
export const change = <T>(path: string, body?: unknown, method = "POST") =>
  request<T>("/network" + path, {
    method,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
export type Page<T> = { rows: T[]; total: number };
export type Catalog = {
  sites: { id: string; name: string; editable: boolean }[];
  contractors: {
    id: string;
    name: string;
    rut: string | null;
    site_ids: string[];
  }[];
  specialties: string[];
};
export type Account = {
  id: string;
  name: string;
  email: string;
  title: string;
  role: string;
  enabled: boolean;
  site_ids: string[];
  can_award: boolean;
  notifications?: boolean;
};
export type Award = {
  id: string;
  item_id: string;
  item_name: string;
  requirement_id: string;
  requirement: string;
  site_id: string;
  site: string;
  contractor_id: string;
  contractor: string;
  rut: string | null;
  quantity: number;
  unit: string;
  executed: number;
  state: string;
  start_date: string;
  end_date: string;
  notes: string;
  awarded_by: string;
  created_at: string;
  version: number;
  capacity_id: string | null;
  coordination_id: string | null;
  workers: number;
  clearance?: {
    state: string;
    label: string;
    approved: number;
    required: number;
  };
};
export type Item = {
  id: string;
  name: string;
  description: string;
  quantity: number;
  unit: string;
  start_date: string;
  end_date: string;
  notes: string;
  awarded: number;
  pending: number;
  executed: number;
  state: string;
  execution: string;
  awards: Award[];
};
export type Requirement = {
  id: string;
  site_id: string;
  site: string;
  title: string;
  specialty: string;
  priority: string;
  workers: number;
  start_date: string;
  end_date: string;
  deadline: string;
  state: string;
  allocation_state: string;
  description: string;
  resident: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  editable: boolean;
  can_award: boolean;
  version: number;
  items: Item[];
  item_count: number;
  covered_items: number;
  coverage: number;
};
export type PendingItem = {
  name: string;
  quantity: number;
  unit: string;
  end_date: string;
};
export type Capacity = {
  id: string;
  site_id: string;
  site: string;
  contractor_id: string;
  contractor: string;
  rut: string | null;
  specialty: string;
  resident: string;
  created_by: string;
  situation: string;
  workers: number;
  mode: string;
  available_date: string;
  availability: string;
  can_transfer: boolean;
  notes: string;
  state: string;
  confirmed_at: string | null;
  expires_on: string;
  expired: boolean;
  stale: boolean;
  updated_at: string;
  editable: boolean;
  version: number;
  pending_items: PendingItem[];
};
export type Match = {
  id: string;
  score: number;
  reasons: string[];
  requirement: Requirement;
  capacity: Capacity;
};
export type Coordination = {
  id: string;
  match_id: string;
  requirement_id: string;
  requirement: string;
  site: string;
  origin: string;
  contractor: string;
  state: string;
  reason: string;
  version: number;
  conversation_id: string | null;
  updated_at: string;
  capacity_id: string;
};
export type Conversation = {
  id: string;
  coordination_id: string;
  title: string;
  site: string;
  unread: number;
};
export type Message = {
  id: string;
  body: string;
  sender_id: string;
  sender: string;
  created_at: string;
};
export type Messages = {
  rows: Message[];
  next_before: string | null;
  participants: {
    id: string;
    name: string;
    sites: string[];
    read_at: string | null;
  }[];
};
export type Notices = {
  rows: {
    id: string;
    title: string;
    resource_type: string;
    resource_id: string;
    created_at: string;
    read: boolean;
  }[];
  unread: number;
  total: number;
};
export type Overview = {
  requirements: number;
  urgent: number;
  pending_items: number;
  partial_items: number;
  awarded_items: number;
  capacities: number;
  matches: number;
  active_coordinations: number;
  awards: number;
  pending_clearance: number;
  enabled_awards: number;
  average_award_days: number | null;
  unread_messages: number;
  by_site: Record<string, number>;
  by_specialty: Record<string, number>;
};
export type CalendarEvent = {
  id: string;
  kind: string;
  title: string;
  site_id: string;
  date: string;
  end_date: string;
  requirement_id?: string;
  overdue: boolean;
};
export type Attachment = {
  id: string;
  filename: string;
  size: number;
  uploaded_by: string;
  created_at: string;
};
export const attach = (
  file: File,
  kind: "requirement_id" | "conversation_id",
  id: string,
) => {
  const data = new FormData();
  data.append("file", file);
  data.append(kind, id);
  return request<Attachment>("/network/attachments", {
    method: "POST",
    body: data,
  });
};
