import { useEffect, useState } from "react";
import type { Site } from "./opsApi";
import { request } from "./api";
import "./weekly-v81.css";

type Entry = { worker_assignment_id: string; worker: string; rut: string | null; signed_dates: string[]; excluded: boolean; reason: string; recorded: boolean };
type Week = { id: string | null; week_number: number; start_date: string; end_date: string; dates: string[]; state: string; saved_state: string; due_at: string; revision: number; migrated: boolean; notes: string; missing_workers: number; entered_by: string | null; completed_by: string | null; completed_at: string | null; completed_on_time: boolean | null; entries: Entry[] };
type Contractor = { association_id: string; contractor: string; rut: string | null; included: boolean; workers: { assignment_id: string; name: string; rut: string | null; signed_days: number; paid_days?: number | null; difference?: number | null }[]; weeks: Week[] };
type Roster = { site_id: string; period: string; contractors: Contractor[]; week_count: number };
type SearchItem = { association_id: string; contractor: string; rut: string | null; workers: number; active: boolean };

const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const errorText = (v: unknown) => v instanceof Error ? v.message : String(v);
const fmtDate = (iso: string) => iso.split("-").reverse().join("/");
const fmtTime = (iso: string) => new Date(iso).toLocaleString("es-CL", { timeZone: "America/Santiago", dateStyle: "short", timeStyle: "short" });
const status: Record<string, string> = {
  excluded: "No considerado", not_required: "No exigible", completed_on_time: "Registrado a tiempo",
  completed_late: "Registrado fuera de plazo", needs_legacy_review: "Histórico: revisar",
  overdue: "Pendiente atrasado", draft: "Borrador", pending: "Pendiente",
};

export default function WeeklyAttendanceV81({ siteId, sites, period, canEdit, canReview }: {
  siteId: string; sites: Site[]; period: string; canEdit: boolean; canReview: boolean;
}) {
  const [localSite, setLocalSite] = useState("");
  const [data, setData] = useState<Roster | null>(null);
  const [matches, setMatches] = useState<SearchItem[]>([]);
  const [search, setSearch] = useState("");
  const [contractorId, setContractorId] = useState("");
  const [weekNumber, setWeekNumber] = useState(1);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const activeSite = siteId || localSite || sites[0]?.id || "";

  useEffect(() => {
    if (!activeSite || !contractorId) { setData(null); return; }
    let active = true;
    void request<Roster>(`/attendance-v81/roster?site_id=${encodeURIComponent(activeSite)}&period=${encodeURIComponent(period)}&association_id=${encodeURIComponent(contractorId)}`)
      .then((result) => { if (active) { setData(result); setError(""); } })
      .catch((reason) => { if (active) { setError(errorText(reason)); setData(null); } });
    return () => { active = false; };
  }, [activeSite, period, contractorId, revision]);
  useEffect(() => {
    if (!activeSite || !search.trim()) { setMatches([]); return; }
    let active = true;
    const timer = window.setTimeout(() => {
      void request<{items: SearchItem[]}>(`/attendance-v81/contractors?site_id=${encodeURIComponent(activeSite)}&q=${encodeURIComponent(search.trim())}`)
        .then((result) => { if (active) setMatches(result.items); })
        .catch((reason) => { if (active) setError(errorText(reason)); });
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [activeSite, search]);
  useEffect(() => { setContractorId(""); setWeekNumber(1); setSearch(""); }, [activeSite, period]);
  const contractor = data?.contractors.find((row) => row.association_id === contractorId);
  const week = contractor?.weeks.find((row) => row.week_number === weekNumber);
  useEffect(() => {
    setEntries(copy(week?.entries || []));
    setNotes(week?.notes?.startsWith("Migrado desde calendario antiguo") ? "" : week?.notes || "");
  }, [contractorId, weekNumber, week?.revision, revision]);

   const missing = entries.filter((row) => !row.recorded).length;
  const deadlineExpired = week ? Date.now() > new Date(week.due_at).getTime() : false;
  const canSubmit = !!contractor?.included && canEdit && !busy;
  function mark(id: string, action: (row: Entry) => Entry) {
    setEntries((current) => current.map((row) =>
      row.worker_assignment_id === id ? action(row) : row));
  }
  async function save(complete: boolean) {
    if (!week || !contractor) return;
    setError(""); setNotice("");
    if (complete && missing) { setError("Completa cada trabajador: indica días, cero días o una exclusión justificada."); return; }
    if (complete && deadlineExpired && !week.completed_at && notes.trim().length < 10) {
      setError("Registro fuera de plazo: agrega un motivo de al menos 10 caracteres."); return;
    }
    setBusy(true);
    try {
      await request("/attendance-v81/weeks", {
        method: "PUT", body: JSON.stringify({
          association_id: contractor.association_id, period, week_number: week.week_number,
          revision: week.revision, complete, notes,
          entries: entries.filter((entry) => entry.recorded).map((entry) => ({
            worker_assignment_id: entry.worker_assignment_id, signed_dates: entry.signed_dates,
            excluded: entry.excluded, reason: entry.reason,
          })),
        }),
      });
      setNotice(complete ? "Semana completada y registrada con trazabilidad." : "Borrador guardado.");
      setRevision((current) => current + 1);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  return <div className="weekly-v81">
    <header className="weekly-v81-head">
      <div><h2>Asistencia semanal</h2><p>{period} · Las semanas se calculan de lunes a domingo, con cortes de mes.</p></div>
      {!siteId && <label>Obra <select value={activeSite} onChange={(e) => setLocalSite(e.target.value)}>
        {sites.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
    </header>
    {error && <p className="alert danger" role="alert">{error}</p>}
    {notice && <p className="alert success" role="status">{notice}</p>}
    <section className="panel">
      <label className="weekly-v81-search">Buscar contratista por nombre o RUT
        <input autoComplete="off" placeholder="Escribe para buscar…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
      {matches.length > 0 && <div className="weekly-v81-results">
        {matches.map((row) => <button type="button" key={row.association_id}
          className={row.association_id === contractorId ? "selected" : ""}
          onClick={() => { setContractorId(row.association_id); setWeekNumber(1); setSearch(row.contractor); }}>
          <strong>{row.contractor}</strong>
          <span>{row.rut || "RUT pendiente"} · {row.workers} trabajadores</span></button>)}
      </div>}
      {!!search && !matches.length && <p className="muted">No hay resultados coincidentes.</p>}
      {!search && <p className="muted">Busca un contratista para comenzar.</p>}
    </section>
    {contractor && <div className="weekly-v81-detail">
      <section className="panel">
        <div className="weekly-v81-head"><h3>{contractor.contractor}</h3><span>{contractor.included ? "En base mensual" : "No considerado este mes"}</span></div>
        <div className="weekly-v81-tabs">
          {contractor.weeks.map((w) => <button type="button" key={w.week_number}
            className={weekNumber === w.week_number ? "current" : ""}
            onClick={() => setWeekNumber(w.week_number)}>
            <b>Semana {w.week_number}</b><small>{fmtDate(w.start_date)} – {fmtDate(w.end_date)}</small>
            <small>{status[w.state] || w.state}</small>
          </button>)}
        </div>
      </section>
      {week && <section className="panel">
        <div className="weekly-v81-head"><h3>Semana {week.week_number}</h3><strong>{status[week.state] || week.state}</strong></div>
        <p>Fecha límite: {fmtTime(week.due_at)}. {week.completed_by && `Completado por ${week.completed_by}.`}</p>
        {week.migrated && week.saved_state !== "completed" && <p className="alert warning" role="status">Registros históricos migrados: verifica los días antes de completar esta semana.</p>}
        {deadlineExpired && !week.completed_at && <p className="alert warning" role="status">Plazo vencido. Puedes ingresar igualmente; se guardará como fuera de plazo y deberás indicar el motivo.</p>}
        <div className="weekly-v81-scroll"><table className="weekly-v81-grid"><thead><tr><th>Trabajador</th>
          {week.dates.map((day) => <th key={day}>{fmtDate(day).slice(0, 5)}</th>)}
          <th>Registrar cero</th><th>Excluir</th><th>Motivo</th></tr></thead>
          <tbody>{entries.map((row) => <tr key={row.worker_assignment_id}>
            <th scope="row">{row.worker}<small>{row.rut || "Sin RUT"}</small></th>
            {week.dates.map((day) => <td key={day}><input type="checkbox"
              aria-label={`${row.worker} asistió el ${fmtDate(day)}`}
              checked={row.signed_dates.includes(day)} disabled={!canSubmit || row.excluded || day > new Intl.DateTimeFormat("sv-SE", {
                timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit"
              }).format(new Date())}
              onChange={(e) => mark(row.worker_assignment_id, (current) => ({
                ...current, recorded: true, signed_dates: e.target.checked
                  ? [...current.signed_dates, day] : current.signed_dates.filter((value) => value !== day),
              }))} /></td>)}
            <td><button type="button" disabled={!canSubmit} aria-label={`Registrar cero días para ${row.worker}`}
              onClick={() => mark(row.worker_assignment_id, (current) => ({
                ...current, recorded: true, excluded: false, signed_dates: [], reason: "",
              }))}>0 días</button></td>
            <td><input type="checkbox" aria-label={`Excluir a ${row.worker}`} disabled={!canSubmit}
              checked={row.excluded} onChange={(e) => mark(row.worker_assignment_id, (current) => ({
                ...current, recorded: e.target.checked || current.recorded,
                excluded: e.target.checked, signed_dates: e.target.checked ? [] : current.signed_dates,
              }))} /></td>
            <td><input aria-label={`Motivo de exclusión de ${row.worker}`} value={row.reason}
              disabled={!canSubmit || !row.excluded} placeholder={row.excluded ? "Obligatorio" : "—"}
              onChange={(e) => mark(row.worker_assignment_id, (current) => ({
                ...current, reason: e.target.value,
              }))} /></td>
          </tr>)}</tbody></table></div>
        <p className="muted">{missing} trabajadores aún sin registrar. Pendiente no equivale a cero.</p>
        {canEdit && contractor.included && <div className="weekly-v81-save">
          <label>Observación o motivo del atraso
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Obligatorio si se entrega fuera de plazo" /></label>
          <div><button disabled={!canSubmit} onClick={() => void save(false)}>Guardar borrador</button>
            <button className="primary" disabled={!canSubmit || missing > 0}
              onClick={() => void save(true)}>Completar semana</button></div>
        </div>}
      </section>}
      {canReview && <section className="panel"><h3>Consolidado mensual para cuadre previsional</h3>
        <div className="weekly-v81-scroll"><table><thead><tr><th>Trabajador</th><th>Días registrados</th><th>Días pagados</th><th>Diferencia</th></tr></thead>
          <tbody>{contractor.workers.map((row) => <tr key={row.assignment_id}>
            <td>{row.name}</td><td>{row.signed_days}</td>
            <td>{row.paid_days ?? "Pendiente"}</td><td>{row.difference ?? "Por revisar"}</td>
          </tr>)}</tbody></table></div>
        <p className="muted">El cuadro refleja días firmados; una diferencia no acredita por sí sola deuda previsional.</p>
      </section>}
    </div>}
  </div>;
}
