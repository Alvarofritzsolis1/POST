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

export default function WeeklyAttendanceV81({ siteId, sites, period, canEdit, canReview, selectedAssociationId, preferredWeekNumber, onSaved, onDirtyChange }: {
  siteId: string; sites: Site[]; period: string; canEdit: boolean; canReview: boolean;
  selectedAssociationId?: string; preferredWeekNumber?: number | null; onSaved?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
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
  const [dirty, setDirty] = useState(false);
  const markDirty = (value: boolean) => { setDirty(value); onDirtyChange?.(value); };
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
  useEffect(() => { setContractorId(selectedAssociationId || ""); setWeekNumber(preferredWeekNumber || 1); setSearch(""); }, [activeSite, period, selectedAssociationId, preferredWeekNumber]);
  const contractor = data?.contractors.find((row) => row.association_id === contractorId);
  // Keep backend week numbers stable for saved evidence; show only weeks with workdays.
  const visibleWeeks = (contractor?.weeks || []).filter((item) => item.dates.length > 0);
  const week = visibleWeeks.find((row) => row.week_number === weekNumber) || visibleWeeks[0];
  const displayWeekNumber = visibleWeeks.findIndex((item) => item.week_number === week?.week_number) + 1;
  const todayChile = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
  useEffect(() => {
    setEntries(copy(week?.entries || []));
    setNotes(week?.notes?.startsWith("Migrado desde calendario antiguo") ? "" : week?.notes || "");
    markDirty(false);
  }, [contractorId, weekNumber, week?.revision, revision]);
  useEffect(() => {
    const warnOnLeave = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnOnLeave);
    return () => window.removeEventListener("beforeunload", warnOnLeave);
  }, [dirty]);

  const missing = entries.filter((row) => !row.recorded).length;
  const recorded = entries.length - missing;
  const presentDays = entries.reduce((sum, row) => sum + (!row.excluded ? row.signed_dates.length : 0), 0);
  const deadlineExpired = week ? Date.now() > new Date(week.due_at).getTime() : false;
  const canSubmit = !!contractor?.included && canEdit && !busy;
  function mark(id: string, action: (row: Entry) => Entry) {
    setEntries((current) => current.map((row) =>
      row.worker_assignment_id === id ? action(row) : row));
    markDirty(true);
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
      markDirty(false);
      setRevision((current) => current + 1);
      onSaved?.();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  return <div className="weekly-v81">
    <header className="weekly-v81-head">
      <div><h2>Asistencia semanal</h2><p>{period} · Solo lunes a viernes. Sábados y domingos no generan obligaciones de asistencia.</p></div>
      {!siteId && <label>Obra <select value={activeSite} onChange={(e) => setLocalSite(e.target.value)}>
        {sites.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
    </header>
    {error && <p className="alert danger" role="alert">{error}</p>}
    {notice && <p className="alert success" role="status">{notice}</p>}
    {!selectedAssociationId && <section className="panel">
      <label className="weekly-v81-search">Buscar contratista por nombre o RUT
        <input autoComplete="off" placeholder="Escribe para buscar…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
      {matches.length > 0 && <div className="weekly-v81-results">
        {matches.map((row) => <button type="button" key={row.association_id}
          className={row.association_id === contractorId ? "selected" : ""}
          onClick={() => { setContractorId(row.association_id); setWeekNumber(1); setSearch(""); setMatches([]); }}>
          <strong>{row.contractor}</strong>
          <span>{row.rut || "RUT pendiente"} · {row.workers} trabajadores</span></button>)}
      </div>}
      {!!search && !matches.length && <p className="muted">No hay resultados coincidentes.</p>}
      {!search && <p className="muted">Busca un contratista para comenzar.</p>}
    </section>}
    {contractor && <div className="weekly-v81-detail">
      <section className="panel">
        <div className="weekly-v81-head"><h3>{contractor.contractor}</h3><span>{contractor.included ? "En base mensual" : "No considerado este mes"}</span></div>
        <p className="weekly-v91-month-summary">{visibleWeeks.length} semanas con días laborales · {visibleWeeks.filter((item) => item.state === "completed_on_time" || item.state === "completed_late").length} completadas · {visibleWeeks.filter((item) => item.state === "overdue").length} atrasadas</p>
        <div className="weekly-v81-tabs">
          {visibleWeeks.map((w, index) => <button type="button" key={w.week_number}
            aria-pressed={week?.week_number === w.week_number}
            className={week?.week_number === w.week_number ? "current" : ""}
            onClick={() => {
              if (dirty && week?.week_number !== w.week_number &&
                !window.confirm("Hay cambios en esta semana sin guardar. ¿Cambiar de semana?")) return;
              markDirty(false);
              setWeekNumber(w.week_number);
            }}>
            <b>Semana {index + 1}</b><small>{fmtDate(w.start_date)} – {fmtDate(w.end_date)}</small>
            <small>{status[w.state] || w.state}</small>
          </button>)}
        </div>
      </section>
      {week && <section className="panel">
        <div className="weekly-v81-head"><h3>Semana {displayWeekNumber}</h3><strong>{status[week.state] || week.state}</strong></div>
        <p>Fecha límite: {fmtTime(week.due_at)}. {week.completed_by && `Completado por ${week.completed_by}.`}</p>
        {week.migrated && week.saved_state !== "completed" && <p className="alert warning" role="status">Registros históricos migrados: verifica los días antes de completar esta semana.</p>}
        {deadlineExpired && !week.completed_at && <p className="alert warning" role="status">Plazo vencido. Puedes ingresar igualmente; se guardará como fuera de plazo y deberás indicar el motivo.</p>}
        <div className="weekly-v91-progress" role="status" aria-live="polite">
          <strong>{recorded} de {entries.length} trabajadores registrados</strong>
          <span>{presentDays} días marcados · {missing} pendientes</span>
          <div className="weekly-v91-meter" aria-hidden="true"><span style={{ width: entries.length ? (recorded / entries.length * 100) + "%" : "100%" }} /></div>
        </div>
        <div className="weekly-v91-workers">
          {entries.map((row) => {
            const availableDays = week.dates.filter((day) => day <= todayChile);
            return <article className={"weekly-v91-worker " + (row.recorded ? "is-recorded" : "is-pending")} key={row.worker_assignment_id}>
              <div className="weekly-v91-worker-head">
                <div><strong>{row.worker}</strong><small>{row.rut || "Sin RUT"}</small></div>
                <span className={"weekly-v91-state " + (row.recorded ? "ok" : "pending")}>
                  {row.excluded ? "Excluido" : !row.recorded ? "Sin registrar" : row.signed_dates.length ? row.signed_dates.length + " días" : "0 días"}
                </span>
              </div>
              <fieldset className="weekly-v91-days" disabled={!canSubmit || row.excluded}>
                <legend>Días de asistencia</legend>
                {week.dates.map((day) => <label key={day} className={"weekly-v91-day " + (row.signed_dates.includes(day) ? "checked" : "")}>
                  <span>{new Intl.DateTimeFormat("es-CL", { weekday: "short", timeZone: "UTC" }).format(new Date(day + "T12:00:00Z"))} <b>{fmtDate(day).slice(0, 5)}</b></span>
                  <input type="checkbox" checked={row.signed_dates.includes(day)}
                    aria-label={row.worker + " asistió el " + fmtDate(day)}
                    disabled={day > todayChile}
                    onChange={(e) => mark(row.worker_assignment_id, (current) => ({
                      ...current, recorded: true, excluded: false,
                      signed_dates: e.target.checked ? [...current.signed_dates, day] : current.signed_dates.filter((d) => d !== day),
                    }))} />
                </label>)}
              </fieldset>
              <div className="weekly-v91-worker-actions">
                <button type="button" disabled={!canSubmit || !availableDays.length}
                  onClick={() => mark(row.worker_assignment_id, (current) => ({
                    ...current, recorded: true, excluded: false, signed_dates: availableDays, reason: "",
                  }))}>Marcar días disponibles</button>
                <button type="button" disabled={!canSubmit}
                  onClick={() => mark(row.worker_assignment_id, (current) => ({
                    ...current, recorded: true, excluded: false, signed_dates: [], reason: "",
                  }))}>Registrar 0 días</button>
                <label className="weekly-v91-exclusion"><input type="checkbox" disabled={!canSubmit}
                  checked={row.excluded} onChange={(e) => mark(row.worker_assignment_id, (current) => ({
                    ...current, recorded: e.target.checked || current.recorded, excluded: e.target.checked,
                    signed_dates: e.target.checked ? [] : current.signed_dates,
                    reason: e.target.checked ? current.reason : "",
                  }))} /> Excluir trabajador</label>
              </div>
              {row.excluded && <label className="weekly-v91-reason">Motivo de exclusión (obligatorio)
                <input value={row.reason} disabled={!canSubmit} placeholder="Describe el motivo de exclusión"
                  onChange={(e) => mark(row.worker_assignment_id, (current) => ({ ...current, reason: e.target.value }))} />
              </label>}
            </article>;
          })}
        </div>
        <p className="muted">{missing} trabajadores aún sin registrar. Pendiente no equivale a cero.</p>
        {canEdit && contractor.included && <div className="weekly-v81-save">
          <label>Observación o motivo del atraso
            <textarea rows={2} value={notes} onChange={(e) => { setNotes(e.target.value); markDirty(true); }}
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
