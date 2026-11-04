import { request } from "./api";
export const read = <T>(path: string) => request<T>(path);
export const send = <T>(path: string, body: unknown, method = "POST") =>
  request<T>(path, { method, body: JSON.stringify(body) });
export async function download(path: string, body: unknown, name: string) {
  const csrf =
    document.cookie
      .split("; ")
      .find((c) => c.startsWith("galant_post_csrf="))
      ?.split("=")[1] || "";
  const r = await fetch("/api/v1" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("No fue posible descargar el informe");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
export type Contribution = {
  control_id: string | null;
  association_id: string;
  site_id: string;
  site: string;
  contractor: string;
  classification: string;
  subject: string;
  worker: string;
  worker_rut: string;
  period: string;
  required_days: number | null;
  suggested_days: number | null;
  paid_days: number | null;
  attendance_days: number | null;
  missing_days: number | null;
  difference: number | null;
  estimated_retention: number | null;
  daily_clp: number;
  confirmed: boolean;
  state: string;
  document_state: string;
  receipt_document_id: string | null;
  payment_finding: string;
  documented_amount: number | null;
  expected_amount: number | null;
  monetary_difference: number | null;
  justification: string;
};
export type Summary = {
  records: number;
  missing_days: number;
  denominator: number;
  average_paid_days: number | null;
  without_information: number;
  coverage: number | null;
  with_differences: number;
  confirmed: number;
  pending_confirmation: number;
  estimated_retention: number;
};
export type MatrixRow = {
  association_id: string;
  site_id: string;
  contractor: string;
  subject: string;
  name: string;
  period: string;
  requirement: string;
  state: string;
  delivery_state: string;
  observation: string;
  document_id: string | null;
};
export type Preferences = {
  name: string;
  appearance: "light" | "dark";
  density: "comfortable" | "compact";
  notifications: boolean;
  default_site: string | null;
  language: "es";
  date_format: "dd/mm/yyyy";
};
export type OrgProfile = {
  organization: string;
  version: string;
  preferences: Preferences;
};
