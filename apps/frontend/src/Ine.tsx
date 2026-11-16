import { useCallback, useEffect, useMemo, useState } from "react";
import type { Profile } from "./api";
import { request } from "./api";
import {
  ArrowLeft, BarChart3, BookOpenText, Check, CheckCircle2, ChevronRight, Clock3,
  Download, FileSpreadsheet, History, Info, LockKeyhole, Pencil, Plus,
  RefreshCw, Save, Search, ShieldCheck, UploadCloud, X,
} from "lucide-react";
import "./ine.css";

type Field = "cct" | "cesp" | "ind" | "th" | "tm";
type Counts = Record<Field, number | null>;
type Tab = "registro" | "analisis" | "historico" | "auditoria" | "respaldo";
type Site = { id: string; name: string };
type SheetRow = Counts & {
  id: string | null; period: string; site_id: string | null;
  site_name: string; supervisor: string; complete: boolean;
  editable: boolean; version: number; source_sheet: string; source_row: number;
  source_status: string | null; source_total: string | number | null;
  source_percent: string | number | null;
};
type Configuration = {
  role: string; current_month: string; previous_month: string;
  sites: Site[]; available_periods: string[];
  source: { name: string; sha256: string; id: string } | null;
};
type MonthSummary = Counts & {
  period: string; rows: number; complete: number; pending: number; reported: number;
};
type Summary = { year: number; months: MonthSummary[] };
type Log = {
  id: string; actor_name: string; action: string; period: string; site_name: string;
  previous: Record<string, unknown>; current: Record<string, unknown>; created_at: string;
};
type Archive = { sheets: { id: string; name: string; rows: number }[] };
type ArchiveSheet = {
  name: string; rows: { row: number; cells: Record<string, unknown>; formulas?: Record<string, string> }[];
};

const fields: { key: Field; label: string; hint: string; color: string }[] = [
  { key: "cct", label: "CCT", hint: "Contratistas permanentes", color: "blue" },
  { key: "cesp", label: "CESP", hint: "Contratistas esporádicos", color: "cyan" },
  { key: "ind", label: "IND", hint: "Independientes", color: "amber" },
  { key: "th", label: "TH", hint: "Trabajadores hombres", color: "indigo" },
  { key: "tm", label: "TM", hint: "Trabajadoras mujeres", color: "rose" },
];
const fmtNumber = (value: number) => value.toLocaleString("es-CL");
const errText = (value: unknown) => value instanceof Error ? value.message : String(value);
const readValue = (value: string) => value.trim() === "" ? null : Number(value);
const emptyFields = (): Record<Field, string> => ({ cct: "", cesp: "", ind: "", th: "", tm: "" });
const monthLabel = (period: string) => {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month || month < 1 || month > 12) return period;
  return new Intl.DateTimeFormat("es-CL", { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, month - 1, 1)));
};
const monthsShort = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
const rowKey = (row: SheetRow) => row.id || "site:" + row.site_id;
const sumFields = (row: Counts, names: Field[]) => names.reduce((sum, key) => sum + (row[key] || 0), 0);
const reported = (row: Counts) => fields.some(col => row[col.key] !== null);
const changedFields = (log: Log) => Object.keys(log.current).filter(key => log.previous[key] !== log.current[key]);
const numOrDash = (value: number, hasData: boolean) => hasData ? fmtNumber(value) : "—";

function checkCounts(values: Record<Field, string>): Counts {
  const output = {} as Counts;
  for (const col of fields) {
    const value = readValue(values[col.key]);
    if (value !== null && (!Number.isSafeInteger(value) || value < 0 || value > 1000000)) {
      throw new Error(col.label + ": ingresa un número entero entre 0 y 1.000.000.");
    }
    output[col.key] = value;
  }
  return output;
}

async function downloadFile(path: string, filename: string) {
  const response = await fetch("/api/v1" + path, { credentials: "include", cache: "no-store" });
  if (!response.ok) throw new Error("No se pudo descargar el archivo. Vuelve a intentarlo.");
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
function sumLabel(value: number, count: number) { return count ? fmtNumber(value) : "Sin datos"; }
function percent(numerator: number, denominator: number) {
  return denominator === 0 ? 0 : Math.round(numerator / denominator * 100);
}
function sheetGroup(name: string) {
  const v = name.trim().toUpperCase();
  if (/^(?:[1-9]|1[0-2])$/.test(v)) return "2026";
  if (/17\b|2017/.test(v)) return "2017";
  if (/18\b|2018/.test(v)) return "2018";
  if (/19\b|2019/.test(v)) return "2019";
  if (/20\b|2020/.test(v)) return "2020";
  return "Anteriores / otros";
}
function columnIndex(column: string) {
  return column.split("").reduce((n, letter) => n * 26 + letter.charCodeAt(0) - 64, 0);
}

export default function Ine({ user, version, onBack, logout }: {
  user: Profile; version?: string | null; onBack?: () => void; logout?: () => void;
}) {
  const admin = user.role === "admin";
  const supervisor = user.role === "ine_supervisor";
  const canWrite = admin || supervisor;
  const [tab, setTab] = useState<Tab>(canWrite ? "registro" : "historico");
  const [config, setConfig] = useState<Configuration | null>(null);
  const [period, setPeriod] = useState("");
  const [rows, setRows] = useState<SheetRow[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Record<Field, string>>>({});
  const [summary, setSummary] = useState<Summary | null>(null);
  const [archive, setArchive] = useState<Archive | null>(null);
  const [preview, setPreview] = useState<ArchiveSheet | null>(null);
  const [selectedSheet, setSelectedSheet] = useState("");
  const [archiveFilter, setArchiveFilter] = useState("Todas");
  const [archiveSearch, setArchiveSearch] = useState("");
  const [audit, setAudit] = useState<Log[]>([]);
  const [search, setSearch] = useState("");
  const [rowFilter, setRowFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSiteId, setNewSiteId] = useState("");
  const [newCounts, setNewCounts] = useState<Record<Field, string>>(emptyFields);
  const [editingDetails, setEditingDetails] = useState("");
  const [detailName, setDetailName] = useState("");
  const [detailSupervisor, setDetailSupervisor] = useState("");
  const [upload, setUpload] = useState<File | null>(null);
  const [uploadYear, setUploadYear] = useState(2026);

  const loadConfig = useCallback(async () => {
    const result = await request<Configuration>("/ine/config");
    setConfig(result);
    setPeriod(previous => previous || result.current_month);
    return result;
  }, []);
  const loadMonth = useCallback(async (target: string) => {
    const result = await request<{ rows: SheetRow[] }>("/ine/rows?period=" + encodeURIComponent(target));
    setRows(result.rows);
    setDrafts({});
  }, []);
  const loadSummary = useCallback(async (target: string) => {
    const result = await request<Summary>("/ine/summary?year=" + target.slice(0, 4));
    setSummary(result);
  }, []);
  const loadArchive = useCallback(async () => {
    const result = await request<Archive>("/ine/archive");
    setArchive(result);
    if (!selectedSheet && result.sheets.length) {
      const first = result.sheets.find(sheet => sheet.name === "10") || result.sheets[result.sheets.length - 1];
      setSelectedSheet(first.id);
    }
  }, [selectedSheet]);
  const loadAudit = useCallback(async () => {
    if (admin) setAudit(await request<Log[]>("/ine/history?limit=250"));
  }, [admin]);
  useEffect(() => {
    let active = true;
    void loadConfig().catch(e => { if (active) setError(errText(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [loadConfig]);
  useEffect(() => {
    if (!period) return;
    let active = true;
    setLoading(true);
    void Promise.all([loadMonth(period), loadSummary(period)])
      .catch(e => { if (active) setError(errText(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [period, loadMonth, loadSummary]);
  useEffect(() => {
    if ((tab === "historico" || tab === "respaldo") && archive === null) {
      void loadArchive().catch(e => setError(errText(e)));
    }
    if (tab === "auditoria" && admin) void loadAudit().catch(e => setError(errText(e)));
  }, [tab, archive, admin, loadArchive, loadAudit]);
  useEffect(() => {
    if (!selectedSheet || tab !== "historico") return;
    let active = true;
    setBusy("sheet");
    setPreview(null);
    void request<ArchiveSheet>("/ine/archive/" + encodeURIComponent(selectedSheet))
      .then(result => { if (active) setPreview(result); })
      .catch(e => { if (active) setError(errText(e)); })
      .finally(() => { if (active) setBusy(""); });
    return () => { active = false; };
  }, [selectedSheet, tab]);

  const filteredRows = useMemo(() => rows.filter(row => {
    if (search && !(row.site_name + " " + row.supervisor).toLocaleLowerCase("es-CL")
      .includes(search.toLocaleLowerCase("es-CL"))) return false;
    if (rowFilter === "pending" && row.complete) return false;
    if (rowFilter === "complete" && !row.complete) return false;
    if (rowFilter === "editable" && !row.editable) return false;
    return true;
  }), [rows, search, rowFilter]);

  const tally = useMemo(() => {
    const totalReported = rows.filter(reported).length;
    const contractors = rows.reduce((n, r) => n + sumFields(r, ["cct", "cesp", "ind"]), 0);
    const workers = rows.reduce((n, r) => n + sumFields(r, ["th", "tm"]), 0);
    return {
      totalReported, contractors, workers,
      complete: rows.filter(row => row.complete).length,
      pending: rows.filter(row => !row.complete).length,
      editable: rows.filter(row => row.editable).length,
    };
  }, [rows]);

  function value(row: SheetRow, field: Field) {
    return drafts[rowKey(row)]?.[field] ?? (row[field] === null ? "" : String(row[field]));
  }
  function dirty(row: SheetRow) {
    const draft = drafts[rowKey(row)];
    return !!draft && fields.some(col => readValue(draft[col.key]) !== row[col.key]);
  }
  function setValue(row: SheetRow, field: Field, next: string) {
    setDrafts(previous => {
      const key = rowKey(row);
      const initial = Object.fromEntries(fields.map(col => [
        col.key, row[col.key] === null ? "" : String(row[col.key]),
      ])) as Record<Field, string>;
      return { ...previous, [key]: { ...(previous[key] || initial), [field]: next } };
    });
  }
  async function saveRow(row: SheetRow) {
    const key = rowKey(row);
    setBusy(key); setError(""); setNotice("");
    try {
      const data = checkCounts(Object.fromEntries(fields.map(col => [
        col.key, value(row, col.key),
      ])) as Record<Field, string>);
      if (row.id) {
        await request("/ine/rows/" + row.id, {
          method: "PUT", body: JSON.stringify({ ...data, version: row.version }),
        });
      } else if (row.site_id) {
        await request("/ine/rows", {
          method: "POST", body: JSON.stringify({ ...data, version: 0, site_id: row.site_id, period }),
        });
      } else {
        throw new Error("Primero crea o vincula la obra.");
      }
      await Promise.all([loadMonth(period), loadSummary(period), loadConfig()]);
      setNotice("Cambios guardados. El Excel original permanece intacto.");
    } catch (e) { setError(errText(e)); }
    finally { setBusy(""); }
  }
  async function linkRow(row: SheetRow, siteId: string) {
    if (!row.id || !admin) return;
    setBusy(rowKey(row)); setError("");
    try {
      await request("/ine/rows/" + row.id + "/link", {
        method: "PUT", body: JSON.stringify({ site_id: siteId || null }),
      });
      await loadMonth(period);
      setNotice("La vinculación se guardó sin modificar la hoja original.");
    } catch (e) { setError(errText(e)); }
    finally { setBusy(""); }
  }
  async function saveDetails(row: SheetRow) {
    if (!row.id || !admin) return;
    setBusy("details:" + row.id); setError("");
    try {
      await request("/ine/rows/" + row.id + "/details", {
        method: "PUT",
        body: JSON.stringify({ version: row.version, site_name: detailName, supervisor: detailSupervisor }),
      });
      setEditingDetails("");
      await loadMonth(period);
      setNotice("Datos de la obra actualizados. Se conservó el original y se registró la modificación.");
    } catch (e) { setError(errText(e)); }
    finally { setBusy(""); }
  }
  async function createManual() {
    if (!admin) return;
    setBusy("new"); setError(""); setNotice("");
    try {
      const result = await request<SheetRow>("/ine/rows/manual", {
        method: "POST",
        body: JSON.stringify({
          period, site_name: newName, site_id: newSiteId || null, version: 0,
          ...checkCounts(newCounts),
        }),
      });
      setShowNew(false);
      setNewName("");
      setNewSiteId("");
      setNewCounts(emptyFields());
      setSearch("");
      setRowFilter("all");
      await Promise.all([loadMonth(period), loadSummary(period), loadConfig()]);
      setNotice("Nueva obra creada: " + result.site_name + ". Ya puedes modificarla como administrador.");
    } catch (e) { setError(errText(e)); }
    finally { setBusy(""); }
  }
  async function importExcel() {
    if (!upload || !admin) return;
    const data = new FormData();
    data.append("file", upload);
    data.append("year", String(uploadYear));
    setBusy("import"); setError(""); setNotice("");
    try {
      const result = await request<{ sheets: number; transcribed_rows: number }>("/ine/import", {
        method: "POST", body: data,
      });
      setArchive(null);
      setPreview(null);
      setSelectedSheet("");
      await Promise.all([loadConfig(), loadMonth(period), loadSummary(period)]);
      setUpload(null);
      setNotice("Se transcribieron " + result.sheets + " hojas y " + result.transcribed_rows +
        " filas mensuales. El archivo original no se modificó.");
    } catch (e) { setError(errText(e)); }
    finally { setBusy(""); }
  }

  const graph = summary?.months || [];
  const maxContract = Math.max(1, ...graph.map(item => sumFields(item, ["cct", "cesp", "ind"])));
  const maxWorkers = Math.max(1, ...graph.map(item => sumFields(item, ["th", "tm"])));
  const contractorSplit = fields.slice(0, 3).map(col => ({
    ...col, value: rows.reduce((acc, item) => acc + (item[col.key] || 0), 0),
  }));
  const workerSplit = fields.slice(3).map(col => ({
    ...col, value: rows.reduce((acc, item) => acc + (item[col.key] || 0), 0),
  }));
  const topSites = rows.filter(reported).map(row => ({
    name: row.site_name, amount: sumFields(row, ["cct", "cesp", "ind"]),
  })).sort((a, b) => b.amount - a.amount).slice(0, 6);
  const maxSite = Math.max(1, ...topSites.map(site => site.amount));
  const sheets = (archive?.sheets || []).filter(sheet =>
    (archiveFilter === "Todas" || sheetGroup(sheet.name) === archiveFilter) &&
    (!archiveSearch.trim() || sheet.name.toLocaleLowerCase("es-CL")
      .includes(archiveSearch.trim().toLocaleLowerCase("es-CL"))));
  const sheetGroups = ["Todas", ...new Set((archive?.sheets || []).map(sheet => sheetGroup(sheet.name)))];
  const columns = [...new Set((preview?.rows || []).flatMap(line => Object.keys(line.cells)))]
    .sort((a, b) => columnIndex(a) - columnIndex(b));
  const canEditThisPeriod = admin || (supervisor && config &&
    (period === config.current_month || period === config.previous_month));
  const selectedMonthHasData = tally.totalReported > 0;
  const currentDateLabel = period ? monthLabel(period) : "mes seleccionado";

  return <div className="ine ine-v2051">
    <section className="ine-hero ine-new-hero">
      <div className="ine-hero-left">
        {onBack && <button className="ine-back" type="button" onClick={onBack}>
          <ArrowLeft size={16}/> Volver a GALANT
        </button>}
        <div className="ine-kicker"><FileSpreadsheet size={17}/> GALANT / CONTROL INE
          <span>v{version || "20.5.1"}</span></div>
        <h1>Control de contratistas por obra</h1>
        <p>Consulta todos los meses y el histórico original. Registra las cifras por obra con permisos claros y trazabilidad.</p>
      </div>
      <div className="ine-hero-right">
        <span className="ine-role">
          {admin ? <ShieldCheck size={16}/> : <LockKeyhole size={16}/>}
          {admin ? "Administrador · edición completa" : supervisor ? "Supervisor · edición limitada" : "Consulta histórica"}
        </span>
        {logout && <button type="button" className="ine-light-btn" onClick={logout}>Cerrar sesión</button>}
      </div>
    </section>

    {error && <div className="ine-alert ine-error" role="alert">{error}
      <button type="button" onClick={() => setError("")} aria-label="Cerrar error"><X size={16}/></button></div>}
    {notice && <div className="ine-alert ine-success" role="status">{notice}
      <button type="button" onClick={() => setNotice("")} aria-label="Cerrar aviso"><X size={16}/></button></div>}

    {!config?.source && !loading && <div className="ine-source-banner">
      <div><Info size={21}/><span><strong>Histórico original pendiente de importar.</strong>
        {admin ? " Carga el Excel 2026 una sola vez para consultar las hojas antiguas y editar sus registros."
          : " El administrador debe importar el Excel para que puedas consultar todas las hojas históricas."}</span></div>
      {admin && <button type="button" onClick={() => setTab("respaldo")}>Importar Excel <ChevronRight size={16}/></button>}
    </div>}

    <div className="ine-control ine-new-control">
      <label className="ine-month"><span>Período seleccionado</span>
        <input type="month" aria-label="Seleccionar cualquier mes del histórico" value={period}
          onChange={event => { if (event.target.value) setPeriod(event.target.value); }}/>
      </label>
      <div className="ine-quick-months">
        {config && [config.current_month, config.previous_month].map((month, index) =>
          <button type="button" key={month} className={period === month ? "selected" : ""}
            onClick={() => setPeriod(month)}>{index === 0 ? "Mes actual" : "Mes anterior"}</button>)}
        <button type="button" onClick={() => setTab("historico")}><BookOpenText size={15}/> Histórico original</button>
      </div>
      <button type="button" className="ine-refresh" disabled={loading || !period}
        onClick={() => void Promise.all([loadMonth(period), loadSummary(period)])}>
        <RefreshCw size={16}/> Actualizar
      </button>
    </div>
    <div className="ine-policy-line">
      <span className="ine-policy-pill"><LockKeyhole size={14}/>
        {admin ? "Puedes editar cualquier obra y mes" : supervisor
          ? "Editas solo tus obras del mes actual y anterior" : "Todos los registros son de solo lectura"}
      </span>
      <span>El Excel original nunca se modifica.</span>
    </div>

    <div className="ine-kpis">
      <div className="ine-kpi ine-kpi-blue"><span>Contratistas del mes</span>
        <strong>{sumLabel(tally.contractors, tally.totalReported)}</strong>
        <small>CCT + CESP + IND · {currentDateLabel}</small></div>
      <div className="ine-kpi ine-kpi-teal"><span>Trabajadores del mes</span>
        <strong>{sumLabel(tally.workers, tally.totalReported)}</strong>
        <small>TH + TM · {currentDateLabel}</small></div>
      <div className="ine-kpi ine-kpi-green"><span>Obras completadas</span>
        <strong>{tally.complete}<em> / {rows.length}</em></strong>
        <small>{rows.length ? percent(tally.complete, rows.length) + "% de las obras del período" : "Sin obras registradas"}</small></div>
      <div className={"ine-kpi " + (tally.pending ? "ine-kpi-amber" : "ine-kpi-neutral")}>
        <span>Obras pendientes</span><strong>{tally.pending}</strong>
        <small>Casillas sin información, no ceros</small></div>
    </div>

    <nav className="ine-tabs" aria-label="Secciones del control INE">
      <button type="button" aria-current={tab === "registro" ? "page" : undefined}
        className={tab === "registro" ? "selected" : ""} onClick={() => setTab("registro")}>
        <Pencil size={16}/> Registro mensual</button>
      <button type="button" aria-current={tab === "analisis" ? "page" : undefined}
        className={tab === "analisis" ? "selected" : ""} onClick={() => setTab("analisis")}>
        <BarChart3 size={16}/> Análisis y gráficos</button>
      <button type="button" aria-current={tab === "historico" ? "page" : undefined}
        className={tab === "historico" ? "selected" : ""} onClick={() => setTab("historico")}>
        <BookOpenText size={16}/> Histórico completo <span className="ine-tab-count">{archive?.sheets.length ?? "…"}</span></button>
      {admin && <button type="button" aria-current={tab === "auditoria" ? "page" : undefined}
        className={tab === "auditoria" ? "selected" : ""} onClick={() => setTab("auditoria")}>
        <History size={16}/> Auditoría privada</button>}
      {admin && <button type="button" aria-current={tab === "respaldo" ? "page" : undefined}
        className={tab === "respaldo" ? "selected" : ""} onClick={() => setTab("respaldo")}>
        <Download size={16}/> Excel y respaldo</button>}
    </nav>

    {tab === "registro" && <section className="ine-register">
      <div className="ine-section-head">
        <div><span className="ine-eyebrow">CIFRAS POR OBRA</span>
          <h2>Registro de {currentDateLabel}</h2>
          <p>Se muestran las cifras originales y las últimas actualizaciones. El administrador puede editar cualquier período.</p>
        </div>
        {admin && <button className="ine-primary-action" type="button" onClick={() => setShowNew(!showNew)}>
          {showNew ? <X size={16}/> : <Plus size={16}/>}
          {showNew ? "Cerrar formulario" : "Agregar obra o registro"}</button>}
      </div>
      {admin && showNew && <section className="ine-new-record" aria-label="Crear registro INE">
        <div className="ine-inline-heading"><h3>Nuevo registro del mes</h3>
          <span>Disponible para el administrador en cualquier período</span></div>
        <div className="ine-new-grid">
          <label>Vincular a obra GALANT (opcional)
            <select value={newSiteId} onChange={event => {
              const id = event.target.value;
              setNewSiteId(id);
              const existing = config?.sites.find(site => site.id === id);
              if (existing) setNewName(existing.name);
            }}>
              <option value="">Sin vincular · escribir nombre manual</option>
              {config?.sites.map(site => <option value={site.id} key={site.id}>{site.name}</option>)}
            </select></label>
          <label>Nombre de la obra
            <input type="text" value={newName} maxLength={200} placeholder="Ej.: OBRA LOMAS VERDES"
              onChange={event => setNewName(event.target.value)}/></label>
        </div>
        <div className="ine-new-counts">{fields.map(col => <label key={col.key}>
          <span>{col.label}</span><input type="number" min="0" max="1000000" step="1" placeholder="Vacío"
            value={newCounts[col.key]} onChange={event => setNewCounts(prev => ({ ...prev, [col.key]: event.target.value }))}/></label>)}</div>
        <div className="ine-new-actions"><small>Deja la cifra en blanco si aún no está informada.</small>
          <button className="ine-save" type="button" disabled={!!busy || !newName.trim()}
            onClick={() => void createManual()}>
            <Plus size={16}/> {busy === "new" ? "Creando…" : "Crear registro"}</button></div>
      </section>}

      <div className="ine-filters">
        <label className="ine-search"><Search size={17}/>
          <input type="search" aria-label="Buscar obra o supervisor" placeholder="Buscar por obra o supervisor"
            value={search} onChange={event => setSearch(event.target.value)}/></label>
        <select aria-label="Filtrar estado de obras" value={rowFilter} onChange={event => setRowFilter(event.target.value)}>
          <option value="all">Todas las obras</option><option value="pending">Pendientes</option>
          <option value="complete">Completas</option><option value="editable">Puedo editar</option>
        </select>
        <span className="ine-row-count">{filteredRows.length} obras</span>
      </div>

      {loading && <p className="ine-loading" role="status">Cargando registros del mes…</p>}
      {!loading && filteredRows.length === 0 && <div className="ine-empty">
        <FileSpreadsheet size={33}/><h3>No hay registros para mostrar</h3>
        <p>{rows.length ? "Prueba otro filtro o nombre de obra." :
          admin ? "Puedes agregar tu primera obra con el botón «Agregar obra o registro», o importar el Excel original para transcribir sus hojas." :
          "Todavía no hay cifras cargadas para este mes. Puedes consultar otros períodos y el histórico original."}</p>
        {admin && !rows.length && <button type="button" className="ine-primary-action" onClick={() => setShowNew(true)}><Plus size={16}/> Crear registro ahora</button>}
      </div>}
      <div className="ine-row-list">{filteredRows.map(row => <article
        className={"ine-site " + (row.editable ? "ine-site-editable" : "ine-site-readonly")}
        key={rowKey(row)}>
        <div className="ine-site-title">
          <div className="ine-site-names">
            <span className={"ine-status " + (row.complete ? "complete" : "pending")}>
              {row.complete ? <CheckCircle2 size={14}/> : <Clock3 size={14}/>}
              {row.complete ? "Completo" : "Pendiente"}
            </span>
            <h3>{row.site_name}</h3>
            <small>{row.supervisor ? "Supervisor del Excel: " + row.supervisor :
              row.site_id ? "Obra vinculada a GALANT" : "Obra del registro INE"}</small>
          </div>
          <div className="ine-site-actions">
            <span className={row.editable ? "ine-allowed" : "ine-locked"}>
              {row.editable ? <Check size={14}/> : <LockKeyhole size={14}/>}
              {row.editable ? "Editable" : "Solo lectura"}</span>
            {admin && row.id && <button type="button" className="ine-text-action"
              onClick={() => {
                if (editingDetails === row.id) setEditingDetails("");
                else {
                  setDetailName(row.site_name); setDetailSupervisor(row.supervisor);
                  setEditingDetails(row.id || "");
                }
              }}><Pencil size={13}/> Editar datos de obra</button>}
          </div>
        </div>
        {admin && row.id && editingDetails === row.id && <div className="ine-details-editor">
          <label>Nombre en GALANT
            <input type="text" value={detailName} maxLength={200}
              onChange={event => setDetailName(event.target.value)}/></label>
          <label>Supervisor
            <input type="text" value={detailSupervisor} maxLength={180}
              onChange={event => setDetailSupervisor(event.target.value)}/></label>
          <label>Vincular obra
            <select value={row.site_id || ""} disabled={!!busy} onChange={event => void linkRow(row, event.target.value)}>
              <option value="">Sin vincular</option>
              {config?.sites.map(site => <option key={site.id} value={site.id}>{site.name}</option>)}
            </select></label>
          <button type="button" className="ine-save" disabled={!!busy || !detailName.trim()}
            onClick={() => void saveDetails(row)}><Save size={15}/> Guardar datos</button>
        </div>}
        <div className="ine-fields">{fields.map(col => <label key={col.key} className={"ine-field-" + col.color} title={col.hint}>
          <span>{col.label}</span>
          <input aria-label={col.hint + " · " + row.site_name} inputMode="numeric"
            type="number" min={0} max={1000000} step={1} placeholder="Sin dato"
            disabled={!row.editable || !!busy} value={value(row, col.key)}
            onChange={event => setValue(row, col.key, event.target.value)}/>
          <small>{col.hint}</small>
        </label>)}</div>
        <div className="ine-site-footer">
          <div className="ine-source-tags">
            <span>{row.source_sheet && row.source_row ? "Excel: hoja " + row.source_sheet + " · fila " + row.source_row :
              "Registro de GALANT"}</span>
            {row.source_status && <span>Estado original: {row.source_status}</span>}
            {row.source_total !== null && <span>Total original: {String(row.source_total)}</span>}
            {row.source_percent !== null && <span>% original: {String(row.source_percent)}</span>}
          </div>
          {row.editable && <div className="ine-save-area">
            {dirty(row) && <span>Hay cambios sin guardar</span>}
            <button type="button" className="ine-save" disabled={!dirty(row) || !!busy}
              onClick={() => void saveRow(row)}><Save size={16}/>{busy === rowKey(row) ? "Guardando…" : "Guardar cambios"}</button>
          </div>}
        </div>
      </article>)}</div>
    </section>}

    {tab === "analisis" && <section className="ine-analytics">
      <div className="ine-section-head"><div>
        <span className="ine-eyebrow">DATOS Y ANÁLISIS</span>
        <h2>Indicadores del año {period.slice(0, 4)}</h2>
        <p>Los gráficos se calculan con los registros mensuales de GALANT; no alteran el Excel original.</p>
      </div></div>
      <div className="ine-analytic-grid">
        <div className="ine-analytic-card">
          <div className="ine-card-title"><div><strong>Contratistas por mes</strong>
            <span>CCT + CESP + IND</span></div><span className="ine-dot ine-dot-blue"/></div>
          <div className="ine-bars">{graph.map((item, index) => {
            const n = sumFields(item, ["cct", "cesp", "ind"]);
            return <div className="ine-bar-column" key={item.period} title={monthLabel(item.period) + ": " + (item.reported ? n : "sin datos")}>
              <div className="ine-bar-area"><div className={item.reported ? "ine-bar-fill ine-bar-blue" : "ine-bar-none"}
                style={{ height: item.reported ? Math.max(3, n / maxContract * 100) + "%" : "3px" }}/></div>
              <small>{monthsShort[index]}</small>
            </div>;
          })}</div>
          <p className="ine-chart-note">Los meses sin reportes se muestran sin barra, no como cero.</p>
        </div>
        <div className="ine-analytic-card">
          <div className="ine-card-title"><div><strong>Trabajadores por mes</strong>
            <span>TH + TM</span></div><span className="ine-dot ine-dot-teal"/></div>
          <div className="ine-bars">{graph.map((item, index) => {
            const n = sumFields(item, ["th", "tm"]);
            return <div className="ine-bar-column" key={item.period} title={monthLabel(item.period) + ": " + (item.reported ? n : "sin datos")}>
              <div className="ine-bar-area"><div className={item.reported ? "ine-bar-fill ine-bar-teal" : "ine-bar-none"}
                style={{ height: item.reported ? Math.max(3, n / maxWorkers * 100) + "%" : "3px" }}/></div>
              <small>{monthsShort[index]}</small>
            </div>;
          })}</div>
          <p className="ine-chart-note">Escala independiente de la gráfica de contratistas.</p>
        </div>
        <div className="ine-analytic-card">
          <div className="ine-card-title"><div><strong>Distribución de contratistas</strong>
            <span>{currentDateLabel}</span></div></div>
          {selectedMonthHasData ? <div className="ine-segment-stack">
            {contractorSplit.map(item => <div key={item.key} className={"ine-stack-" + item.color}
              style={{ width: (tally.contractors ? item.value / tally.contractors * 100 : 0) + "%" }}/>)}
          </div> : <p className="ine-no-stat">No hay cifras informadas para este período.</p>}
          {contractorSplit.map(item => <div key={item.key} className="ine-key-value">
            <span><i className={"ine-key-" + item.color}/>{item.hint}</span>
            <strong>{numOrDash(item.value, selectedMonthHasData)}</strong></div>)}
        </div>
        <div className="ine-analytic-card">
          <div className="ine-card-title"><div><strong>Distribución de trabajadores</strong>
            <span>{currentDateLabel}</span></div></div>
          {selectedMonthHasData ? <div className="ine-segment-stack">
            {workerSplit.map(item => <div key={item.key} className={"ine-stack-" + item.color}
              style={{ width: (tally.workers ? item.value / tally.workers * 100 : 0) + "%" }}/>)}
          </div> : <p className="ine-no-stat">No hay cifras informadas para este período.</p>}
          {workerSplit.map(item => <div key={item.key} className="ine-key-value">
            <span><i className={"ine-key-" + item.color}/>{item.hint}</span>
            <strong>{numOrDash(item.value, selectedMonthHasData)}</strong></div>)}
        </div>
        <div className="ine-analytic-card ine-analytic-wide">
          <div className="ine-card-title"><div><strong>Obras con mayor registro de contratistas</strong>
            <span>{currentDateLabel} · comparación descriptiva, no clasificación de desempeño</span></div></div>
          {topSites.length ? <div className="ine-top-list">{topSites.map(site =>
            <div className="ine-top-item" key={site.name}>
              <span title={site.name}>{site.name}</span>
              <div><span style={{ width: (site.amount / maxSite * 100) + "%" }}/></div>
              <strong>{fmtNumber(site.amount)}</strong></div>)}</div> :
            <p className="ine-no-stat">Selecciona un mes con información para comparar sus obras.</p>}
        </div>
      </div>
      <div className="ine-panel ine-analytics-table">
        <div className="ine-section-head"><div><h3>Resumen mensual</h3>
          <p>Las casillas sin informar no deben interpretarse como actividad cero.</p></div></div>
        <div className="ine-table-scroll"><table className="ine-stats">
          <thead><tr><th>Mes</th>{fields.map(col => <th key={col.key}>{col.label}</th>)}
            <th>Obras informadas</th><th>Completas</th><th>Pendientes</th></tr></thead>
          <tbody>{graph.map(item => <tr key={item.period}>
            <th>{monthLabel(item.period)}</th>
            {fields.map(col => <td key={col.key}>{item.reported ? fmtNumber(item[col.key] || 0) : "—"}</td>)}
            <td>{item.reported ? item.reported : "—"}</td>
            <td>{item.rows ? item.complete : "—"}</td>
            <td>{item.rows ? item.pending : "—"}</td>
          </tr>)}</tbody></table></div>
        <p className="ine-footnote"><Info size={15}/> Los históricos anteriores a 2026 tienen estructuras distintas y pueden consultarse literalmente en «Histórico completo» sin forzar categorías incorrectas.</p>
      </div>
    </section>}

    {tab === "historico" && <section className="ine-panel ine-history-library">
      <div className="ine-section-head"><div><span className="ine-eyebrow">ARCHIVO HISTÓRICO ORIGINAL</span>
        <h2>Consulta de todas las hojas</h2>
        <p>Disponible para todos los usuarios INE. Se leen los valores originales y las fórmulas sin modificarlas.</p></div>
        <span className="ine-history-lock"><LockKeyhole size={14}/> Solo lectura</span>
      </div>
      {archive?.sheets.length ? <div className="ine-archive-layout">
        <aside className="ine-archive-sidebar">
          <div className="ine-archive-search"><Search size={15}/>
            <input type="search" aria-label="Buscar hoja histórica" value={archiveSearch}
              onChange={event => setArchiveSearch(event.target.value)} placeholder="Buscar mes u hoja…"/></div>
          <select aria-label="Filtrar año del Excel" value={archiveFilter} onChange={event => setArchiveFilter(event.target.value)}>
            {sheetGroups.map(group => <option key={group} value={group}>{group}</option>)}
          </select>
          <p>{archive.sheets.length} hojas originales · {sheets.length} visibles</p>
          <div className="ine-sheet-list">{sheets.map(sheet =>
            <button key={sheet.id} type="button" className={selectedSheet === sheet.id ? "selected" : ""}
              onClick={() => setSelectedSheet(sheet.id)}>
              <span><BookOpenText size={14}/>{sheet.name}</span><small>{sheetGroup(sheet.name)}</small>
            </button>)}
          </div>
        </aside>
        <div className="ine-archive-main">
          {busy === "sheet" || !preview ? <div className="ine-loading">Cargando hoja original…</div> :
            <>
              <div className="ine-archive-heading"><div><span>VISTA HISTÓRICA</span>
                <h3>{preview.name}</h3><p>Valores originales · {preview.rows.length} filas con contenido</p></div>
                <span><LockKeyhole size={14}/> Protegido</span></div>
              <div className="ine-table-scroll ine-historic-scroll">
                <table className="ine-original-table"><thead><tr><th>Fila</th>
                  {columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
                  <tbody>{preview.rows.map(line => <tr key={line.row}><th>{line.row}</th>
                    {columns.map(col => {
                      const value = line.cells[col];
                      const display = value == null ? "" : String(value);
                      return <td key={col}
                        className={(display.startsWith("#") ? "ine-error-cell " : "") +
                          (line.formulas?.[col] ? "ine-formula-cell" : "")}
                        title={line.formulas?.[col] || display}>{display}</td>;
                    })}</tr>)}</tbody>
                </table>
              </div>
              <p className="ine-footnote"><Info size={15}/> Una fórmula puede mostrar un error presente en el Excel original. La consulta no recalcula ni corrige el archivo.</p>
            </>}
        </div>
      </div> : <div className="ine-empty"><BookOpenText size={32}/>
        <h3>No hay hojas históricas cargadas</h3>
        <p>El administrador debe importar «02 INE 2026.xlsx» en Excel y respaldo. El archivo se conservará sin cambios.</p>
        {admin && <button type="button" className="ine-primary-action" onClick={() => setTab("respaldo")}>
          <UploadCloud size={16}/> Ir a importar Excel</button>}
      </div>}
    </section>}

    {tab === "auditoria" && admin && <section className="ine-panel">
      <div className="ine-section-head"><div><span className="ine-eyebrow">ACCESO EXCLUSIVO ADMIN</span>
        <h2>Auditoría de modificaciones</h2>
        <p>A diferencia del histórico de datos, esta lista registra quién cambió cada valor y cuándo.</p></div>
        <span className="ine-history-lock"><ShieldCheck size={15}/> Privado</span>
      </div>
      {audit.length ? <div className="ine-history">{audit.map(log => <article key={log.id}>
        <div><b>{log.actor_name}</b>
          <time>{new Date(log.created_at).toLocaleString("es-CL", { timeZone: "America/Santiago" })}</time></div>
        <p>{log.site_name} · {monthLabel(log.period)} · {log.action === "create" ? "Registro nuevo" :
          log.action === "link" ? "Vinculación" : log.action === "details" ? "Datos de la obra" : "Modificación"}</p>
        {changedFields(log).map(field => <div className="ine-diff" key={field}>
          <strong>{field.toUpperCase()}</strong><span>{String(log.previous[field] ?? "Vacío")}</span>
          <ChevronRight size={13}/><b>{String(log.current[field] ?? "Vacío")}</b></div>)}
      </article>)}</div> : <div className="ine-empty"><ShieldCheck size={32}/>
        <h3>Sin cambios registrados</h3><p>Las próximas modificaciones aparecerán con el nombre real del usuario.</p></div>}
    </section>}

    {tab === "respaldo" && admin && <section className="ine-panel ine-backup-panel">
      <div className="ine-section-head"><div><span className="ine-eyebrow">SEGURIDAD DOCUMENTAL</span>
        <h2>Excel original y respaldos</h2><p>El archivo de origen se conserva exactamente como fue recibido. GALANT trabaja sobre una copia de sus registros.</p></div></div>
      <div className="ine-archive-actions">
        <div className="ine-archive-card"><BookOpenText size={24}/><h3>Original sin modificaciones</h3>
          <p>{config?.source ? config.source.name : "Todavía no existe un archivo original importado."}</p>
          {config?.source && <button type="button" onClick={() => void downloadFile("/ine/original", "INE-original-sin-modificaciones.xlsx").catch(e => setError(errText(e)))}>
            <Download size={16}/> Descargar archivo original</button>}
        </div>
        <div className="ine-archive-card"><Download size={24}/><h3>Respaldo actualizado</h3>
          <p>Exportación de los registros editados de {period.slice(0, 4)}, sin cambiar el Excel fuente.</p>
          <button type="button" onClick={() => void downloadFile("/ine/export?year=" + period.slice(0, 4),
            "GALANT-INE-respaldo-" + period.slice(0, 4) + ".xlsx").catch(e => setError(errText(e)))}>
            <Download size={16}/> Descargar respaldo {period.slice(0, 4)}</button>
        </div>
      </div>
      {!config?.source && <section className="ine-import">
        <h3>Transcribir el Excel histórico</h3>
        <p>Importación única y sin correcciones. Se conservará el archivo binario original, y todas sus hojas quedarán disponibles para consulta.</p>
        <div className="ine-import-form">
          <label>Año de las 12 hojas mensuales
            <input type="number" min="1900" max="2199" value={uploadYear} onChange={event => setUploadYear(Number(event.target.value))}/></label>
          <label>Seleccionar archivo Excel
            <input type="file" accept=".xlsx" onChange={event => setUpload(event.target.files?.[0] || null)}/></label>
          <button type="button" disabled={!upload || !!busy} onClick={() => void importExcel()}>
            <UploadCloud size={16}/>{busy === "import" ? "Transcribiendo…" : "Transcribir sin modificar"}</button>
        </div>
      </section>}
      <p className="ine-footnote"><LockKeyhole size={15}/> Los usuarios pueden consultar el histórico; solo los administradores descargan el original, gestionan respaldos y consultan la auditoría.</p>
    </section>}
  </div>;
}
