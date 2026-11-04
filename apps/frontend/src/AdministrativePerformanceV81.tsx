import { useEffect, useState } from "react";
import { request } from "./api";
import type { Site } from "./opsApi";
import "./performance-v81.css";

type Account = { id: string; name: string; role: string; site_ids: string[]; enabled: boolean };
type Duty = { id: string; association_id: string; contractor: string; week_number: number; deadline_at: string; exempt: boolean; completed_at: string | null };
type Result = {
  user_id: string; name: string; required: number; completed: number; punctual: number;
  completion: number | null; punctuality: number | null; grade: number | null;
  overdue: number; delivered_late: number; exempt: number; duties: Duty[];
  login_count: number; last_login_at: string | null;
  approved: { revision: number; grade: number | null; approved_at: string; observations: string } | null;
};
const message = (e: unknown) => e instanceof Error ? e.message : String(e);

export default function AdministrativePerformance({ sites, period }: { sites: Site[]; period: string }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [userId, setUserId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [rows, setRows] = useState<Result[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [graceDays, setGraceDays] = useState(1);
  const [cutoff, setCutoff] = useState("23:59");
  const [weight, setWeight] = useState("0.70");
  const [dutySearch, setDutySearch] = useState("");
  const [dutyReasons, setDutyReasons] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    void request<Account[]>("/network/users")
      .then((result) => { if (active) setAccounts(result.filter((u) => u.role === "administrative")); })
      .catch((e) => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    void request<{ rows: Result[] }>(`/attendance-v81/evaluations?period=${encodeURIComponent(period)}`)
      .then((result) => { if (active) setRows(result.rows); })
      .catch((e) => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [period, revision]);
  useEffect(() => {
    if (!siteId) return;
    let active = true;
    void request<{grace_days: number; cutoff: string; completion_weight: number}>(`/attendance-v81/settings?site_id=${encodeURIComponent(siteId)}`)
      .then((result) => { if (active) {
        setGraceDays(result.grace_days); setCutoff(result.cutoff);
        setWeight(result.completion_weight.toString());
      } }).catch((e) => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [siteId]);
  async function execute(url: string, body: object, success: string, method: "POST" | "PUT" = "POST") {
    setError(""); setNotice(""); setBusy(true);
    try {
      await request(url, { method, body: JSON.stringify(body) });
      setNotice(success); setRevision((v) => v + 1);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function changeDuty(duty: Duty, makeExempt: boolean) {
    const reason = dutyReasons[duty.id]?.trim() || "";
    if (makeExempt && reason.length < 10) {
      setError("Explica el motivo de la exención (mínimo 10 caracteres).");
      return;
    }
    setBusy(true); setError(""); setNotice("");
    try {
      await request(`/attendance-v81/duties/${encodeURIComponent(duty.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ exempt: makeExempt, exemption_reason: makeExempt ? reason : "" }),
      });
      setNotice(makeExempt ? "Obligación justificada; no se incluirá en la nota."
                          : "Obligación nuevamente exigible.");
      setRevision((value) => value + 1);
    } catch (cause) { setError(message(cause)); } finally { setBusy(false); }
  }
  const people = accounts.filter((row) => row.enabled && (siteId ? row.site_ids.includes(siteId) : true));
  return <section className="performance-v81">
    <div className="performance-heading"><h2>Evaluación de cumplimiento administrativo</h2>
      <p>Mes {period}. El desempeño se evalúa por obligaciones semanales exigibles, no por visitas a la plataforma.</p>
    </div>
    <section className="panel performance-assign">
      <h3>Asignar obligaciones semanales</h3>
      <p>Antes de evaluar, asigna los contratistas de cada obra al Administrativo responsable. No se duplicarán obligaciones ya creadas.</p>
      <div className="performance-fields">
        <label>Obra <select value={siteId} onChange={(e) => { setSiteId(e.target.value); setUserId(""); }}>
          <option value="">Seleccionar obra</option>{sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}</select></label>
        <label>Administrativo <select value={userId} onChange={(e) => setUserId(e.target.value)}>
          <option value="">Seleccionar responsable</option>{people.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <button disabled={busy || !siteId || !userId} onClick={() => void execute("/attendance-v81/duties/generate",
          { site_id: siteId, period, user_id: userId }, "Obligaciones generadas o verificadas.")}>
          Generar obligaciones</button>
      </div>
    </section>
    {siteId && <section className="panel performance-assign">
      <h3>Configuración de plazos y calificación</h3>
      <p>Los plazos se aplican a las nuevas obligaciones. Las entregas ya asignadas conservan su fecha límite original.</p>
      <div className="performance-fields">
        <label>Días después del cierre semanal <input type="number" min={0} max={31} value={graceDays}
          onChange={(e) => setGraceDays(Number(e.target.value))} /></label>
        <label>Hora límite (Chile) <input type="time" value={cutoff}
          onChange={(e) => setCutoff(e.target.value)} /></label>
        <label>Peso del cumplimiento (0 a 1) <input type="number" step="0.05" min={0} max={1}
          value={weight} onChange={(e) => setWeight(e.target.value)} /></label>
        <button disabled={busy || graceDays < 0 || graceDays > 31 || Number(weight) < 0 || Number(weight) > 1}
          onClick={() => void execute("/attendance-v81/settings",
            { site_id: siteId, grace_days: graceDays, cutoff, completion_weight: Number(weight) },
            "Configuración guardada.", "PUT")}>Guardar configuración</button>
      </div>
    </section>}
    {error && <p role="alert" className="alert danger">{error}</p>}
    {notice && <p role="status" className="alert success">{notice}</p>}
    <div className="performance-list">{rows.map((row) => <section className="panel" key={row.user_id}>
      <div className="performance-card-head"><div><h3>{row.name}</h3><p>{row.required} entregas exigibles · {row.exempt} justificadas</p></div>
        <strong className="performance-grade">{row.grade === null ? "Sin evaluar" : `Nota ${row.grade.toFixed(1)}`}</strong></div>
      <div className="performance-metrics">
        <div><small>Cumplimiento</small><b>{row.completion === null ? "—" : row.completion.toFixed(1) + "%"}</b></div>
        <div><small>Puntualidad</small><b>{row.punctuality === null ? "—" : row.punctuality.toFixed(1) + "%"}</b></div>
        <div><small>Entregas atrasadas</small><b>{row.delivered_late}</b></div>
        <div><small>Vencidas pendientes</small><b>{row.overdue}</b></div>
        <div><small>Ingresos a la plataforma</small><b>{row.login_count}</b>
          <small>{row.last_login_at ? new Date(row.last_login_at).toLocaleString("es-CL",
            { timeZone: "America/Santiago", dateStyle: "short", timeStyle: "short" })
            : "Sin ingresos durante este mes"}</small></div>
      </div>
      <p className="muted">Los ingresos a la plataforma son informativos y no afectan la nota.</p>
      <details className="performance-duties"><summary>Revisar obligaciones ({row.duties.length}) y justificar semanas sin movimiento</summary>
        <label>Buscar contratista
          <input type="search" value={dutySearch} onChange={(event) => setDutySearch(event.target.value)}
            placeholder="Nombre del contratista o número de semana" />
        </label>
        <div className="performance-duty-list">
          {row.duties.filter((duty) => (
            duty.contractor + " semana " + duty.week_number
          ).toLocaleLowerCase("es-CL").includes(dutySearch.trim().toLocaleLowerCase("es-CL")))
            .slice(0, 40).map((duty) => <div className="performance-duty" key={duty.id}>
              <div><b>{duty.contractor}</b><small>Semana {duty.week_number} · {
                duty.exempt ? "No exigible" : duty.completed_at ? "Registrado" : "Pendiente"
              }</small></div>
              {duty.exempt ? <button type="button" disabled={busy}
                onClick={() => void changeDuty(duty, false)}>Volver a exigir</button>
              : <div className="performance-justify">
                <input aria-label={`Motivo de exención para ${duty.contractor} semana ${duty.week_number}`}
                  placeholder="Motivo: sin movimientos u otra justificación" value={dutyReasons[duty.id] || ""}
                  onChange={(event) => setDutyReasons((current) => ({
                    ...current, [duty.id]: event.target.value,
                  }))} />
                <button type="button" disabled={busy || (dutyReasons[duty.id] || "").trim().length < 10}
                  onClick={() => void changeDuty(duty, true)}>Justificar</button>
              </div>}
            </div>)}
        </div>
        {row.duties.length > 40 && <small>Se muestran hasta 40 coincidencias; utiliza el buscador para otras obligaciones.</small>}
      </details>
      {row.approved && <p className="performance-approved">Última evaluación aprobada: versión {row.approved.revision} · nota {row.approved.grade?.toFixed(1) ?? "—"}</p>}
      <div className="performance-actions">
        <button disabled={busy || row.required === 0} onClick={() => void execute(
          "/attendance-v81/evaluations/finalize", { period, user_id: row.user_id },
          "Evaluación de " + row.name + " aprobada y guardada.")}>
          Aprobar evaluación mensual</button>
      </div>
    </section>)}</div>
  </section>;
}
