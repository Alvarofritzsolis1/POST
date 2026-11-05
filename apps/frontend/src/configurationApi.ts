import { request } from "./api";

export type DocumentType = {
  id: string;
  code: string;
  name: string;
  description: string;
  category: string;
  level: string;
  frequency: string;
  conditions: string;
  system: boolean;
};
export type ConfigurationContractor = {
  association_id: string;
  contractor_id: string;
  name: string;
  rut: string | null;
  site_id: string;
  site: string;
  category: string;
  status: string;
};
export type ConfigurationSettings = {
  porteria_start_period: string;
  alert_days: number;
  repeated_periods: number;
  version: number;
};
export type ConfigurationBootstrap = {
  catalog: DocumentType[];
  sites: { id: string; name: string }[];
  contractors: ConfigurationContractor[];
  periods: string[];
  settings: ConfigurationSettings;
};
export type Counts = {
  required: number;
  approved: number;
  submitted: number;
  missing: number;
  incomplete: number;
  rejected: number;
  overdue: number;
  exempt: number;
  compliance: number | null;
  delivery: number | null;
  porteria_pending?: number;
  active?: number;
  inactive?: number;
  categories?: Record<string, number>;
};
export type ReviewState =
  | "approved"
  | "submitted"
  | "missing"
  | "incomplete"
  | "rejected"
  | "overdue"
  | "not_applicable"
  | "exempt"
  | "no_movements";
export type Obligation = {
  association_id: string;
  contractor: string;
  site_id: string;
  site: string;
  category: string;
  period: string;
  document_type_id: string;
  code: string;
  document: string;
  required: boolean;
  state: string;
  rule_source: string;
  rule_id: string | null;
  due_date: string | null;
  notes: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  document_id: string | null;
  original_name: string | null;
  subject?: string;
  worker?: string | null;
};
export type ConfigurationAlert = {
  key: string;
  association_id: string;
  contractor: string;
  site: string;
  period: string;
  document: string;
  reason: string;
  priority: string;
  action: string;
};
export type AuditRow = {
  id: string;
  actor: string;
  user_id: string;
  at: string;
  action: string;
  association_id: string | null;
  site_id: string | null;
  period: string | null;
  document: string;
  reason: string;
  before: unknown;
  after: unknown;
};
export type Rule = {
  id: string;
  document_type_id: string;
  document?: string;
  scope: string;
  category?: string | null;
  site_id?: string | null;
  association_ids?: string[];
  required: boolean | null;
  frequency: string;
  period_start: string;
  period_end: string | null;
  due_day?: number | null;
  due_month_offset?: number;
  reason: string;
};
export type ConfigurationSummary = {
  periods: string[];
  summary: Counts;
  by_period: (Counts & { period: string })[];
  by_site: (Counts & { site_id: string; site: string })[];
  contractors: (ConfigurationContractor & Counts)[];
  obligations: Obligation[];
  alerts: ConfigurationAlert[];
};
export type GateMovement = {
  id: string;
  period: string;
  worker_name: string;
  worker_rut: string | null;
  movement_date: string;
  notes: string;
};
export type ContractorDetail = ConfigurationSummary & {
  contractor: ConfigurationContractor;
  workers: {
    id: string;
    name: string;
    rut: string | null;
    active: boolean;
    contracts: {
      id: string;
      start_date: string;
      end_date: string | null;
      status: string;
    }[];
  }[];
  rules: Rule[];
  audit: AuditRow[];
  gate_movements?: GateMovement[];
};
export type RuleInput = {
  document_type_id: string;
  scope: "general" | "category" | "site" | "association" | "exception";
  category?: string;
  site_id?: string;
  association_ids: string[];
  required: boolean | null;
  frequency: string;
  period_start: string;
  period_end: string | null;
  due_day: number | null;
  due_month_offset: number;
  reason: string;
  retroactive: boolean;
};
export type RulePreview = {
  preview_token: string;
  affected: number;
  conflicts: (Rule | string)[];
  changes: {
    association_id: string;
    name: string;
    site: string;
    period: string;
    from_required: boolean | null;
    to_required: boolean | null;
  }[];
  historical: boolean;
  periods_previewed?: string[];
  continues_after_preview?: boolean;
};
const root = "/admin/configuration";
export type PorteriaStartInput = {
  period_start: string;
  reason: string;
  retroactive: boolean;
};
export const configurationApi = {
  bootstrap: () => request<ConfigurationBootstrap>(root + "/bootstrap"),
  summary: (query: string) =>
    request<ConfigurationSummary>(root + "/summary?" + query),
  contractor: (id: string, query: string) =>
    request<ContractorDetail>(
      root + "/contractors/" + encodeURIComponent(id) + "?" + query,
    ),
  catalog: (body: Omit<DocumentType, "id" | "code" | "system">) =>
    request<DocumentType>(root + "/catalog", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  preview: (body: RuleInput) =>
    request<RulePreview>(root + "/rules/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  apply: (body: RuleInput, token: string) =>
    request<{ created: number; version: number }>(root + "/rules/apply", {
      method: "POST",
      body: JSON.stringify({ ...body, preview_token: token, confirm: true }),
    }),
  porteriaPreview: (body: PorteriaStartInput) =>
    request<RulePreview>(root + "/porteria-start/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  porteriaApply: (body: PorteriaStartInput, token: string) =>
    request(root + "/porteria-start/apply", {
      method: "POST",
      body: JSON.stringify({ ...body, preview_token: token, confirm: true }),
    }),
  review: (body: {
    association_id: string;
    period: string;
    document_type_id: string;
    state: ReviewState;
    notes: string;
    subject?: string;
  }) =>
    request(root + "/reviews", { method: "PUT", body: JSON.stringify(body) }),
  gate: (body: {
    association_id: string;
    period: string;
    worker_name: string;
    worker_rut: string | null;
    movement_date: string;
    notes: string;
  }) =>
    request<GateMovement>(root + "/gate-movements", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alerts: (body: {
    alert_days: number;
    repeated_periods: number;
    reason: string;
  }) =>
    request(root + "/alerts", { method: "PUT", body: JSON.stringify(body) }),
  audit: (query: string) =>
    request<{ rows: AuditRow[]; total: number }>(root + "/audit?" + query),
};
