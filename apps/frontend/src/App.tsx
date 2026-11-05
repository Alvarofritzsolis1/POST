import { lazy, Suspense, useCallback, useEffect, useState, useRef } from "react";
import {
  Building2,
  LayoutDashboard,
  Users,
  FileCheck2,
  CalendarDays,
  FileSpreadsheet,
  BarChart3,
  Settings as SettingsIcon,
  Network,
  RefreshCcw,
  Menu,
} from "lucide-react";
import { api, type Profile } from "./api";
import { opsApi, type Site } from "./opsApi";
import { Login } from "./DocumentAnalysis";
import DocumentAnalysis from "./DocumentAnalysis";
import Operations from "./Operations";
import ErrorBoundary from "./ErrorBoundary";
import Workers from "./Workers";
import AdminAttendanceV93 from "./AdminAttendanceV93";
import AdministrativePerformanceV81 from "./AdministrativePerformanceV81";
import AdministrativeWorkspace from "./AdministrativeWorkspace";
import ControlCenter from "./ControlCenter";
import BulkImport from "./BulkImport";
import Settings from "./Settings";
const GeneralConfiguration = lazy(() => import("./GeneralConfiguration"));
import RedDeObras, { ResidentNetwork } from "./Network";
import { NetworkAccountMenu, NetworkPasswordScreen } from "./NetworkAccounts";
import {
  read,
  send,
  type Contribution,
  type Summary,
  type MatrixRow,
  type OrgProfile,
  type Preferences,
} from "./platformApi";
const nav = [
  ["home", "Inicio", LayoutDashboard],
  ["network", "Red de Obras", Network],
  ["contractors", "Contratistas", Building2],
  ["workers", "Trabajadores", Users],
  ["attendance", "Control de asistencia", CalendarDays],
  ["evaluations", "Evaluación administrativa", BarChart3],
  ["documents", "Control documental", FileCheck2],
  ["contributions", "Cotizaciones y pagos", CalendarDays],
  ["imports", "Importación masiva", FileSpreadsheet],
  ["administration", "Gestión administrativa", CalendarDays],
  ["reports", "Informes", BarChart3],
  ["settings", "Configuración", SettingsIcon],
] as const;
const navGroups = [
  { title: "PRINCIPAL", ids: ["home", "network"] },
  { title: "GESTIÓN OPERATIVA", ids: ["contractors", "workers", "attendance"] },
  { title: "CUMPLIMIENTO", ids: ["documents", "contributions", "evaluations"] },
  { title: "ADMINISTRACIÓN", ids: ["administration", "imports", "reports", "settings"] },
] as const;
const alertCriticalKeys = new Set<string>(["critical_contractors", "workers_expired", "incomplete_contributions", "declared_unpaid", "attendance_overdue"]);
const dashboardUrgentTitles = new Set<string>(["Con observaciones", "Registros con diferencias", "Días faltantes acumulados"]);
const dashboardWarningTitles = new Set<string>(["Documentación pendiente", "Pendientes de confirmación", "Registros sin información", "Trabajadores con observaciones"]);
const number = (v: number | null | undefined) =>
  v == null
    ? "Sin información"
    : v.toLocaleString("es-CL", { maximumFractionDigits: 2 });
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
type Overview = {
  activity: { id: string; kind: string; at: string; actor: string }[];
  classifications: Record<string, number>;
  active_workers: number;
  observed_workers: number;
  up_to_date: number;
  observed: number;
  pending_documents: number;
  contributions: Summary;
  contractors: {
    association_id: string;
    contractor: string;
    classification: string;
    state: string;
    approved: number;
    pending: number;
    applicable: number;
    warnings: string[];
  }[];
};
type LaborAlerts = { summary: Record<string, number>; alerts: { kind: string; severity: string; label: string; site: string; date: string | null; target_id: string; target_section: string }[] };
function App() {
  const [user, setUser] = useState<Profile | null>(null),
    [ready, setReady] = useState(false),
    [version, setVersion] = useState<string | null>(null),
    [revision, setRevision] = useState<string | null>(null),
    [section, setSection] = useState(() => window.location.pathname.startsWith("/admin/configuracion") ? "configuration" : window.location.pathname.startsWith("/contratistas") ? "contractors" : new URLSearchParams(window.location.search).has("attendance_contractor") ? "attendance" : "home"),
    [sites, setSites] = useState<Site[]>([]),
    [site, setSite] = useState(() => new URLSearchParams(window.location.search).get("obra") || new URLSearchParams(window.location.search).get("attendance_site") || ""),
    [period, setPeriod] = useState(() =>
      new URLSearchParams(window.location.search).get("periodo") || new URLSearchParams(window.location.search).get("attendance_period") || new Intl.DateTimeFormat("sv-SE", {
        timeZone: "America/Santiago",
        year: "numeric",
        month: "2-digit",
      }).format(new Date()),
    ),
    [profile, setProfile] = useState<OrgProfile | null>(null),
    [overview, setOverview] = useState<Overview | null>(null),
    [laborAlerts, setLaborAlerts] = useState<LaborAlerts | null>(null),
    [targetWorker, setTargetWorker] = useState(""),
    [findingDraft, setFindingDraft] = useState<{control_id:string;state:string;document_id:string;documented_amount:string;expected_amount:string;observation:string}|null>(null),
    [contributions, setContributions] = useState<{
      rows: Contribution[];
      total: number;
      summary: Summary;
    } | null>(null),
    [matrix, setMatrix] = useState<MatrixRow[]>([]),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [hash, setHash] = useState(window.location.hash),
    [mobileOpen, setMobileOpen] = useState(false),
    [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem("galant-sidebar-collapsed") === "true"),
    [loading, setLoading] = useState(false),
    [search, setSearch] = useState(""),
    [quickNav, setQuickNav] = useState(""),
    [filter, setFilter] = useState("all"),
    [classification, setClassification] = useState("all"),
    [editing, setEditing] = useState<Contribution | null>(null),
    [reviewing, setReviewing] = useState<MatrixRow | null>(null),
    [evidence, setEvidence] = useState(false),
    [sporadic, setSporadic] = useState(false),
    [page, setPage] = useState(0);
  useEffect(() => { window.localStorage.setItem("galant-sidebar-collapsed", String(sidebarCollapsed)); }, [sidebarCollapsed]);
  useEffect(() => {
    const routeChanged = () => {
      const path = window.location.pathname;
      setSection(path.startsWith("/admin/configuracion") ? "configuration" : path.startsWith("/contratistas") ? "contractors" : window.history.state?.galantSection || (new URLSearchParams(window.location.search).has("attendance_contractor") ? "attendance" : "home"));
    };
    window.addEventListener("popstate", routeChanged);
    return () => window.removeEventListener("popstate", routeChanged);
  }, []);
  const refreshGeneration = useRef(0);
  const lastActivity = useRef<string | null>(null);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    const expired = () => {
      setUser(null);
      setOverview(null);
      setContributions(null);
      setMatrix([]);
      setProfile(null);
      setSites([]);
      setEditing(null);
      setReviewing(null);
    };
    window.addEventListener("galant-session-ended", expired);
    return () => window.removeEventListener("galant-session-ended", expired);
  }, []);
  const readonly = false;
  const canEdit = user?.role === "admin";
  const canReview = canEdit;
  const canAttend = canEdit;
  const params =
    "period=" +
    encodeURIComponent(period) +
    (site ? "&site_id=" + encodeURIComponent(site) : "");
  const applyPreferences = useCallback((p: Preferences) => {
    document.documentElement.dataset.theme = p.appearance;
    document.documentElement.dataset.density = p.density;
    setProfile((old) => (old ? { ...old, preferences: p } : old));
  }, []);
  useEffect(() => {
    void api
      .me()
      .then(setUser)
      .catch(() => {})
      .finally(() => setReady(true));
    void api
      .version()
      .then((v) => { setVersion(v.version); setRevision(v.commit); })
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!user || user.role !== "admin") return;
    void Promise.all([opsApi.sites(), read<OrgProfile>("/admin/profile")])
      .then(([s, p]) => {
        setSites(s);
        setProfile(p);
        applyPreferences(p.preferences);
        const requestedSite = new URLSearchParams(window.location.search).get("obra") || new URLSearchParams(window.location.search).get("attendance_site");
        setSite(requestedSite && s.some((entry) => entry.id === requestedSite) ? requestedSite : p.preferences.default_site || "");
      })
      .catch((e) => setError(errorText(e)));
  }, [user, applyPreferences]);
  const refresh = useCallback(async () => {
    if (!user || user.role !== "admin" || section === "network" || section === "configuration") return;
    const generation = ++refreshGeneration.current;
    try {
      const [o, c, m, a] = await Promise.all([
        read<Overview>("/ops/overview?" + params),
        read<{ rows: Contribution[]; total: number; summary: Summary }>(
          "/ops/contributions?" +
            params +
            "&include_sporadic=" +
            sporadic +
            "&limit=50&offset=" +
            page * 50 +
            "&q=" +
            encodeURIComponent(search) +
            "&state=" +
            encodeURIComponent(filter) +
            "&kind=" +
            encodeURIComponent(classification),
        ),
        read<MatrixRow[]>("/ops/document-reviews?" + params),
        section === "home" ? read<LaborAlerts>("/labor/alerts?" + params) : Promise.resolve(null),
      ]);
      if (generation === refreshGeneration.current) {
        if (
          lastActivity.current &&
          o.activity[0]?.id !== lastActivity.current &&
          profile?.preferences.notifications
        )
          setNotice(
            "Hay nueva actividad en tu organización. Los datos se actualizaron.",
          );
        lastActivity.current = o.activity[0]?.id || null;
        setOverview(o);
        setContributions(c);
        setMatrix(m);
        if (a) setLaborAlerts(a);
        setError("");
      }
    } catch (e) {
      if (generation === refreshGeneration.current) setError(errorText(e));
    }
  }, [
    user,
    params,
    sporadic,
    profile?.preferences.notifications,
    page,
    search,
    filter,
    classification,
    section,
  ]);
  useEffect(() => {
    if (!user || user.role !== "admin" || section === "network" || section === "configuration") return;
    let active = true;
    const update = () => {
      // Al volver a una pestaña no forzamos una nueva carga: el sondeo visible conserva los datos.
      if (active && !document.hidden) void refresh();
    };
    setLoading(true);
    void refresh().finally(() => {
      if (active) setLoading(false);
    });
    const timer = setInterval(update, 10000);
    window.addEventListener("galant-changed", update);
    const sitesUpdate = () => {
      void opsApi
        .sites()
        .then(setSites)
        .catch((e) => setError(errorText(e)));
    };
    window.addEventListener("galant-changed", sitesUpdate);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener("galant-changed", update);
      window.removeEventListener("galant-changed", sitesUpdate);
    };
  }, [refresh, user]);
  useEffect(() => {
    setPage(0);
  }, [site, period, search, filter, classification, section]);
  async function logout() {
    try {
      await api.logout();
      setUser(null);
      setProfile(null);
      setSites([]);
      setOverview(null);
      setContributions(null);
      setMatrix([]);
      lastActivity.current = null;
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function save(path: string, body: unknown) {
    try {
      await send(path, body, "PUT");
      setNotice("Control guardado y disponible para la organización.");
      setEditing(null);
      setReviewing(null);
      await refresh();
    } catch (e) {
      setError(errorText(e));
    }
  }
  function go(s: string) {
    if (s === "configuration") {
      window.history.replaceState({ ...window.history.state, galantSection: section }, "", window.location.href);
      window.history.pushState({ galantSection: "configuration", galantConfiguration: true }, "", "/admin/configuracion");
      setSection("configuration");
      return;
    }
    if (window.location.pathname.startsWith("/contratistas") || window.location.pathname.startsWith("/admin/configuracion")) {
      const url = new URL(window.location.href);
      url.pathname = s === "contractors" ? "/contratistas" : "/";
      url.searchParams.delete("obra");
      url.searchParams.delete("periodo");
      window.history.replaceState({}, "", url);
      if (s === "contractors") window.dispatchEvent(new PopStateEvent("popstate"));
    }
    window.history.replaceState({ ...window.history.state, galantSection: s }, "", window.location.href);
    setSection(s);
    setFilter("all");
    setSearch("");
    setMobileOpen(false);
    setError("");
    setNotice("");
  }
  function drill(s: string, value = "all") {
    go(s);
    setFilter(value);
  }
  if (hash.startsWith("#establecer-clave=") || hash === "#recuperar-clave") return <NetworkPasswordScreen hash={hash} done={() => { window.history.replaceState(null, "", window.location.pathname); setHash(""); setUser(null); }} />;
  if (!ready) return <div className="app-loading">Cargando GALANT…</div>;
  if (!user) return <Login onLogin={setUser} version={version} />;
  if (section === "configuration" && user.role !== "admin") return <main className="panel" style={{ margin: "40px auto", maxWidth: 620 }}><h1>Acceso restringido</h1><p>Configuración General está disponible exclusivamente para administradores.</p><button type="button" onClick={() => { window.history.replaceState({}, "", "/"); setSection("home"); }}>← Volver</button></main>;
  if (user.role === "resident") return <ResidentNetwork user={user} version={version} logout={() => void logout()} />;
  if (user.role === "administrative") return <AdministrativeWorkspace user={user} version={version} logout={() => void logout()} />;
  if (section === "configuration" && user.role === "admin") return <ErrorBoundary name="Configuración General"><Suspense fallback={<div className="app-loading">Cargando Configuración General…</div>}><GeneralConfiguration user={user} version={version} logout={() => void logout()} onOpenSettings={() => go("settings")} onBack={() => { if (window.history.state?.galantConfiguration) window.history.back(); else go("settings"); }}/></Suspense></ErrorBoundary>;
  const rows = (contributions?.rows || []).filter(
    (r) =>
      (!search ||
        (r.worker + " " + r.contractor + " " + r.worker_rut)
          .toLowerCase()
          .includes(search.toLowerCase())) &&
      (filter === "all" ||
        r.state === filter ||
        (filter === "payment_confirmed" && r.confirmed) ||
        (filter === "payment_pending" &&
          r.paid_days !== null &&
          !r.confirmed) ||
        (filter === "differences" && (r.missing_days || 0) > 0) ||
        (filter === "declared_unpaid" && r.payment_finding === "declared_unpaid")) &&
      (classification === "all" || r.classification === classification),
  );
  const cards = (overview?.contractors || []).filter(
    (r) =>
      (filter === "all" || r.state === filter) &&
      (classification === "all" || r.classification === classification) &&
      r.contractor.toLowerCase().includes(search.toLowerCase()),
  );
  const docs = matrix.filter(
    (r) =>
      (filter === "all" ||
        r.state === filter ||
        (filter === "pending" &&
          ["pending", "overdue", "schedule_not_configured"].includes(
            r.state,
          ))) &&
      (r.name + " " + r.contractor)
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <div className={"shell platform " + (mobileOpen ? "menu-open" : "") + (sidebarCollapsed ? " sidebar-collapsed" : "")}>
      <aside className="sidebar">
        <div className="brand">
          <Building2 />
          <div>
            <b>GALANT POST</b>
            <small>Gestión de contratistas</small>
          </div>
        </div>
        <p className="sidebar-label">ORGANIZACIÓN COMPARTIDA</p>
        <nav aria-label="Navegación principal">
          {navGroups.map(group => (
            <div className="nav-group" key={group.title}>
              <p className="nav-group-title">{group.title}</p>
              {group.ids.map(id => {
                const entry = nav.find(([key]) => key === id);
                if (!entry) return null;
                const [, label, Icon] = entry;
                return (
                  <button
                    key={id}
                    className={"nav-item " + (section === id ? "active" : "")}
                    aria-current={section === id ? "page" : undefined}
                    aria-label={label}
                    title={sidebarCollapsed ? label : undefined}
                    onClick={() => go(id)}
                  >
                    <Icon size={18} aria-hidden="true" />
                    <span className="v91-nav-label">{label}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <p>{profile?.organization}</p>
          <small>
            v{version} · {revision && revision !== "unbuilt" ? revision.slice(0, 8) + " · " : ""}{" "}
            Administrador
          </small>
        </div>
      </aside>
      {mobileOpen && <button type="button" className="v91-menu-backdrop" aria-label="Cerrar menú de navegación" onClick={() => setMobileOpen(false)} />}
      <main className="main">
        <header className="topbar">
          <button
            className="icon-button menu-toggle"
            aria-label={mobileOpen ? "Cerrar menú" : sidebarCollapsed ? "Expandir menú" : "Contraer menú"}
            title={sidebarCollapsed ? "Expandir menú" : "Contraer menú"}
            aria-expanded={!sidebarCollapsed || mobileOpen}
            onClick={() => {
              if (window.matchMedia("(max-width: 760px)").matches) setMobileOpen((value) => !value);
              else setSidebarCollapsed((value) => !value);
            }}
          >
            <Menu />
          </button>
          <strong>GALANT POST</strong>
          <div className="v15-quicknav" role="search">
            <input
              type="search"
              aria-label="Buscar módulo"
              placeholder="Ir a un módulo…"
              value={quickNav}
              onChange={(event)=>setQuickNav(event.target.value)}
              onKeyDown={(event)=>{
                if(event.key!=="Enter"||!quickNav.trim())return
                const target=nav.find(([,label])=>label.toLocaleLowerCase("es-CL").includes(quickNav.trim().toLocaleLowerCase("es-CL")))
                if(target){go(target[0]);setQuickNav("")}
              }}
            />
            {quickNav.trim()&&<div className="v15-quicknav-results" role="group" aria-label="Coincidencias de módulos">
              {nav.filter(([,label])=>label.toLocaleLowerCase("es-CL").includes(quickNav.trim().toLocaleLowerCase("es-CL"))).slice(0,6).map(([id,label,Icon])=>
                <button type="button" key={id} onClick={()=>{go(id);setQuickNav("")}}><Icon size={16} aria-hidden="true"/>{label}</button>)}
              {!nav.some(([,label])=>label.toLocaleLowerCase("es-CL").includes(quickNav.trim().toLocaleLowerCase("es-CL")))&&<p>Sin módulos coincidentes</p>}
            </div>}
          </div>
          {section !== "network" && <div className="global-filters">
            <label className="global-filter">
              <span>Obra</span>
              <select
                aria-label="Obra seleccionada"
                value={site}
                onChange={(e) => {
                  setSite(e.target.value);
                  setOverview(null);
                  setContributions(null);
                  setMatrix([]);
                }}
              >
                <option value="">Todas las obras</option>
                {sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="global-filter">
              <span>Período</span>
              <input
                aria-label="Período auditado"
                type="month"
                value={period}
                onChange={(e) => {
                  if (e.target.value) {
                    setPeriod(e.target.value);
                    setOverview(null);
                    setContributions(null);
                    setMatrix([]);
                  }
                }}
              />
            </label>
          </div>}
          <button
            className="icon-button"
            title="Actualizar datos"
            aria-label="Actualizar datos"
            onClick={() => section === "network" ? window.dispatchEvent(new Event("galant-network-changed")) : void refresh()}
          >
            <RefreshCcw size={18} />
          </button>
          <NetworkAccountMenu user={user} logout={() => void logout()} openNetwork={() => go("network")} openSettings={() => go("settings")} />
        </header>
        <div className="page">
          {section !== "network" && <div className="intro">
            <div>
              <span className="eyebrow">
                {profile?.organization} /{" "}
                {sites.find((s) => s.id === site)?.name || "Todas las obras"}
              </span>
              <h1>{nav.find(([id]) => id === section)?.[1]}</h1>
              <p>
                Información compartida de tu organización · Período {period}
              </p>
            </div>

          </div>}
          {section === "network" && <RedDeObras user={user} />}
          {error && (
            <div role="alert" className="alert danger">
              {error}
            </div>
          )}
          {notice && (
            <div role="status" className="alert success">
              {notice}
            </div>
          )}
          {loading && section !== "network" && <p className="v1501-refresh-status" role="status">Actualizando datos…</p>}
          {section === "home" && overview && (
            <>
              <section className="v15-dashboard-hero" aria-label="Indicadores principales del período">
                <div className="v15-dashboard-heading"><div><span className="eyebrow">VISIÓN OPERATIVA</span><h2>Resumen del período</h2><p>Situación real de las obras y documentación bajo revisión</p></div><span>{period}</span></div>
                <div className="v15-dashboard-metrics">
                  {([
                    ["Contratistas del período", overview.contractors.length, "contractors", "all"],
                    ["Contratistas al día", overview.up_to_date, "contractors", "all"],
                    ["Documentos pendientes", overview.pending_documents, "documents", "pending"],
                    ["Contratos por vencer", laborAlerts?.summary.workers_ending ?? "—", "workers", "ending_soon"],
                    ["Asistencia atrasada", laborAlerts?.summary.attendance_overdue ?? "—", "attendance", "overdue"]
                  ] as const).map(([label,value,target,state])=><button type="button" className={"v15-dashboard-kpi "+((Number(value)>0&&["Documentos pendientes","Asistencia atrasada"].includes(label))?"attention":"")} key={label} onClick={()=>drill(target,state)}>
                    <span>{label}</span><strong>{value}</strong><small>Ver detalle →</small>
                  </button>)}
                </div>
              </section>
              {laborAlerts && <section className="panel dashboard-alerts" aria-labelledby="dashboard-alerts-title">
                <div className="dashboard-section-title">
                  <div><span className="eyebrow">PRIORIDADES DEL PERÍODO</span><h2 id="dashboard-alerts-title">Alertas laborales y documentales</h2></div>
                  <span className="dashboard-source-label">Datos verificados de la obra seleccionada</span>
                </div>
                <details className="v15-dashboard-more"><summary>Indicadores de riesgo por categoría</summary><div className="kpi-grid alert-kpi-grid">
                  {([
                    ["critical_contractors", "Contratistas con documentación crítica", "documents", "overdue"],
                    ["workers_expired", "Contratos vencidos", "workers", "expired_needs_review"],
                    ["workers_ending", "Contratos próximos", "workers", "ending_soon"],
                    ["finiquito_pending", "Finiquitos pendientes", "workers", "finiquito_pending"],
                    ["incomplete_contributions", "Cotizaciones incompletas", "contributions", "differences"],
                    ["declared_unpaid", "Declaradas sin pago", "contributions", "declared_unpaid"],
                    ["attendance_overdue", "Semanas de asistencia atrasadas", "attendance", "overdue"],
                    ["unclassified_contractors", "Contratistas sin clasificación", "contractors", "SIN CLASIFICAR"],
                  ] as const).map(([key, label, destination, state]) => <button className={"kpi alert-metric " + ((laborAlerts.summary[key] || 0) === 0 ? "metric-clear" : alertCriticalKeys.has(key) ? "metric-danger" : "metric-warning")} key={key} onClick={() => {
                    drill(destination, state); if (key === "finiquito_pending") setFilter("finiquito_pending");
                    if (key === "unclassified_contractors") setClassification("SIN CLASIFICAR");
                  }}><small>{label}</small><strong>{laborAlerts.summary[key] || 0}</strong><span className="alert-metric-state">{(laborAlerts.summary[key] || 0) === 0 ? "Sin casos" : alertCriticalKeys.has(key) ? "Requiere acción" : "Revisar"}</span><span className="alert-metric-action">Ver registros →</span></button>)}
                </div>
                </details><h3 className="dashboard-list-heading">Centro de alertas</h3>
                {laborAlerts.alerts.slice(0, 30).map((item, i) => <button className={"worker-alert-link worker-signal " + item.severity} key={i} onClick={() => {
                  if (item.target_section === "workers") { setTargetWorker(item.target_id); go("workers"); }
                  else if (item.target_section === "contributions") drill("contributions", item.kind === "declared_unpaid" ? "declared_unpaid" : "differences");
                  else if (item.target_section === "documents") drill("documents", "overdue");
                  else if (item.target_section === "attendance") go("attendance");
                  else { drill("contractors"); setClassification("SIN CLASIFICAR"); }
                }}>{item.label} · {item.site} {item.date ? "· " + item.date : ""}</button>)}
                {!laborAlerts.alerts.length && <p>Sin alertas verificadas para el período y obra seleccionados.</p>}
              </section>}
              <div className="dashboard-summary-heading">
                <h2>Resumen de contratistas</h2>
                <p>Distribución por clasificación para la obra y período seleccionados.</p>
              </div>
              <div className="kpi-grid">
                {Object.entries(overview.classifications).map(
                  ([key, value]) => (
                    <button
                      className="kpi dashboard-metric"
                      key={key}
                      onClick={() => {
                        drill("contractors");
                        setClassification(key);
                      }}
                    >
                      <small>Contratistas {key}</small>
                      <strong>{value}</strong>
                      <span>Ver registros →</span>
                    </button>
                  ),
                )}
              </div>
              <details className="dashboard-more">
                <summary><strong>Más indicadores del período</strong><span>Trabajadores, documentos, pagos y retenciones</span></summary>
                <div className="kpi-grid">
                {[
                  [
                    "Trabajadores activos",
                    overview.active_workers,
                    "workers",
                    "all",
                  ],
                  [
                    "Contratistas al día",
                    overview.up_to_date,
                    "home",
                    "al día",
                  ],
                  [
                    "Con observaciones",
                    overview.observed,
                    "home",
                    "con observaciones",
                  ],
                  [
                    "Documentación pendiente",
                    overview.pending_documents,
                    "documents",
                    "pending",
                  ],
                  [
                    "Pagos confirmados",
                    overview.contributions.confirmed,
                    "contributions",
                    "payment_confirmed",
                  ],
                  [
                    "Pendientes de confirmación",
                    overview.contributions.pending_confirmation,
                    "contributions",
                    "payment_pending",
                  ],
                  [
                    "Registros sin información",
                    overview.contributions.without_information,
                    "contributions",
                    "sin información",
                  ],
                  [
                    "Promedio días registrados",
                    number(overview.contributions.average_paid_days),
                    "contributions",
                    "all",
                  ],
                  [
                    "Trabajadores con observaciones",
                    overview.observed_workers,
                    "documents",
                    "observed",
                  ],
                  [
                    "Registros con diferencias",
                    overview.contributions.with_differences,
                    "contributions",
                    "differences",
                  ],
                  [
                    "Días faltantes acumulados",
                    overview.contributions.missing_days,
                    "contributions",
                    "differences",
                  ],
                  [
                    "Retención estimada CLP",
                    number(overview.contributions.estimated_retention),
                    "contributions",
                    "all",
                  ],
                ].map(([title, value, target, state]) => (
                  <button
                    className={"kpi dashboard-metric " + (Number(value) > 0 && dashboardUrgentTitles.has(String(title)) ? "metric-danger" : Number(value) > 0 && dashboardWarningTitles.has(String(title)) ? "metric-warning" : "")}
                    key={title}
                    onClick={() => drill(String(target), String(state))}
                  >
                    <small>{title}</small>
                    <strong>{value}</strong>
                    <span>Ver detalle →</span>
                  </button>
                ))}
                </div>
              </details>
              <p className="muted">
                Promedio: {overview.contributions.denominator} registros
                individuales con días informados. La falta de información
                permanece pendiente; las observaciones requieren revisión.
              </p>
              <div className="toolbar">
                <input
                  aria-label="Buscar contratista"
                  placeholder="Buscar contratista"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <select
                  aria-label="Estado de cumplimiento"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">Todos los estados</option>
                  {[
                    "al día",
                    "con observaciones",
                    "pendiente de información",
                  ].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </div>
              <div className="contractor-grid">
                {cards.map((c) => (
                  <button
                    className="panel contractor-card"
                    key={c.association_id}
                    onClick={() => {
                      go("documents");
                      setSearch(c.contractor);
                    }}
                  >
                    <small>{c.classification}</small>
                    <h3>{c.contractor}</h3>
                    <span
                      className={
                        "state " +
                        (c.state === "al día"
                          ? "good"
                          : c.state === "con observaciones"
                            ? "pending"
                            : "neutral")
                      }
                    >
                      {c.state}
                    </span>
                    <p>
                      {c.approved} aprobados · {c.pending} pendientes /{" "}
                      {c.applicable} aplicables
                    </p>
                  </button>
                ))}
              </div>
              {!cards.length && (
                <p className="empty">
                  No hay contratistas para estos filtros. Crea una ficha o
                  importa un Excel.
                </p>
              )}
              <section className="panel">
                <h2>Actividad reciente</h2>
                {overview.activity.length ? (
                  <ul className="activity-list">
                    {overview.activity.map((a) => (
                      <li key={a.id}>
                        <span>
                          {(
                            {
                              contractor: "Contratista actualizado",
                              contractor_worksite: "Asignación de contratista",
                              worker: "Trabajador actualizado",
                              worker_assignment: "Asignación laboral",
                              contractors: "Importación de contratistas",
                              workers: "Importación de trabajadores",
                              contribution_control: "Control de cotizaciones",
                              monthly_document: "Revisión documental",
                              user: "Administración de cuenta",
                              catalogs: "Catálogos actualizados",
                              retention_rate: "Valor de retención actualizado",
                            } as Record<string, string>
                          )[a.kind] || "Registro administrativo actualizado"}
                        </span>
                        <small>
                          {a.actor} ·{" "}
                          {new Date(a.at).toLocaleString("es-CL", {
                            timeZone: "America/Santiago",
                          })}
                        </small>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>Aún no hay actividad registrada.</p>
                )}
              </section>
            </>
          )}
          {section === "contractors" &&
            (site ? (
              <ErrorBoundary key={"contractors-"+site} name="la ficha de contratistas">
              <Operations
                readOnly={readonly}
                externalSiteId={site}
                mode={section}
                onImport={() => go("imports")}
                onWorkers={(assignmentId) => { go("workers"); setTargetWorker(assignmentId || ""); }}
                classificationFilter={classification}
                period={period}
                onSiteChange={setSite}
                onPeriodChange={setPeriod}
                onAttendance={(associationId,worksiteId,month)=>{
                  const url=new URL(window.location.href)
                  url.pathname="/"
                  url.searchParams.delete("obra")
                  url.searchParams.delete("periodo")
                  url.searchParams.set("attendance_contractor",associationId)
                  url.searchParams.set("attendance_site",worksiteId)
                  url.searchParams.set("attendance_period",month)
                  window.history.pushState({galantSection:"attendance"},"",url)
                  setSite(worksiteId)
                  setPeriod(month)
                  setSection("attendance")
                }}
              />
              </ErrorBoundary>
            ) : (
              <div className="panel empty">
                Selecciona una obra en la barra superior para administrar sus
                contratistas y trabajadores.
              </div>
            ))}
          {section === "workers" && <ErrorBoundary key={"workers-"+site} name="el módulo de trabajadores"><Workers siteId={site} sites={sites} period={period}
            canEdit={!!canEdit} canReview={!!canReview}
            initialPending={filter === "finiquito_pending"}
            initialAssignment={targetWorker}
            initialState={filter === "expired_needs_review" || filter === "ending_soon" ? filter : ""} /></ErrorBoundary>}
          {section === "attendance" && <AdminAttendanceV93 siteId={site} sites={sites} period={period}
            onSiteSelect={setSite} onEvaluate={() => go("evaluations")} />}
          {section === "evaluations" && <AdministrativePerformanceV81 sites={sites} period={period} />}
          {section === "imports" && (
            <ErrorBoundary key={"imports-"+site} name="carga masiva"><BulkImport readOnly={readonly} siteId={site} /></ErrorBoundary>
          )}
          {(section === "contributions" || section === "reports") && (
            <section className="panel">
              <div className="toolbar">
                <input
                  placeholder="Buscar trabajador o contratista"
                  aria-label="Buscar control"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <select
                  aria-label="Clasificación"
                  value={classification}
                  onChange={(e) => setClassification(e.target.value)}
                >
                  <option value="all">Todas las clasificaciones</option>
                  {["CT", "CI"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
                <select
                  aria-label="Estado pago"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">Todos los estados</option>
                  {[
                    "confirmado",
                    "con diferencias",
                    "sin información",
                    "pendiente de confirmación",
                    "justificado",
                  ].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={sporadic}
                    onChange={(e) => setSporadic(e.target.checked)}
                  />
                  Incluir esporádicos y sin clasificar
                </label>
                <a
                  className="primary"
                  href={
                    "/api/v1/ops/contributions/report?" +
                    params +
                    "&include_sporadic=" +
                    sporadic +
                    "&q=" +
                    encodeURIComponent(search) +
                    "&state=" +
                    encodeURIComponent(filter) +
                    "&kind=" +
                    encodeURIComponent(classification)
                  }
                >
                  Exportar Excel por obra
                </a>
                {section === "contributions" && (
                  <button onClick={() => setEvidence(!evidence)}>
                    Analizar evidencia documental
                  </button>
                )}
              </div>
              <p>
                Promedio registrado:{" "}
                <b>{number(contributions?.summary.average_paid_days)}</b> días ·
                Denominador: {contributions?.summary.denominator} · Sin
                información: {contributions?.summary.without_information} ·
                Retención estimada: $
                {number(contributions?.summary.estimated_retention)} CLP
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Obra / contratista</th>
                      <th>Trabajador / CI</th>
                      <th>Asistencia</th>
                      <th>Pagados</th>
                      <th>Faltantes</th>
                      <th>Estimación CLP</th>
                      <th>Diferencia monetaria CLP</th>
                      <th>Comprobante</th>
                      <th>Estado</th>
                      <th>Control</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.site_id + r.subject}>
                        <td>
                          {r.site}
                          <br />
                          <b>{r.contractor}</b> · {r.classification}
                        </td>
                        <td>
                          {r.worker}
                          <br />
                          <small>{r.worker_rut}</small>
                        </td>
                        <td>{number(r.attendance_days)}</td>
                        <td>{number(r.paid_days)}</td>
                        <td>{number(r.missing_days)}</td>
                        <td>{number(r.estimated_retention)}</td>
                        <td>{number(r.monetary_difference)}</td>
                        <td><span className={"worker-signal " + (r.payment_finding === "insufficient" || r.payment_finding === "declared_unpaid" ? "red" : r.document_state === "incomplete" ? "orange" : r.document_state === "approved" ? "green" : "gray")}>
                          {r.document_state === "incomplete" ? "Incompleto — diferencia detectada" :
                          r.document_state === "not_delivered" ? "No entregado" :
                          r.document_state === "pending_review" ? "Entregado — pendiente de revisión" :
                          r.document_state === "approved" ? "Aprobado" :
                          r.document_state === "observed" ? "Observado" : r.document_state}</span></td>
                        <td>
                          <span
                            className={
                              "status " +
                              (r.state === "conforme" ? "success" :
                               r.state === "incompleto" ? "review" :
                               r.state === "observado" ? "review" : "waiting")
                            }
                          >
                            {r.state}
                          </span>
                        </td>
                        <td>
                          {canEdit && (
                            <button onClick={() => setEditing({ ...r })}>
                              Revisar días
                            </button>
                          )}
                          {canReview && r.control_id && <button onClick={() => setFindingDraft({
                            control_id:r.control_id!, state:r.payment_finding || "unverified",
                            document_id:r.receipt_document_id || "",
                            documented_amount:r.documented_amount?.toString() || "",
                            expected_amount:r.expected_amount?.toString() || "", observation:"",
                          })}>Revisar pago</button>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!rows.length && (
                <p className="empty">
                  Sin registros para estos filtros. Clasifica contratistas CT/CI
                  y registra sus trabajadores.
                </p>
              )}
              <div className="toolbar">
                <button disabled={!page} onClick={() => setPage(page - 1)}>
                  Anterior
                </button>
                <span>Página {page + 1}</span>
                <button
                  disabled={(page + 1) * 50 >= (contributions?.total || 0)}
                  onClick={() => setPage(page + 1)}
                >
                  Siguiente
                </button>
              </div>
              <p className="muted">
                La retención es una estimación administrativa. Los días
                registrados no confirman por sí solos un pago. Para comparar
                meses, cambia el período; cada exportación conserva su
                competencia.
              </p>
              {evidence && <DocumentAnalysis />}
            </section>
          )}
          {section === "documents" && (
            <section className="panel">
              <div className="toolbar">
                <input
                  aria-label="Buscar documentación"
                  placeholder="Buscar contratista o trabajador"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <select
                  aria-label="Estado documental"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">Todos los estados</option>
                  <option value="pending">Pendiente</option>
                  <option value="incomplete">Incompleto</option>
                  <option value="approved">Aprobado</option>
                  <option value="observed">Observado</option>
                  <option value="not_applicable">No aplica</option>
                </select>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Contratista</th>
                      <th>Persona</th>
                      <th>Requisito</th>
                      <th>Estado</th>
                      <th>Observación</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.slice(page * 50, (page + 1) * 50).map((r, i) => (
                      <tr key={i}>
                        <td>{r.contractor}</td>
                        <td>{r.name}</td>
                        <td>{r.requirement}</td>
                        <td>
                          <span className={
                            "status " +
                            (r.state === "approved" ? "success" :
                             r.state === "incomplete" || r.state === "observed" ? "review" :
                             r.state === "overdue" || r.state === "rejected" ? "error" : "waiting")
                          }>
                          {
                            (
                              {
                                pending: "△ Pendiente",
                                incomplete: "⚠ Incompleto",
                                approved: "✓ Aprobado",
                                observed: "! Observado",
                                not_applicable: "— No aplica",
                                schedule_not_configured:
                                  "△ Sin plazo configurado",
                                not_yet_required: "No exigible todavía",
                                overdue: "△ Fuera de plazo",
                                needs_classification: "Confirmar exigibilidad",
                                rejected: "! Rechazado",
                              } as Record<string, string>
                            )[["incomplete", "observed"].includes(r.state) ? r.state :
                              r.delivery_state === "not_delivered" ? "not_delivered" :
                              r.delivery_state === "pending_review" ? "pending_review" : r.state] ||
                              (r.delivery_state === "not_delivered" ? "No entregado" :
                               r.delivery_state === "pending_review" ? "Entregado — pendiente de revisión" : r.state)
                          }
                          </span>
                        </td>
                        <td>{r.observation}</td>
                        <td>
                          {canReview && (
                            <button onClick={() => setReviewing({
                              ...r,
                              state: (["pending", "approved", "observed", "not_applicable"].includes(r.state)
                                ? r.state : "pending"),
                            })}>
                              Revisar
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="toolbar">
                <button disabled={!page} onClick={() => setPage(page - 1)}>
                  Anterior
                </button>
                <span>Página {page + 1}</span>
                <button
                  disabled={(page + 1) * 50 >= docs.length}
                  onClick={() => setPage(page + 1)}
                >
                  Siguiente
                </button>
              </div>
              {!docs.length && (
                <p className="empty">
                  Sin requisitos aplicables. Revisa obra y clasificación CT/CI.
                </p>
              )}
            </section>
          )}
          {section === "administration" && (
            <ControlCenter
              readOnly={readonly}
              externalSiteId={site}
              externalPeriod={period}
              initialTab="contracts"
              onContextChange={(s, p) => {
                setSite(s);
                setPeriod(p);
              }}
            />
          )}
          {section === "settings" && (
            <Settings
              admin={user.role === "admin"}
              sites={sites}
              onPreferences={applyPreferences}
              onOpenConfiguration={() => go("configuration")}
            />
          )}
          {editing && (
            <div className="modal-backdrop">
              <section
                className="panel"
                role="dialog"
                aria-modal="true"
                aria-label="Revisar cotizaciones"
              >
                <h2>
                  {editing.worker} · {period}
                </h2>
                <p>
                  {editing.contractor} / {editing.site}
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void save("/ops/contributions", {
                      association_id: editing.association_id,
                      subject: editing.subject,
                      period: editing.period,
                      attendance_days: editing.attendance_days,
                      paid_days: editing.paid_days,
                      confirmed: editing.confirmed,
                      justification: editing.justification,
                    });
                  }}
                >
                  {(
                    ["attendance_days", "paid_days"] as const
                  ).map((key) => (
                    <label key={key}>
                      {
                        {
                          paid_days: "Días pagados acreditados",
                          attendance_days: "Días de asistencia",
                        }[key]
                      }
                      <input
                        type="number"
                        min="0"
                        max="31"
                        value={editing[key] ?? ""}
                        onChange={(e) =>
                          setEditing({
                            ...editing,
                            [key]:
                              e.target.value === ""
                                ? null
                                : Number(e.target.value),
                          })
                        }
                      />
                    </label>
                  ))}
                  {editing.suggested_days !== null && (
                    <p>
                      Sugerencia según historial laboral:{" "}
                      {editing.suggested_days} días. Requiere revisión.
                    </p>
                  )}
                  <label>
                    Justificación de diferencias (requiere revisión)
                    <textarea
                      value={editing.justification}
                      onChange={(e) =>
                        setEditing({
                          ...editing,
                          justification: e.target.value,
                        })
                      }
                    />
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={editing.confirmed}
                      onChange={(e) =>
                        setEditing({ ...editing, confirmed: e.target.checked })
                      }
                    />
                    Pago confirmado manualmente
                  </label>
                  {editing.subject !== "independent" &&
                    editing.attendance_days !== null &&
                    editing.paid_days !== null && (
                      <div className="contribution-preview" aria-live="polite">
                        <strong>Resultado del cuadre</strong>
                        <p>Días faltantes: <b>{Math.max(0, editing.attendance_days - editing.paid_days)}</b></p>
                        <p>Retención administrativa propuesta: <b>{number(
                          Math.max(0, editing.attendance_days - editing.paid_days) *
                            editing.daily_clp,
                        )} CLP</b></p>
                        <span className={
                          "status " +
                          (!editing.confirmed ? "waiting" :
                            editing.attendance_days > editing.paid_days ? "review" : "success")
                        }>
                          {!editing.confirmed ? "Pendiente de verificar el pago" :
                            editing.attendance_days > editing.paid_days ?
                              "INCOMPLETO — requiere revisión" : "Sin diferencias de días"}
                        </span>
                        <small>La propuesta no constituye una retención aprobada.</small>
                      </div>
                    )}
                  <div className="toolbar">
                    <button className="primary">Guardar control</button>
                    <button type="button" onClick={() => setEditing(null)}>
                      Cancelar
                    </button>
                  </div>
                </form>
                {error && (
                  <p role="alert" className="form-error">
                    {error}
                  </p>
                )}
              </section>
            </div>
          )}
          {findingDraft && <div className="modal-backdrop"><section className="panel" role="dialog" aria-modal="true" aria-label="Conclusión de pago"><h2>Revisión de pago</h2>
            <p>Solo la revisión humana de un documento permite declarar pago insuficiente o declarado sin pago. Cambiar los días invalida la conclusión anterior.</p>
            <form onSubmit={(e) => { e.preventDefault(); void (async () => { try {
              await send("/labor/contributions/" + findingDraft.control_id + "/finding", {
                state:findingDraft.state, document_id:findingDraft.document_id || null,
                documented_amount:findingDraft.documented_amount ? Number(findingDraft.documented_amount) : null,
                expected_amount:findingDraft.expected_amount ? Number(findingDraft.expected_amount) : null,
                observation:findingDraft.observation,
              }, "PUT"); setFindingDraft(null); await refresh(); setNotice("Revisión de pago registrada.");
            } catch (ex) { setError(errorText(ex)); } })(); }}>
              <label>Conclusión<select value={findingDraft.state} onChange={(e) => setFindingDraft({ ...findingDraft, state:e.target.value })}><option value="unverified">Sin verificar</option><option value="verified">Pago verificado</option><option value="insufficient">Pago inferior al requerido</option><option value="declared_unpaid">Declarado sin pago</option></select></label>
              <label>ID del documento<input value={findingDraft.document_id} onChange={(e) => setFindingDraft({ ...findingDraft, document_id:e.target.value })} /></label>
              <label>Monto documentado CLP<input type="number" min="0" value={findingDraft.documented_amount} onChange={(e) => setFindingDraft({ ...findingDraft, documented_amount:e.target.value })} /></label>
              <label>Monto esperado CLP<input type="number" min="0" value={findingDraft.expected_amount} onChange={(e) => setFindingDraft({ ...findingDraft, expected_amount:e.target.value })} /></label>
              <label>Motivo y evidencia<textarea value={findingDraft.observation} onChange={(e) => setFindingDraft({ ...findingDraft, observation:e.target.value })} /></label>
              <div className="toolbar"><button className="primary">Guardar revisión</button><button type="button" onClick={() => setFindingDraft(null)}>Cancelar</button></div>
            </form>{error && <p role="alert" className="form-error">{error}</p>}
          </section></div>}
          {reviewing && (
            <div className="modal-backdrop">
              <section
                className="panel"
                role="dialog"
                aria-modal="true"
                aria-label="Revisión documental"
              >
                <h2>{reviewing.name}</h2>
                <p>
                  {reviewing.requirement} · {period}
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void save("/ops/document-reviews", reviewing);
                  }}
                >
                  <label>
                    Estado
                    <select
                      value={reviewing.state}
                      onChange={(e) =>
                        setReviewing({ ...reviewing, state: e.target.value })
                      }
                    >
                      <option value="pending">Pendiente</option>
                      <option value="approved">Aprobado manualmente</option>
                      <option value="observed">Observado</option>
                      <option value="not_applicable">
                        No aplica (requiere justificación)
                      </option>
                    </select>
                  </label>
                  <label>
                    Observación
                    <textarea
                      value={reviewing.observation}
                      onChange={(e) =>
                        setReviewing({
                          ...reviewing,
                          observation: e.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    ID de documento existente (opcional)
                    <input
                      value={reviewing.document_id || ""}
                      onChange={(e) =>
                        setReviewing({
                          ...reviewing,
                          document_id: e.target.value || null,
                        })
                      }
                    />
                  </label>
                  <div className="toolbar">
                    <button className="primary">Guardar revisión</button>
                    <button type="button" onClick={() => setReviewing(null)}>
                      Cancelar
                    </button>
                  </div>
                </form>
                {error && (
                  <p role="alert" className="form-error">
                    {error}
                  </p>
                )}
              </section>
            </div>
          )}
          <footer className="footer">
            GALANT POST v{version} · {profile?.organization}
            <span>
              {section === "network" ? "Información compartida · Red de Obras" : "Datos de la organización · Actualización automática cada 10 segundos"}
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}
export default App;
