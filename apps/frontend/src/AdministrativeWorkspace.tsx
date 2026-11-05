import { useEffect, useState } from "react";
import type { Profile } from "./api";
import { request } from "./api";
import { opsApi, type Site } from "./opsApi";
import AdministrativeControlV92 from "./AdministrativeControlV92";
import ContractAlerts from "./ContractAlerts";
import "./administrative.css";

type AdministrativeProfile = { name: string; site_ids: string[] };
const currentPeriod = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "America/Santiago", year: "numeric", month: "2-digit",
}).format(new Date());

export default function AdministrativeWorkspace({ user, version, logout }: {
  user: Profile; version: string | null; logout: () => void;
}) {
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState(() => new URLSearchParams(window.location.search).get("attendance_site") || "");
  const [period, setPeriod] = useState(() => new URLSearchParams(window.location.search).get("attendance_period") || currentPeriod());
  const [name, setName] = useState("");
  const [tab, setTab] = useState<"attendance" | "contracts" | "severance" | "staff" | "performance" | "alerts">("attendance");
  const [detailOpen, setDetailOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void Promise.all([opsApi.sites(), request<AdministrativeProfile>("/network/profile")])
      .then(([all, profile]) => {
        if (!active) return;
        const assigned = new Set(profile.site_ids);
        const available = all.filter((site) => assigned.has(site.id));
        setSites(available);
        setSiteId((previous) => available.some((site) => site.id === previous)
          ? previous : available[0]?.id || "");
        setName(profile.name || "Administrativo");
      })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : String(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  return <main className="administrative-app">
    <header className="administrative-topbar">
      <div><strong>GALANT POST</strong><span>Control de Asistencia · v{version || "—"}</span></div>
      <div className="administrative-user"><span>{name || user.email}</span><button type="button" onClick={logout}>Cerrar sesión</button></div>
    </header>
    <div className="administrative-content">
      {!detailOpen && <div className="administrative-heading">
        <div><h1>Control laboral de la obra</h1><p>Contratistas activos, asistencia semanal, dotación, contratos y finiquitos en un solo lugar.</p></div>
        <div className="administrative-filters">
          <label>Obra <select value={siteId} onChange={(event) => setSiteId(event.target.value)}
            disabled={!sites.length}>{sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}</select></label>
          <label>Mes <input type="month" value={period} onChange={(event) => setPeriod(event.target.value || currentPeriod())} /></label>
        </div>
      </div>}
      {error && <p className="alert danger" role="alert">{error}</p>}
      {loading ? <p>Cargando tus obras…</p> : !sites.length
        ? <section className="panel"><h2>Sin obras asignadas</h2><p>Un Administrador debe asignarte una obra antes de registrar asistencia.</p></section>
        : <>
          {!detailOpen && <nav aria-label="Opciones administrativas" className="administrative-tabs">
            <button type="button" aria-current={tab === "attendance" ? "page" : undefined} onClick={() => setTab("attendance")}>Asistencia semanal</button>
            <button type="button" aria-current={tab === "contracts" ? "page" : undefined} onClick={() => setTab("contracts")}>Contratos de trabajo</button>
             <button type="button" aria-current={tab === "alerts" ? "page" : undefined} onClick={() => setTab("alerts")}>Alertas contractuales</button>
            <button type="button" aria-current={tab === "severance" ? "page" : undefined} onClick={() => setTab("severance")}>Finiquitos</button>
            <button type="button" aria-current={tab === "staff" ? "page" : undefined} onClick={() => setTab("staff")}>Dotación vigente</button>
            <button type="button" aria-current={tab === "performance" ? "page" : undefined} onClick={() => setTab("performance")}>Mi rendimiento</button>
          </nav>}
          {tab === "alerts" ? <ContractAlerts siteId={siteId} /> :
             <AdministrativeControlV92 siteId={siteId} sites={sites} period={period} tab={tab} role="administrative" onChangeTab={setTab} onDetailChange={setDetailOpen} />}
        </>}
    </div>
  </main>;
}
