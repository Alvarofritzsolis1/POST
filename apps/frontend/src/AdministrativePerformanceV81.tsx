import { useEffect, useState } from "react";
import { request } from "./api";
import type { Site } from "./opsApi";
import "./performance-v81.css";

type Account = { id: string; name: string; role: string; site_ids: string[]; enabled: boolean };
type Duty = { id: string; association_id: string; week_number: number; deadline_at: string; exempt: boolean; completed_at: string | null };
type Result = {
  user_id: string; name: string; required: number; completed: number; punctual: number;
  completion: number | null; punctuality: number | null; grade: number | null;
  overdue: number; delivered_late: number; exempt: number; duties: Duty[];
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
  async function execute(url: string, body: object, success: string) {
    setError(""); setNotice(""); setBusy(true);
    try {
      await request(url, { method: "POST", body: JSON.stringify(body) });
      setNotice(success); setRevision((v) => v + 1);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
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
      </div>
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
