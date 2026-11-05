import type { Requirement } from "./opsControlApi";

/**
 * Única presentación de la matriz documental de GALANT.
 * Nunca sustituye al evaluador de exigibilidad del backend.
 */
const excludedStates = new Set([
  "not_required", "not_yet_required", "not_applicable", "exempt",
  "no_movements", "inactive", "schedule_not_configured",
]);

const urgentStates = new Set(["overdue", "observed", "rejected", "incomplete", "missing"]);

export function evaluableRequirement(row: Requirement): boolean {
  return row.applicable === true && !excludedStates.has(row.state);
}

export function requirementCounts(row: Requirement): { required: number; approved: number } {
  const required = Math.max(0, row.required_count ?? 1);
  const approved = Math.min(required, Math.max(0, row.approved_count ?? (row.state === "approved" ? 1 : 0)));
  return { required, approved };
}

export function requirementPending(row: Requirement): boolean {
  // Exigibilidad desconocida y calendarios faltantes requieren configuración,
  // pero no se suman al denominador de cumplimiento.
  if (row.applicable === null || (row.applicable === true && row.state === "schedule_not_configured")) return true;
  if (!evaluableRequirement(row)) return false;
  const { required, approved } = requirementCounts(row);
  return required > approved;
}

export function summarizeRequirements(rows: Requirement[]) {
  const evaluable = rows.filter(evaluableRequirement);
  const totals = evaluable.reduce((acc, row) => {
    const count = requirementCounts(row);
    acc.required += count.required;
    acc.approved += count.approved;
    return acc;
  }, { required: 0, approved: 0 });
  const pending = rows.filter(requirementPending);
  const urgent = pending.filter(row => urgentStates.has(row.state) || row.state === "needs_classification");
  return {
    ...totals,
    pending,
    urgent,
    percent: totals.required ? Math.round(100 * totals.approved / totals.required) : null,
  };
}

export function statusTone(state: string): "ok" | "warn" | "bad" | "muted" {
  if (state === "approved") return "ok";
  if (urgentStates.has(state) || state === "missing") return "bad";
  if (excludedStates.has(state)) return "muted";
  return "warn";
}

export function statusLabel(state: string) {
  const labels: Record<string, string> = {
    approved: "Aprobado",
    submitted: "Entregado, pendiente de revisión",
    pending: "Pendiente de revisión",
    missing: "No entregado",
    incomplete: "Entregado incompleto",
    overdue: "Fuera de plazo",
    observed: "Observado",
    rejected: "Rechazado",
    exempt: "Exento",
    no_movements: "Sin movimientos",
    not_applicable: "No aplica",
    not_required: "No exigible",
    not_yet_required: "Aún no exigible",
    schedule_not_configured: "Sin calendario configurado",
    inactive: "Inactivo (no exigible)",
    needs_classification: "Exigibilidad sin definir",
  };
  return labels[state] ?? state;
}
