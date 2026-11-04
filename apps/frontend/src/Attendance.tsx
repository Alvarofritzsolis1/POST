import { useEffect, useState } from "react";
import { api } from "./api";
import { read, send } from "./platformApi";
import type { Site } from "./opsApi";
import "./attendance.css";

type Entry = { worker_assignment_id: string; worker: string; rut: string; signed_dates: string[]; excluded: boolean; reason: string; recorded: boolean };
type Week = { id: string | null; week_number: number; dates: string[]; due_date?: string; state: string; severity: string; saved_state?: string; source_document_id?: string | null; notes?: string; entered_by?: string | null; entered_at?: string | null; updated_by?: string | null; updated_at?: string | null; completed_by?: string | null; completed_at?: string | null; completed_on_time?: boolean | null; review_state?: string | null; review_note?: string; reviewed_by?: string | null; reviewed_at?: string | null; missing_workers: number; entries: Entry[] };
type Contractor = { association_id: string; contractor: string; rut: string | null; administrative_status: string; roster_status: string; roster_reason: string; roster_updated_by?: string | null; roster_updated_at?: string | null; weeks: Week[]; workers: { assignment_id: string; name: string; rut: string | null; signed_days: number; paid_days: number | null; difference: number | null }[]; signed_days: number; paid_days: number; missing_payment_days: number };
type Roster = { site_id: string; period: string; contractors: Contractor[]; summary: { contractors: number; overdue_weeks: number; completed_weeks: number; signed_days: number; missing_payment_days: number } };

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const dayLabel = (value: string) => { const [y, m, d] = value.split("-"); return `${d}/${m}/${y}`; };
const timeLabel = (value?: string | null) => value ? new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + "Z").toLocaleString("es-CL", { timeZone: "America/Santiago", dateStyle: "short", timeStyle: "short" }) : "Sin registrar";
const statusLabel: Record<string, string> = { overdue: "Atrasada", pending: "Pendiente", draft: "Borrador", completed: "Ingresada, pendiente de revisión", approved: "Revisada y conforme", observed: "Observada", excluded: "No considerar", not_applicable: "No aplica" };

export default function Attendance({ siteId, sites, period, canEdit, canReview }: {
  siteId: string; sites: Site[]; period: string; canEdit: boolean; canReview: boolean;
}) {
  const [localSite, setLocalSite] = useState("");
  const [data, setData] = useState<Roster | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [weekNumber, setWeekNumber] = useState(1);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rosterReason, setRosterReason] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const activeSite = siteId || localSite || sites[0]?.id || "";
  useEffect(() => {
    if (!activeSite) { setData(null); return; }
    let alive = true;
    void read<Roster>(`/attendance/roster?site_id=${encodeURIComponent(activeSite)}&period=${encodeURIComponent(period)}`)
      .then((result) => { if (alive) { setData(result); setError(""); } })
      .catch((e) => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [activeSite, period, revision]);
  useEffect(() => { setSelectedId(""); setWeekNumber(1); }, [activeSite, period]);
  const contractor = data?.contractors.find((item) => item.association_id === selectedId) || null;
  const week = contractor?.weeks.find((item) => item.week_number === weekNumber) || null;
  useEffect(() => {
    setEntries(week?.entries.map((item) => ({ ...item, signed_dates: [...item.signed_dates] })) || []);
    setNotes(week?.notes || "");
    setFile(null);
    setReviewNote(week?.review_note || "");
    setRosterReason(contractor?.roster_reason || "");
  }, [selectedId, weekNumber, revision, data]);
  const refresh = () => { setRevision((current) => current + 1); window.dispatchEvent(new Event("galant-changed")); };
  async function run(action: () => Promise<void>, success: string) {
    setError(""); setNotice(""); setBusy(true);
    try { await action(); setNotice(success); refresh(); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  const changeEntry = (id: string, update: (row: Entry) => Entry) => setEntries((old) => old.map((row) => row.worker_assignment_id === id ? update(row) : row));
  async function saveWeek(complete: boolean) {
    if (!contractor || !week) return;
    await run(async () => {
      let source = week.source_document_id || null;
      if (file) source = (await api.upload(file, "auto")).id;
      await send("/attendance/weeks", {
        association_id: contractor.association_id, period, week_number: week.week_number,
        complete, source_document_id: source, notes,
        entries: entries.map((row) => ({ worker_assignment_id: row.worker_assignment_id,
          signed_dates: row.signed_dates, excluded: row.excluded, reason: row.reason })),
      }, "PUT");
    }, complete ? "Semana ingresada con fecha y responsable." : "Borrador de asistencia guardado.");
  }
  async function updateRoster(status: "included" | "excluded") {
    if (!contractor) return;
    await run(async () => {
      await send("/attendance/roster", {
        association_id: contractor.association_id, period, status,
        reason: status === "excluded" ? rosterReason : "",
      }, "PUT");
    }, status === "excluded" ? "Contratista excluido de la base mensual; su historial permanece disponible." : "Contratista incluido en la base mensual.");
  }
  async function review(state: "approved" | "observed") {
    if (!week?.id) return;
    await run(async () => { await send(`/attendance/weeks/${week.id}/review`, { state, note: reviewNote }, "PUT"); },
      state === "approved" ? "Semana revisada y conforme." : "Observación guardada; la administrativa puede corregir la semana.");
  }
  return <div className="attendance-page">
    <header className="workers-heading"><div><h2>Control de asistencia · {period}</h2>
      <p>La administrativa ingresa las firmas por semana. El balance mensual compara días firmados con días pagados registrados en cotizaciones.</p></div>
      {activeSite && <a className="secondary" href={`/api/v1/attendance/export?site_id=${encodeURIComponent(activeSite)}&period=${encodeURIComponent(period)}`}>Descargar planilla de 5 semanas</a>}
    </header>
    {!siteId && <label>Obra <select value={activeSite} onChange={(e) => setLocalSite(e.target.value)}>{sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}</select></label>}
    {error && <p role="alert" className="alert danger">{error}</p>}{notice && <p role="status" className="alert success">{notice}</p>}
    {data && <div className="kpi-grid">
      <div className="kpi"><small>Contratistas considerados</small><strong>{data.summary.contractors}</strong></div>
      <div className="kpi"><small>Semanas atrasadas</small><strong>{data.summary.overdue_weeks}</strong></div>
      <div className="kpi"><small>Semanas ingresadas</small><strong>{data.summary.completed_weeks}</strong></div>
      <div className="kpi"><small>Ingresos a obra con firma</small><strong>{data.summary.signed_days}</strong></div>
      <div className="kpi"><small>Días firmados sobre días pagados</small><strong>{data.summary.missing_payment_days}</strong></div>
    </div>}
    {data && <div className="attendance-layout"><section className="panel"><h3>Contratistas de la obra</h3>
      {data.contractors.map((item) => <button type="button" key={item.association_id}
        className={`attendance-company ${item.association_id === selectedId ? "selected" : ""}`}
        onClick={() => { setSelectedId(item.association_id); setWeekNumber(1); }}>
        <strong>{item.contractor}</strong><span>{item.workers.length} trabajadores · {item.roster_status === "included" ? "En base" : "No considerado"}</span>
        <span className={"worker-signal " + (item.weeks.some((w) => w.state === "overdue") ? "red" : "gray")}>{item.weeks.filter((w) => w.state === "overdue").length} semanas atrasadas</span>
      </button>)}
      {data.contractors.length === 0 && <p>No hay contratistas asociados a esta obra.</p>}
    </section>
    <div className="attendance-detail">{contractor ? <>
      <section className="panel"><div className="workers-heading"><div><h3>{contractor.contractor}</h3>
        <p>{contractor.rut || "Sin RUT"} · {contractor.workers.length} trabajadores · {contractor.roster_status === "included" ? "Incluido" : "No considerado"}</p></div>
        <span className={`worker-signal ${contractor.roster_status === "included" ? "green" : "gray"}`}>{contractor.roster_status === "included" ? "En la base mensual" : "Fuera de la base mensual"}</span></div>
        {contractor.roster_updated_at && <p>Base modificada por {contractor.roster_updated_by} el {timeLabel(contractor.roster_updated_at)}.</p>}
        {contractor.roster_status === "excluded" && <p>Motivo: {contractor.roster_reason || "Contratista no activo"}. Los registros anteriores siguen disponibles.</p>}
        {canEdit && <div className="attendance-roster-form"><label>Motivo para no considerar este mes
          <input value={rosterReason} onChange={(e) => setRosterReason(e.target.value)} placeholder="Ej.: no ingresó a la obra este mes" /></label>
          {contractor.roster_status === "included" ? <button type="button" disabled={busy || !rosterReason.trim()} onClick={() => void updateRoster("excluded")}>No considerar este mes</button>
            : contractor.administrative_status === "active" && <button type="button" disabled={busy} onClick={() => void updateRoster("included")}>Agregar a la base</button>}</div>}
      </section>
      <section className="panel"><h3>Balance mensual por trabajador</h3><div className="table-wrap"><table><thead><tr><th>Trabajador</th><th>RUT</th><th>Ingresos con firma</th><th>Días pagados</th><th>Balance</th></tr></thead><tbody>
        {contractor.workers.map((row) => <tr key={row.assignment_id}><td>{row.name}</td><td>{row.rut || "—"}</td><td>{row.signed_days}</td><td>{row.paid_days ?? "Sin información"}</td><td className={row.difference != null && row.difference > 0 ? "attendance-difference" : ""}>{row.difference == null ? "Pendiente de pago registrado" : row.difference > 0 ? `${row.difference} días firmados sobre lo pagado` : row.difference < 0 ? `${Math.abs(row.difference)} días pagados sobre lo firmado` : "Conciliado"}</td></tr>)}
        {!contractor.workers.length && <tr><td colSpan={5}>Sin trabajadores vinculados. Puede registrar semana sin firmas si corresponde.</td></tr>}
      </tbody></table></div><small>Se cuentan firmas de semanas completadas. Un balance requiere días pagados registrados; no constituye por sí solo una conclusión de deuda.</small></section>
      <section className="panel"><h3>Cinco semanas del mes</h3><div className="attendance-weeks">
        {contractor.weeks.map((item) => <button type="button" key={item.week_number} disabled={item.state === "not_applicable"}
          className={`attendance-week ${item.week_number === weekNumber ? "selected" : ""}`} onClick={() => setWeekNumber(item.week_number)}>
          <strong>Semana {item.week_number}</strong><small>{item.dates.length ? `${dayLabel(item.dates[0])}–${dayLabel(item.dates[item.dates.length - 1])}` : "Sin días este mes"}</small>
          <span className={`worker-signal ${item.severity}`}>{statusLabel[item.state] || item.state}</span>
        </button>)}</div></section>
      {week && week.dates.length > 0 && <section className="panel"><h3>Semana {week.week_number} · firmas diarias</h3>
        <p className={`worker-signal ${week.severity}`}>{statusLabel[week.state] || week.state}</p>
        {week.completed_on_time !== null && week.completed_on_time !== undefined && <p className={`worker-signal ${week.completed_on_time ? "green" : "red"}`}>{week.completed_on_time ? "Cumplió el plazo de ingreso" : "Ingresada fuera de plazo"}</p>}
        {week.due_date && <p>Plazo de ingreso: {dayLabel(week.due_date)}. {week.missing_workers > 0 && `${week.missing_workers} trabajadores aún sin registrar.`}</p>}
        <div className="attendance-provenance"><span>Ingresada por: {week.entered_by || "Pendiente"} · {timeLabel(week.entered_at)}</span>
          <span>Última edición: {week.updated_by || "Pendiente"} · {timeLabel(week.updated_at)}</span>
          <span>Completada por: {week.completed_by || "Pendiente"} · {timeLabel(week.completed_at)} · {week.completed_on_time === null || week.completed_on_time === undefined ? "Plazo pendiente" : week.completed_on_time ? "Cumplió el plazo" : "Fuera de plazo"}</span>
          <span>Revisión: {week.reviewed_by || "Pendiente"} · {timeLabel(week.reviewed_at)}</span></div>
        {week.review_note && <p>Observación: {week.review_note}</p>}
        {week.source_document_id && <a href={api.pdf(week.source_document_id)} target="_blank" rel="noreferrer">Ver respaldo de firmas</a>}
        <div className="table-wrap"><table className="attendance-grid"><thead><tr><th>Trabajador</th>{week.dates.map((day) => <th key={day}>{dayLabel(day).slice(0, 5)}</th>)}<th>No considerar</th><th>Motivo</th></tr></thead><tbody>
          {entries.map((entry) => <tr key={entry.worker_assignment_id}><th scope="row">{entry.worker}<small>{entry.rut}</small></th>
            {week.dates.map((day) => <td key={day}><input type="checkbox" aria-label={`${entry.worker} firmó ${dayLabel(day)}`} disabled={!canEdit || contractor.roster_status !== "included" || day > new Intl.DateTimeFormat("sv-SE", { timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date()) || entry.excluded}
              checked={entry.signed_dates.includes(day)} onChange={(e) => changeEntry(entry.worker_assignment_id, (row) => ({ ...row, signed_dates: e.target.checked ? [...row.signed_dates, day] : row.signed_dates.filter((value) => value !== day) }))} /></td>)}
            <td><input type="checkbox" aria-label={`No considerar a ${entry.worker} esta semana`} checked={entry.excluded} disabled={!canEdit || contractor.roster_status !== "included"} onChange={(e) => changeEntry(entry.worker_assignment_id, (row) => ({ ...row, excluded: e.target.checked, signed_dates: e.target.checked ? [] : row.signed_dates }))} /></td>
            <td><input aria-label={`Motivo para ${entry.worker}`} value={entry.reason} disabled={!canEdit || contractor.roster_status !== "included" || !entry.excluded} onChange={(e) => changeEntry(entry.worker_assignment_id, (row) => ({ ...row, reason: e.target.value }))} placeholder={entry.excluded ? "Motivo obligatorio" : "—"} /></td></tr>)}
          {!entries.length && <tr><td colSpan={week.dates.length + 3}>Sin trabajadores para esta semana.</td></tr>}
        </tbody></table></div>
        {canEdit && contractor.roster_status === "included" && <div className="attendance-actions"><label>Respaldo de firmas (PDF o imagen)
            <input type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>
          <label>Nota de ingreso o motivo cuando no hay archivo
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Origen de las firmas o motivo detallado" /></label>
          <div><button type="button" disabled={busy} onClick={() => void saveWeek(false)}>Guardar borrador</button>
            <button type="button" className="primary" disabled={busy || week.dates[week.dates.length - 1] > new Intl.DateTimeFormat("sv-SE", { timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())} onClick={() => void saveWeek(true)}>Completar semana</button></div>
          <small>Completar registra cero firmas para las personas sin casillas marcadas. Requiere respaldo o nota detallada. Puede corregirse con trazabilidad.</small></div>}
        {canReview && week.id && week.saved_state === "completed" && <div className="attendance-actions"><label>Observación de revisión
          <input value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="Si observa, indique el motivo" /></label>
          <div><button type="button" disabled={busy} onClick={() => void review("approved")}>Marcar conforme</button>
            <button type="button" disabled={busy || !reviewNote.trim()} onClick={() => void review("observed")}>Observar</button></div></div>}
      </section>}
    </> : <section className="panel empty">Elige un contratista para revisar sus cinco semanas y el balance de trabajadores.</section>}</div></div>}
  </div>;
}
