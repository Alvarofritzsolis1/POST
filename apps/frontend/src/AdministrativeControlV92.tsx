import { useEffect, useMemo, useState } from "react";
import { request } from "./api";
import type { Site } from "./opsApi";
import WeeklyAttendanceV81 from "./WeeklyAttendanceV81";
import ContractEntry from "./ContractEntry";
import "./administrative-v92.css";
import "./administrative-v93.css";

type LaborState = "vigente" | "por_vencer" | "vencido" | "terminado" | "por_verificar";
type Staff = {
  assignment_id: string; name: string; rut: string | null; contract_id: string | null;
  contract_type: string | null; start_date: string | null; end_date: string | null;
  labor_state: LaborState; termination_date: string | null; finiquito_state: string;
  finiquito_overdue: boolean;
};
type Week = {
  week_number: number; dates: string[]; state: string; due_at: string;
  missing_workers: number; completed_by: string | null; completed_at: string | null;
  assigned_to_name: string | null; entered_by: string | null;
  completed_on_time: boolean | null;
};
type Contractor = {
  association_id: string; contractor: string; rut: string | null;
  contractor_active: boolean; contractor_status: string; attendance_applicable: boolean;
  weeks: Week[]; staff: Staff[];
  staff_counts: Record<LaborState, number>;
  pending_finiquitos: number; overdue_finiquitos: number;
};
type Overview = {
  site_id: string; period: string; as_of: string; week_count: number;
  contractors: Contractor[];
  summary: Record<string, number>;
};
export type AdministrativeTab = "attendance" | "contracts" | "severance" | "staff" | "performance";
type Tab = AdministrativeTab;
type Assessment = {
  required: number; completed: number; punctual: number; overdue: number;
  delivered_late: number; exempt: number; grade: number;
  duties: { id: string; contractor: string; week_number: number; exempt: boolean; completed_at: string | null; deadline_at: string }[];
};
const chileDate = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());
const date = (value: string | null | undefined) => value
  ? value.slice(0, 10).split("-").reverse().join("/") : "—";
const errorText = (value: unknown) => value instanceof Error ? value.message : String(value);
const weekText: Record<string, string> = {
  completed_on_time: "Revisada a tiempo", completed_late: "Revisada fuera de plazo",
  overdue: "Fuera de plazo", pending: "Pendiente", draft: "En progreso",
  excluded: "No incluida", not_required: "No exigible",
  needs_legacy_review: "Histórica: revisar",
};
const workerText: Record<LaborState, string> = {
  vigente: "Vigente", por_vencer: "Por vencer", vencido: "Vencido: revisar",
  terminado: "Terminado", por_verificar: "Por verificar",
};
const finiquitoText: Record<string, string> = {
  approved: "Validado", delivered: "Recibido", pending: "En revisión",
  observed: "Observado", rejected: "Rechazado",
  missing: "Pendiente", not_applicable: "No aplica",
};
const contractText: Record<string, string> = {
  indefinite: "Indefinido", fixed_term: "Plazo fijo",
  project: "Obra o faena", services: "Servicios",
};
function tone(state: string): "ok" | "warn" | "bad" | "muted" {
  if (state === "completed_on_time" || state === "vigente" || state === "approved") return "ok";
  if (state === "overdue" || state === "vencido") return "bad";
  if (state === "excluded" || state === "not_required" || state === "terminado") return "muted";
  return "warn";
}
function WeekBadge({ week }: { week?: Week }) {
  const started = !!week?.dates?.length && week.dates[0] <= chileDate();
  const hours = week ? (new Date(week.due_at).getTime() - Date.now()) / 3_600_000 : Infinity;
  const nearing = !!week && started && ["pending", "draft"].includes(week.state) && hours >= 0 && hours <= 48;
  const scheduled = !!week && !started && ["pending", "draft"].includes(week.state);
  const state = scheduled ? "muted" : tone(week?.state || "not_required");
  const label = scheduled ? "Programada" : nearing ? "Próximo a vencer"
    : week ? (weekText[week.state] || "Por verificar") : "No aplica";
  return <span className={`av92-badge ${state}`}>{label}</span>;
}
export default function AdministrativeControlV92({
  siteId, sites, period, tab, role = "administrative", onChangeTab,
}: {
  siteId: string; sites: Site[]; period: string; tab: Tab;
  role?: "admin" | "administrative"; onChangeTab?: (tab: Tab) => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [weekNumber, setWeekNumber] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [showInactive, setShowInactive] = useState(false);
  const [asOf, setAsOf] = useState(chileDate);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [evaluation, setEvaluation] = useState<Assessment | null>(null);
  const [evaluationError, setEvaluationError] = useState("");

  useEffect(() => { setWeekNumber(null); setSelectedId(""); setFilter("all"); setSearch(""); }, [siteId, period]);
  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    const query = `/attendance-v81/overview?site_id=${encodeURIComponent(siteId)}&period=${encodeURIComponent(period)}&as_of=${encodeURIComponent(asOf)}`;
    void request<Overview>(query)
      .then((value) => { if (active) setOverview(value); })
      .catch((reason) => { if (active) { setError(errorText(reason)); setOverview(null); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [siteId, period, asOf, revision]);

  useEffect(() => {
    const update = () => setRevision((count) => count + 1);
    const timer = window.setInterval(update, 30000);
    window.addEventListener("focus", update);
    window.addEventListener("galant-changed", update);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", update); window.removeEventListener("galant-changed", update); };
  }, []);

  useEffect(() => {
    if (tab !== "performance" || role !== "administrative") return;
    let active = true;
    void request<Assessment>(`/attendance-v81/my-evaluation?period=${encodeURIComponent(period)}`)
      .then((data) => { if (active) { setEvaluation(data); setEvaluationError(""); } })
      .catch((cause) => { if (active) setEvaluationError(errorText(cause)); });
    return () => { active = false; };
  }, [tab, role, period, revision]);

  const weekOptions = useMemo(() => overview?.contractors.find((row) => row.weeks.length)?.weeks || [], [overview]);
  const effectiveWeek = useMemo(() => {
    if (weekNumber && weekOptions.some((row) => row.week_number === weekNumber)) return weekNumber;
    const today = chileDate();
    return (weekOptions.find((w) => w.dates[0] <= today && w.dates[w.dates.length - 1] >= today)
      || weekOptions.find((w) => w.dates[0] > today)
      || weekOptions[weekOptions.length - 1])?.week_number || null;
  }, [weekNumber, weekOptions]);
  const weekOf = (row: Contractor) => row.weeks.find((w) => w.week_number === effectiveWeek);
  const activeContractors = useMemo(() => (overview?.contractors || [])
    .filter((row) => showInactive || row.contractor_active), [overview, showInactive]);
  const weekRows = activeContractors.filter((row) => row.contractor_active && row.attendance_applicable
    && weekOf(row)?.state !== "not_required" && (weekOf(row)?.dates[0] || "") <= chileDate());
  const complete = weekRows.filter((row) => ["completed_on_time", "completed_late"].includes(weekOf(row)?.state || "")).length;
  const pending = weekRows.filter((row) => ["pending", "draft", "needs_legacy_review"].includes(weekOf(row)?.state || "")).length;
  const overdue = weekRows.filter((row) => weekOf(row)?.state === "overdue").length;
  const compliance = weekRows.length ? Math.round(100 * complete / weekRows.length) : null;
  const monthObligations = activeContractors.flatMap((row) => row.contractor_active && row.attendance_applicable
    ? row.weeks.filter((w) => w.dates.length && w.dates[0] <= chileDate() &&
        !["excluded", "not_required"].includes(w.state)) : []);
  const monthlyDone = monthObligations.filter((w) => ["completed_on_time", "completed_late"].includes(w.state)).length;
  const monthlyCompliance = monthObligations.length
    ? Math.round(100 * monthlyDone / monthObligations.length) : null;
  const contractorProgress = (row: Contractor) => {
    const due = row.attendance_applicable ? row.weeks.filter((w) =>
      w.dates.length && w.dates[0] <= chileDate() && !["excluded", "not_required"].includes(w.state)) : [];
    if (!due.length) return "No exigible";
    const done = due.filter((w) => ["completed_on_time", "completed_late"].includes(w.state)).length;
    return `${Math.round(done * 100 / due.length)}%`;
  };
  const visibleContractors = activeContractors.filter((row) => {
    if (search && !(`${row.contractor} ${row.rut || ""}`).toLocaleLowerCase("es-CL").includes(search.toLocaleLowerCase("es-CL"))) return false;
    const week = weekOf(row);
    if (filter === "done") return !!week && ["completed_on_time", "completed_late"].includes(week.state);
    if (filter === "pending") return !!week && week.dates[0] <= chileDate() && ["pending", "draft", "needs_legacy_review"].includes(week.state);
    if (filter === "overdue") return week?.state === "overdue";
    if (filter === "contracts") return row.staff_counts.por_vencer + row.staff_counts.vencido > 0;
    if (filter === "finiquitos") return row.pending_finiquitos > 0;
    return true;
  }).sort((a, b) => {
    const priority = (row: Contractor) => weekOf(row)?.state === "overdue" ? 0
      : ["pending", "draft", "needs_legacy_review"].includes(weekOf(row)?.state || "") ? 1 : 2;
    return priority(a) - priority(b) || a.contractor.localeCompare(b.contractor, "es");
  });
  const contractor = overview?.contractors.find((row) => row.association_id === selectedId);
  const allPeople = activeContractors.flatMap((row) => row.staff.map((person) => ({
    ...person, contractor: row.contractor,
  }))).filter((row) => (`${row.name} ${row.rut || ""} ${row.contractor}`)
    .toLocaleLowerCase("es-CL").includes(search.toLocaleLowerCase("es-CL")));
  const finiquitos = allPeople.filter((row) => row.labor_state === "terminado");
  const contractPeople = allPeople.filter((row) => row.contract_id);
  const viewTitle: Record<Tab, string> = {
    attendance: "Revisión de asistencia", contracts: "Vigencia de contratos",
    severance: "Control de finiquitos", staff: "Dotación de la obra",
    performance: "Mi cumplimiento mensual",
  };
  const currentTab = tab === "performance" ? [] : (tab === "severance" ? finiquitos
    : tab === "contracts" ? contractPeople : allPeople);
  const refresh = () => setRevision((n) => n + 1);

  return <section className="av92">
    <div className="av92-title">
      <div><h2>{viewTitle[tab]}</h2><p>Información compartida · {period} · {role === "admin" ? "Supervisión de obra" : "Obra asignada"}</p></div>
      <button type="button" className="av92-refresh" onClick={refresh} disabled={loading}>Actualizar datos</button>
    </div>
    {error && <p role="alert" className="alert danger">{error}</p>}
    {loading && <p role="status" className="av92-muted">Actualizando información de la obra…</p>}
    {overview && <>
      <div className="av92-metrics" aria-label="Resumen operativo">
        {[
          { key: "all", value: overview.summary.active_contractors, label: "Contratistas activos", title: "Todos los contratistas" },
          { key: "done", value: complete, label: "Semana revisada", title: "Revisados en la semana" },
          { key: "done", value: compliance === null ? "—" : compliance + "%", label: "Avance semanal", title: "Revisiones exigibles ya iniciadas" },
          { key: "all", value: monthlyCompliance === null ? "—" : monthlyCompliance + "%", label: "Avance mensual", title: "Obligaciones iniciadas, sin penalizar semanas futuras" },
          { key: "pending", value: pending, label: "Pendientes", title: "Pendientes de esta semana" },
          { key: "overdue", value: overdue, label: "Fuera de plazo", title: "Incumplimientos de asistencia" },
          { key: "staff", value: overview.summary.workers_vigente, label: "Trabajadores vigentes", title: "Dotación vigente a la fecha" },
          { key: "contracts", value: overview.summary.contracts_ending, label: "Contratos por vencer", title: "Alertas de contratos" },
          { key: "finiquitos", value: overview.summary.pending_finiquitos, label: "Finiquitos pendientes", title: "Documentos pendientes" },
        ].map((metric) => <button type="button" key={metric.label} className={`av92-metric ${filter === metric.key ? "current" : ""}`}
          title={metric.title}
          onClick={() => metric.key === "staff" && onChangeTab
            ? onChangeTab("staff") : setFilter(metric.key)}>
          <span>{metric.label}</span><strong>{metric.value ?? "—"}</strong>
        </button>)}
      </div>
      {tab === "attendance" && <>
        <div className="av92-weekbar" aria-label="Semanas con días laborales">
          {weekOptions.map((week, index) => <button type="button" key={week.week_number}
            className={week.week_number === effectiveWeek ? "current" : ""}
            aria-pressed={week.week_number === effectiveWeek}
            onClick={() => { setWeekNumber(week.week_number); setSelectedId(""); }}>
            <strong>Semana {index + 1}</strong>
            <span>{date(week.dates[0])} – {date(week.dates[week.dates.length - 1])}</span>
          </button>)}
        </div>
        <div className="av92-section-head">
          <div><h3>Contratistas de la obra</h3><p>{visibleContractors.length} de {activeContractors.length} contratistas mostrados. Selecciona uno para revisar trabajadores y asistencia.</p></div>
          <label className="av92-search">Buscar por nombre o RUT
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar contratista…" />
          </label>
        </div>
        <div className="av92-filters">
          {[
            ["all", "Todos"], ["overdue", "Vencidos"], ["pending", "Pendientes"],
            ["done", "Revisados"], ["contracts", "Contratos por vencer"], ["finiquitos", "Finiquitos"],
          ].map(([value, label]) => <button type="button" key={value}
            aria-pressed={filter === value} className={filter === value ? "current" : ""}
            onClick={() => setFilter(value)}>{label}</button>)}
          <label className="av92-check"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Incluir históricos</label>
        </div>
        <div className="av92-tablewrap">
          <table className="av92-table av93-month-matrix">
            <thead><tr><th>Contratista</th><th>Dotación vigente</th>
              {weekOptions.map((w, index) => <th key={w.week_number} scope="col" className="av93-week-cell">S{index + 1}<small>{date(w.dates[0]).slice(0,5)}</small></th>)}
              <th>Avance</th><th>Contratos</th><th>Finiquitos</th><th>Revisar</th>
            </tr></thead>
            <tbody>{visibleContractors.map((row) => {
              const week = weekOf(row);
              return <tr key={row.association_id} className={selectedId === row.association_id ? "selected" : ""}>
                <td><strong>{row.contractor}</strong><small>{row.rut || "RUT sin registrar"}{!row.contractor_active ? " · Histórico" : ""}</small></td>
                <td>{row.staff_counts.vigente + row.staff_counts.por_vencer}<small>{row.staff_counts.por_verificar ? `${row.staff_counts.por_verificar} por verificar` : "Vigentes y por vencer"}</small></td>
                {weekOptions.map((w) => {
                  const item = row.weeks.find((entry) => entry.week_number === w.week_number);
                  const description = item?.completed_by ? `Revisada por ${item.completed_by}` :
                    item?.assigned_to_name ? `Asignada a ${item.assigned_to_name}` : "Sin responsable asignado";
                  return <td key={w.week_number} className="av93-week-cell">
                    <button type="button" className="av93-cell-action" aria-label={`${row.contractor}, semana ${weekOptions.indexOf(w)+1}: ${weekText[item?.state || "not_required"] || "No exigible"}. ${description}`}
                      title={description} aria-pressed={selectedId === row.association_id && effectiveWeek === w.week_number}
                      onClick={() => { setWeekNumber(w.week_number); setSelectedId(row.association_id); }}>
                      <WeekBadge week={row.attendance_applicable ? item : undefined} />
                    </button>
                  </td>;
                })}
                <td><strong>{contractorProgress(row)}</strong><small>{week?.assigned_to_name
                  ? `Asignada: ${week.assigned_to_name}` : "Sin asignación formal"}{week?.completed_by ? ` · Revisó: ${week.completed_by}` : ""}</small></td>
                <td>{row.staff_counts.vencido > 0 ? <span className="av92-badge bad">{row.staff_counts.vencido} vencidos</span>
                  : row.staff_counts.por_vencer > 0 ? <span className="av92-badge warn">{row.staff_counts.por_vencer} por vencer</span>
                  : <span className="av92-badge ok">Sin alertas</span>}</td>
                <td>{row.pending_finiquitos ? <span className={`av92-badge ${row.overdue_finiquitos ? "bad" : "warn"}`}>{row.pending_finiquitos} pendientes</span>
                  : <span className="av92-muted">Sin pendientes</span>}</td>
                <td><button type="button" className="av92-action" aria-expanded={selectedId === row.association_id}
                  onClick={() => setSelectedId((previous) => previous === row.association_id ? "" : row.association_id)}>
                  {selectedId === row.association_id ? "Cerrar" : "Ver asistencia"}</button></td>
              </tr>;
            })}</tbody>
          </table>
          {!visibleContractors.length && <p className="av92-empty">No hay contratistas para estos filtros.</p>}
        </div>
        {contractor && <div className="av92-selected">
          <div className="av92-section-head"><div><h3>{contractor.contractor}</h3>
            <p>Trabajadores a revisar según la semana elegida. Contratos y finiquitos se muestran por separado.</p></div>
            <button type="button" onClick={() => setSelectedId("")}>Cerrar detalle</button>
          </div>
          <WeeklyAttendanceV81 siteId={siteId} sites={sites} period={period}
            canEdit={true} canReview={role === "admin"} selectedAssociationId={selectedId}
            preferredWeekNumber={effectiveWeek} onSaved={refresh} />
        </div>}
      </>}
      {tab !== "attendance" && <>
        <div className="av92-section-head" id="av92-dotacion">
          <div><h3>{viewTitle[tab]}</h3><p>Fecha de consulta: {date(overview.as_of)}. La vigencia laboral no se presume si faltan antecedentes.</p></div>
          <label className="av92-search">Buscar trabajador o contratista
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Nombre, RUT o contratista" />
          </label>
          <label className="av92-search">Vigencia al día
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value || chileDate())} />
          </label>
        </div>
        {tab !== "performance" && <div className="av92-tablewrap">
          <table className="av92-table"><thead><tr>
            <th>Trabajador</th><th>Contratista</th><th>Tipo / inicio</th><th>Fecha de término</th><th>Vigencia</th><th>Finiquito</th>
          </tr></thead><tbody>{currentTab.map((person) => <tr key={person.assignment_id}>
            <td><strong>{person.name}</strong><small>{person.rut || "RUT pendiente"}</small></td>
            <td>{person.contractor}</td>
            <td>{contractText[person.contract_type || ""] || "Por verificar"}<small>{date(person.start_date)}</small></td>
            <td>{date(person.labor_state === "terminado" ? person.termination_date : person.end_date)}</td>
            <td><span className={`av92-badge ${tone(person.labor_state)}`}>{workerText[person.labor_state]}</span></td>
            <td>{person.finiquito_state !== "not_applicable"
              ? <span className={`av92-badge ${person.finiquito_overdue ? "bad" : tone(person.finiquito_state)}`}>{finiquitoText[person.finiquito_state] || "Por revisar"}</span>
              : "No aplica"}</td>
          </tr>)}</tbody></table>
          {!currentTab.length && <p className="av92-empty">No hay trabajadores para mostrar con estos criterios.</p>}
        </div>}
        {tab === "contracts" && <details className="av92-register">
          <summary>Registrar nuevo contrato de trabajo</summary>
          <ContractEntry siteId={siteId} period={period} />
        </details>}
        {tab === "severance" && <p className="av92-notice">La recepción y validación de finiquitos siguen los permisos documentales vigentes. Esta vista permite detectar pendientes; las aprobaciones se realizan desde el módulo laboral autorizado.</p>}
        {tab === "staff" && <p className="av92-notice">Un contrato vencido no significa automáticamente que el trabajador haya terminado su relación laboral. Los registros sin respaldo se muestran como «Por verificar». Los estados de revisión documental de finiquitos representan su estado actual, no necesariamente el que tenían en la fecha histórica consultada.</p>}
        {tab === "performance" && <>
          {evaluationError && <p role="alert" className="alert danger">{evaluationError}</p>}
          {evaluation && <div className="av92-evaluation">
            <div className="av92-metrics">
              {[
                ["Revisiones exigibles", evaluation.required],
                ["Completadas", evaluation.completed],
                ["Dentro de plazo", evaluation.punctual],
                ["Fuera de plazo", evaluation.delivered_late],
                ["Vencidas pendientes", evaluation.overdue],
                ["Nota provisional", evaluation.required ? evaluation.grade.toFixed(2) : "Sin evaluación"],
              ].map(([label, value]) => <div className="av92-metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}
            </div>
            <p>Esta evaluación considera únicamente obligaciones asignadas. Las revisiones tardías conservan su historial aun después de regularizarlas.</p>
          </div>}
        </>}
      </>}
    </>}
  </section>;
}
