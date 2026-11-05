import { useEffect, useState } from "react";
import { request } from "./api";
import type { Site } from "./opsApi";
import AdministrativeControlV92, { type AdministrativeTab } from "./AdministrativeControlV92";
import "./administrative-v92.css";
import "./administrative-v93.css";

type Summary = {
  active_contractors: number; required_revisions: number;
  completed_revisions: number; punctual_revisions: number;
  late_completions: number; pending_revisions: number;
  overdue_revisions: number; completion_percent: number | null;
};
type SiteProgress = Summary & { site_id: string; site_name: string };
type Portfolio = { period: string; sites: SiteProgress[]; totals: Summary };
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : String(reason);
const percent = (value: number | null) => value === null ? "No exigible" : `${value}%`;

export default function AdminAttendanceV93({
  siteId, sites, period, onSiteSelect, onEvaluate,
}: {
  siteId: string; sites: Site[]; period: string;
  onSiteSelect: (id: string) => void; onEvaluate: () => void;
}) {
  const [tab, setTab] = useState<AdministrativeTab>("attendance");
  const [detailOpen, setDetailOpen] = useState(false);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (siteId) return;
    let active = true;
    setLoading(true);
    setError("");
    void request<Portfolio>(`/attendance-v81/portfolio?period=${encodeURIComponent(period)}`)
      .then((data) => { if (active) setPortfolio(data); })
      .catch((reason) => { if (active) { setError(errorText(reason)); setPortfolio(null); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [siteId, period, refresh]);

  useEffect(() => { setTab("attendance"); setDetailOpen(false); }, [siteId]);
  useEffect(() => {
    const update = () => setRefresh((v) => v + 1);
    const timer = window.setInterval(update, 30000);
    window.addEventListener("focus", update);
    window.addEventListener("galant-changed", update);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", update);
      window.removeEventListener("galant-changed", update);
    };
  }, []);

  return <div className="av93-admin">
    {!detailOpen && <div className="av92-title">
      <div>
        <h2>{siteId ? "Control integral de asistencia" : "Control de asistencia · todas las obras"}</h2>
        <p>{siteId ? "La misma matriz utilizada por las administrativas, con supervisión global." :
          "Resumen de obligaciones iniciadas por obra; las semanas futuras no se cuentan como incumplimientos."}</p>
      </div>
      <div className="av93-actions">
        {siteId && <button type="button" className="av92-refresh" onClick={() => onSiteSelect("")}>Todas las obras</button>}
        <button type="button" className="av92-refresh" onClick={onEvaluate}>Evaluar administrativas</button>
        <button type="button" className="av92-refresh" onClick={() => setRefresh((v) => v + 1)}>Actualizar</button>
      </div>
    </div>}
    {siteId ? <>
      {!detailOpen && <nav aria-label="Control laboral del administrador" className="administrative-tabs">
        {([
          ["attendance", "Asistencia semanal"],
          ["contracts", "Contratos de trabajo"],
          ["severance", "Finiquitos"],
          ["staff", "Dotación vigente"],
        ] as const).map(([id, label]) =>
          <button key={id} type="button" aria-current={tab === id ? "page" : undefined}
            onClick={() => setTab(id)}>{label}</button>)}
      </nav>}
      <AdministrativeControlV92 key={siteId} siteId={siteId} sites={sites}
        period={period} tab={tab} role="admin" onChangeTab={setTab} onDetailChange={setDetailOpen} />
    </> : <>
      {error && <p className="alert danger" role="alert">{error}</p>}
      {loading && <p className="av92-muted" role="status">Actualizando el consolidado de obras…</p>}
      {portfolio && <>
        <div className="av92-metrics">
          {([
            ["Contratistas activos", portfolio.totals.active_contractors],
            ["Revisiones exigibles", portfolio.totals.required_revisions],
            ["Completadas", portfolio.totals.completed_revisions],
            ["Pendientes", portfolio.totals.pending_revisions],
            ["Atrasadas", portfolio.totals.overdue_revisions],
            ["Completadas tarde", portfolio.totals.late_completions],
            ["Avance mensual", percent(portfolio.totals.completion_percent)],
          ] as [string, number | string][]).map(([label, value]) =>
            <div className="av92-metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}
        </div>
        <section className="av93-site-section">
          <div className="av92-section-head">
            <div><h3>Cumplimiento por obra</h3><p>Selecciona cualquier obra para abrir todos sus contratistas y la matriz mensual.</p></div>
          </div>
          <div className="av93-site-list">
            {portfolio.sites.map((row) => <button type="button"
              key={row.site_id} className="av93-site" onClick={() => onSiteSelect(row.site_id)}>
              <span className="av93-site-head"><strong>{row.site_name}</strong><span>Ver contratistas</span></span>
              <span className="av93-site-metrics">
                <span><b>{row.active_contractors}</b> contratistas</span>
                <span><b>{row.completed_revisions}</b> revisiones completas</span>
                <span><b>{row.pending_revisions}</b> pendientes</span>
                <span><b>{row.overdue_revisions}</b> atrasadas</span>
              </span>
              <span className="av93-site-progress">
                <span><b>Avance {percent(row.completion_percent)}</b><small>{row.required_revisions} revisiones exigibles</small></span>
                <span className="av93-track" aria-hidden="true"><span style={{width: `${row.completion_percent ?? 0}%`}} /></span>
              </span>
            </button>)}
            {!portfolio.sites.length && <p className="av92-empty">No hay obras registradas en esta organización.</p>}
          </div>
        </section>
      </>}
    </>}
  </div>;
}
