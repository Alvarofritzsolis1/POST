import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [expandedRow, setExpandedRow] = useState("");
  const [moreCharts, setMoreCharts] = useState(false);
  const monthRequest = useRef(0);
  const summaryRequest = useRef(0);
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
    const sequence = ++monthRequest.current;
    const result = await request<{ rows: SheetRow[] }>("/ine/rows?period=" + encodeURIComponent(target));
    if (sequence !== monthRequest.current) return;
    setRows(result.rows);
    setDrafts({});
  }, []);
  const loadSummary = useCallback(async (target: string) => {
    const sequence = ++summaryRequest.current;
    const result = await request<Summary>("/ine/summary?year=" + target.slice(0, 4));
    if (sequence === summaryRequest.current) setSummary(result);
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

  const graph = summary?.year === Number(period.slice(0,4)) ? summary.months : [];
  const tracking = period >= "2026-11" && !!config && period <= config.current_month;
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
  const selectedMonthHasData = tally.totalReported > 0;
  const currentDateLabel = period ? monthLabel(period) : "mes seleccionado";

  const pendingRows = rows.filter(row => !row.complete)
    .sort((a, b) => Number(reported(a)) - Number(reported(b)) ||
      a.site_name.localeCompare(b.site_name, "es-CL"));
  const missingCount = rows.reduce((sum, row) =>
    sum + fields.filter(col => row[col.key] === null).length, 0);
  const filledCount = rows.length * fields.length - missingCount;
  const fieldProgress = percent(filledCount, rows.length * fields.length);
  const completedPercent = percent(tally.complete, rows.length);
  const noStarted = rows.filter(row => !reported(row)).length;
  const chosen = rows.find(row => rowKey(row) === expandedRow);
  const assignedNames = [...new Set(rows.map(row => row.supervisor.trim() || "Sin responsable definido"))];
  const responsible = assignedNames.map(name => {
    const data = rows.filter(row => (row.supervisor.trim() || "Sin responsable definido") === name);
    const complete = data.filter(row => row.complete).length;
    return { name, count: data.length, complete, pending: data.length - complete,
      progress: percent(complete, data.length) };
  }).sort((a, b) => b.pending - a.pending || a.name.localeCompare(b.name, "es-CL"));
  const annualRows = graph.filter(item => item.rows > 0 && item.period >= "2026-11" && item.period <= (config?.current_month || ""));
  const annualProgress = Math.round(
    annualRows.reduce((sum, item) => sum + item.complete, 0) /
    Math.max(1, annualRows.reduce((sum, item) => sum + item.rows, 0)) * 100);
  const openRow = (row: SheetRow) => {
    if (!row.editable || busy || loading) return;
    if (chosen && rowKey(chosen) !== rowKey(row) && dirty(chosen)) {
      setError("Guarda los cambios de la obra seleccionada antes de continuar."); return;
    }
    setSearch(""); setRowFilter("all");
    setExpandedRow(rowKey(row)); setEditingDetails("");
    window.setTimeout(() => {
      const input = document.getElementById("ine-cell-" + rowKey(row) + "-" +
        (fields.find(col => row[col.key] === null)?.key || "cct"));
      input?.focus({preventScroll:true});
      input?.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"nearest"});
    }, 60);
  };
  const gotoMonth = (next: string) => {
    if (!next || next === period || busy) return;
    if (chosen && dirty(chosen)) { setError("Guarda los cambios antes de cambiar de mes."); return; }
    ++monthRequest.current; ++summaryRequest.current;
    setLoading(true); setRows([]); setPeriod(next); setExpandedRow(""); setEditingDetails("");
    setRowFilter("all"); setSearch("");
  };

  return <main className="ine ine-v2051 ine-simplified ine-analytics-ux">
    <header className="ine-simple-header">
      <div className="ine-simple-heading">
        {onBack && <button className="ine-back" type="button" onClick={onBack}>
          <ArrowLeft size={15}/> Volver a GALANT</button>}
        <div className="ine-simple-caption"><FileSpreadsheet size={16}/> GALANT / INE
          <span>v{version || "20.5.1"}</span></div>
        <h1>INE · Control de obras</h1>
      </div>
      <div className="ine-simple-user">
        <span>{admin ? <ShieldCheck size={15}/> : <LockKeyhole size={15}/>}
          {admin ? "Administrador" : supervisor ? "Supervisor INE" : "Consulta"}</span>
        {logout && <button type="button" onClick={logout}>Cerrar sesión</button>}
      </div>
    </header>

    {error && <div className="ine-alert ine-error" role="alert">{error}
      <button type="button" onClick={() => setError("")} aria-label="Cerrar error"><X size={16}/></button></div>}
    {notice && <div className="ine-alert ine-success" role="status">{notice}
      <button type="button" onClick={() => setNotice("")} aria-label="Cerrar aviso"><X size={16}/></button></div>}

    <div className="ine-simple-toolbar">
      <label>Mes que deseas consultar
        <input aria-label="Seleccionar mes" type="month" value={period}
          onChange={event => gotoMonth(event.target.value)}/></label>
      {config && <div className="ine-simple-date-actions">
        <button type="button" className={period === config.current_month ? "selected" : ""}
          onClick={() => gotoMonth(config.current_month)}>Mes actual</button>
        <button type="button" className={period === config.previous_month ? "selected" : ""}
          onClick={() => gotoMonth(config.previous_month)}>Mes anterior</button>
      </div>}
      <button type="button" className="ine-simple-refresh" disabled={!period || loading}
        onClick={() => { if (chosen && dirty(chosen)) { setError("Guarda los cambios antes de actualizar."); return; } void Promise.all([loadMonth(period), loadSummary(period)]).catch(e => setError(errText(e))); }}>
        <RefreshCw size={15}/> Actualizar</button>
    </div>
    {period && <div className="ine-ux-months" aria-label="Meses del año">
      {monthsShort.map((label, index) => {
        const target = period.slice(0,4) + "-" + String(index+1).padStart(2,"0");
        return <button type="button" key={target} aria-pressed={period===target} disabled={!!busy}
          onClick={() => gotoMonth(target)}>{label}</button>;
      })}
    </div>}
    <nav className="ine-simple-tabs" aria-label="Secciones INE">
      <button type="button" className={tab === "registro" ? "selected" : ""}
        onClick={() => setTab("registro")}><FileSpreadsheet size={16}/> Rellenar y consultar</button>
      <button type="button" className={tab === "analisis" ? "selected" : ""}
        onClick={() => setTab("analisis")}><BarChart3 size={16}/> Análisis y evolución</button>
      <button type="button" className={tab === "historico" ? "selected" : ""}
        onClick={() => setTab("historico")}><BookOpenText size={16}/> Histórico del Excel</button>
      {admin && <button type="button" className={tab === "auditoria" ? "selected" : ""}
        onClick={() => setTab("auditoria")}><History size={16}/> Registro de cambios</button>}
      {admin && <button type="button" className={tab === "respaldo" ? "selected" : ""}
        onClick={() => setTab("respaldo")}><Download size={16}/> Respaldos</button>}
    </nav>

    {tab === "registro" && <>
      {!config?.source && !loading && <div className="ine-source-banner">
        <div><Info size={18}/><span><strong>El Excel original aún no se ha importado.</strong>
          {" "}Solo aparecen las obras ya registradas en GALANT.</span></div>
        {admin && <button type="button" onClick={() => setTab("respaldo")}>
          Importar Excel <ChevronRight size={15}/></button>}
      </div>}

      {tracking && <section className="ine-summary-card">
        <div className="ine-summary-primary">
          <span className="ine-overline">AVANCE DEL MES · {monthLabel(period)}</span>
          <div className="ine-summary-percent">{rows.length ? fieldProgress + "%" : "—"}</div>
          <strong>Información completada</strong>
          <div className="ine-progress-track">
            <div style={{width: fieldProgress + "%"}}/>
          </div>
          <p>{rows.length ? filledCount + " de " + rows.length * 5 + " campos informados" :
            "Todavía no hay datos para este período"}</p>
        </div>
        <div className="ine-summary-metrics">
          <div className="ine-stat"><span>Obras del mes</span><strong>{rows.length}</strong><small>Registros para controlar</small></div>
          <div className="ine-stat ine-stat-green"><span>Completas</span><strong>{tally.complete}</strong><small>{completedPercent}% de las obras</small></div>
          <div className="ine-stat ine-stat-amber"><span>Faltan completar</span><strong>{tally.pending}</strong><small>{missingCount} casillas pendientes</small></div>
          <div className="ine-stat ine-stat-red"><span>Sin comenzar</span><strong>{noStarted}</strong><small>Sin ninguna cifra informada</small></div>
        </div>
      </section>}

      <div className="ine-simple-insight">
        <Info size={15}/>{admin ? "Puedes editar cualquier mes y obra." :
          supervisor ? "Puedes revisar todos los meses, pero editar solo tus obras del mes actual y anterior." :
            "Consulta de solo lectura para tu perfil."}
        {" "}Las casillas vacías no se cuentan como cero.
      </div>

      {chosen && chosen.editable && editingDetails && <section id="ine-quick-editor" className="ine-simple-editor">
        <div className="ine-section-head">
          <div><span className="ine-eyebrow">EDICIÓN RÁPIDA</span>
            <h2>{chosen.site_name}</h2><p>Modifica las cifras y presiona Guardar. El Excel original no cambia.</p></div>
          <button type="button" className="ine-simple-close" onClick={() => setEditingDetails("")}><X size={16}/> Cerrar</button>
        </div>
        {admin && chosen.id && <div className="ine-details-access">
          <button type="button" className="ine-text-action" onClick={() => {
            if (editingDetails === chosen.id) setEditingDetails("");
            else { setDetailName(chosen.site_name); setDetailSupervisor(chosen.supervisor); setEditingDetails(chosen.id || ""); }
          }}><Pencil size={14}/> Editar nombre, supervisor o vínculo</button>
          {editingDetails === chosen.id && <div className="ine-details-editor">
            <label>Nombre de la obra<input value={detailName} maxLength={200}
              onChange={event => setDetailName(event.target.value)}/></label>
            <label>Supervisor<input value={detailSupervisor} maxLength={180}
              onChange={event => setDetailSupervisor(event.target.value)}/></label>
            <label>Vincular a GALANT<select value={chosen.site_id || ""}
              onChange={event => void linkRow(chosen, event.target.value)}>
              <option value="">Sin vincular</option>{config?.sites.map(site =>
                <option value={site.id} key={site.id}>{site.name}</option>)}</select></label>
            <button type="button" className="ine-save" disabled={!!busy || !detailName.trim()}
              onClick={() => void saveDetails(chosen)}><Save size={15}/> Guardar</button>
          </div>}
        </div>}
        <div className="ine-simple-fields">{fields.map(col => <label key={col.key}>
          <span>{col.label}</span><small>{col.hint}</small>
          <input type="number" min={0} max={1000000} step={1} placeholder="Pendiente"
            aria-label={col.hint + " de " + chosen.site_name} disabled={!!busy}
            value={value(chosen, col.key)} onChange={event => setValue(chosen, col.key, event.target.value)}/>
        </label>)}</div>
        <div className="ine-simple-save">
          <span>{dirty(chosen) ? "Cambios sin guardar" : "Sin cambios pendientes"}</span>
          <button type="button" className="ine-save" disabled={!dirty(chosen) || !!busy}
            onClick={() => void saveRow(chosen)}><Save size={16}/>
              {busy === rowKey(chosen) ? "Guardando…" : "Guardar cifras"}</button>
        </div>
      </section>}

      {admin && showNew && <section className="ine-new-record ine-simple-new">
        <div className="ine-section-head"><div><span className="ine-eyebrow">ADMINISTRADOR</span>
          <h2>Agregar una obra</h2><p>También puedes crear registros de meses anteriores.</p></div>
          <button type="button" className="ine-simple-close" onClick={() => setShowNew(false)}><X size={15}/> Cerrar</button></div>
        <div className="ine-new-grid">
          <label>Obra GALANT (opcional)<select value={newSiteId} onChange={event => {
            const id = event.target.value; setNewSiteId(id);
            const site = config?.sites.find(item => item.id === id);
            if (site) setNewName(site.name);
          }}><option value="">Sin vincular</option>
            {config?.sites.map(site => <option value={site.id} key={site.id}>{site.name}</option>)}</select></label>
          <label>Nombre de la obra<input value={newName} maxLength={200}
            placeholder="Nombre de la obra" onChange={event => setNewName(event.target.value)}/></label>
        </div>
        <div className="ine-new-counts">{fields.map(col => <label key={col.key}>
          <span>{col.label}</span><input type="number" min={0} max={1000000} step={1}
            value={newCounts[col.key]} placeholder="Pendiente"
            onChange={event => setNewCounts(previous => ({...previous, [col.key]: event.target.value}))}/>
        </label>)}</div>
        <div className="ine-new-actions"><small>Los valores sin información se dejan vacíos.</small>
          <button type="button" className="ine-save" disabled={!newName.trim() || !!busy}
            onClick={() => void createManual()}><Plus size={15}/> Crear obra</button></div>
      </section>}

      {tracking && <section className="ine-dashboard-main">
        <div className="ine-dashboard-section-head">
          <div><span className="ine-eyebrow">PRIORIDADES</span><h2>¿Quiénes faltan?</h2>
            <p>Obras que necesitan completar o informar datos de {monthLabel(period)}.</p></div>
          <span className="ine-pending-count">{pendingRows.length} pendientes</span>
        </div>
        {loading ? <p className="ine-loading" role="status">Cargando obras…</p> : pendingRows.length ? <div className="ine-missing-list">
          {pendingRows.slice(0, 8).map(row => {
            const missing = fields.filter(col => row[col.key] === null);
            const filled = 5 - missing.length;
            return <div className="ine-missing-item" key={rowKey(row)}>
              <div className={"ine-missing-dot " + (!reported(row) ? "urgent" : "")}/>
              <div className="ine-missing-body">
                <strong>{row.site_name}</strong>
                <small>{row.supervisor || "Responsable no indicado en el Excel"}</small>
                <div className="ine-missing-tags">{missing.map(col =>
                  <span key={col.key}>{col.label}</span>)}</div>
              </div>
              <div className="ine-missing-progress"><strong>{filled}/5</strong>
                <div className="ine-mini-progress"><span style={{width:(filled / 5 * 100)+"%"}}/></div></div>
              {row.editable ? <button type="button" className="ine-list-edit"
                onClick={() => openRow(row)}>Completar <ChevronRight size={14}/></button> :
                <span className="ine-readonly-pill"><LockKeyhole size={12}/> Lectura</span>}
            </div>;
          })}</div> :
          <div className="ine-simple-empty"><CheckCircle2 size={24}/>
            <strong>{rows.length ? "Todas las obras están completas" : "Sin registros de este mes"}</strong>
            <span>{rows.length ? "No hay campos pendientes." : "Elige otro mes o carga el Excel original."}</span></div>}
        {pendingRows.length > 8 && <button type="button" className="ine-show-rest" onClick={() => {
          setRowFilter("pending");
          document.getElementById("ine-all-rows")?.scrollIntoView({behavior:"smooth"});
        }}>Ver todas las {pendingRows.length} obras pendientes <ChevronRight size={15}/></button>}
      </section>}

      {tracking && <div className="ine-dashboard-charts">
        <section className="ine-simple-chart">
          <div className="ine-chart-head"><span className="ine-eyebrow">EVOLUCIÓN</span>
            <h3>Progreso por mes</h3><p>Porcentaje de obras con los cinco datos completos.</p></div>
          <div className="ine-annual-bars">
            {graph.map((item, index) => {
              const eligible = item.period >= "2026-11" && item.period <= (config?.current_month || "");
              const progress = percent(item.complete, item.rows);
              return <div className="ine-annual-col" key={item.period}
                title={monthLabel(item.period) + " · " + (eligible && item.rows ? progress + "% de obras completas" : "sin seguimiento")}>
                <span>{eligible && item.rows ? progress + "%" : "—"}</span>
                <div className="ine-annual-track"><i className={eligible && item.rows ? "filled" : ""}
                  style={{height: eligible && item.rows ? progress + "%" : "0%"}}/></div>
                <small>{monthsShort[index]}</small>
              </div>;
            })}
          </div>
          <p className="ine-chart-bottom">Avance desde noviembre 2026: <strong>{annualRows.length ? annualProgress + "%" : "Sin datos"}</strong></p>
        </section>
        <section className="ine-simple-chart">
          <div className="ine-chart-head"><span className="ine-eyebrow">RESPONSABLES</span>
            <h3>Avance por supervisor</h3><p>Comparación de las obras agrupadas por el supervisor indicado en el Excel.</p></div>
          {responsible.length ? <div className="ine-responsible-list">{responsible.map(item =>
            <div className="ine-responsible-row" key={item.name}>
              <div><button type="button" className="ine-table-edit" title={item.name} onClick={()=>{setSearch(item.name==="Sin responsable definido"?"":item.name);setRowFilter("all");document.getElementById("ine-all-rows")?.scrollIntoView({block:"nearest"});}}>{item.name}</button>
                <small>{item.pending ? item.pending + " pendiente(s)" : "Completo"}</small></div>
              <div className="ine-responsible-track"><span style={{width:item.progress+"%"}}/></div>
              <b>{item.progress}%</b>
            </div>)}</div> :
            <div className="ine-simple-empty"><Info size={23}/><span>No hay responsables para mostrar.</span></div>}
        </section>
      </div>}

      <section className="ine-chart-disclosure">
        <button type="button" onClick={() => setMoreCharts(previous => !previous)}>
          <BarChart3 size={17}/>{moreCharts ? "Ocultar" : "Ver"} más gráficos de contratistas y trabajadores
          <ChevronRight size={16} className={moreCharts ? "ine-rotated" : ""}/></button>
        {moreCharts && <div className="ine-extra-charts">
          <section className="ine-simple-chart">
            <div className="ine-chart-head"><h3>Contratistas por mes</h3><p>CCT + CESP + IND.</p></div>
            <div className="ine-volume-bars">{graph.map((item, index) => {
              const total = sumFields(item, ["cct", "cesp", "ind"]);
              return <div className="ine-volume-col" key={item.period} title={monthLabel(item.period)+": "+(item.reported? total : "sin cifras")}>
                <span>{item.reported ? fmtNumber(total) : "—"}</span><div><i style={{height:item.reported ? Math.max(3,total/maxContract*100)+"%" : "0%"}}/></div>
                <small>{monthsShort[index]}</small>
              </div>;
            })}</div>
          </section>
          <section className="ine-simple-chart">
            <div className="ine-chart-head"><h3>Trabajadores por mes</h3><p>TH + TM (escala independiente).</p></div>
            <div className="ine-volume-bars ine-workers-bars">{graph.map((item,index) => {
              const total = sumFields(item,["th","tm"]);
              return <div className="ine-volume-col" key={item.period} title={monthLabel(item.period)+": "+(item.reported?total:"sin cifras")}>
                <span>{item.reported?fmtNumber(total):"—"}</span><div><i style={{height:item.reported?Math.max(3,total/maxWorkers*100)+"%":"0%"}}/></div>
                <small>{monthsShort[index]}</small>
              </div>;
            })}</div>
          </section>
          <section className="ine-simple-chart ine-extra-full">
            <div className="ine-chart-head"><h3>Composición de las cifras del mes</h3>
              <p>Desglose por categoría para {monthLabel(period)}.</p></div>
            <div className="ine-split-categories">
              {fields.map(col => {
                const total = rows.reduce((sum, row) => sum + (row[col.key] || 0),0);
                const maxTotal = Math.max(1, ...fields.map(c => rows.reduce((sum,row)=>sum+(row[c.key]||0),0)));
                return <div className={"ine-category-row ine-category-"+col.color} key={col.key}>
                  <span>{col.hint}</span><div><i style={{width:(total/maxTotal*100)+"%"}}/></div>
                  <strong>{rows.some(reported) ? fmtNumber(total) : "—"}</strong>
                </div>;
              })}
            </div>
          </section>
        </div>}
      </section>

      <section id="ine-all-rows" className="ine-all-rows">
        <div className="ine-dashboard-section-head">
          <div><span className="ine-eyebrow">REGISTRO MENSUAL</span><h2>Todas las obras</h2>
            <p>Selecciona una obra para rellenar sus cifras directamente en la tabla.</p></div>
          {admin && <button type="button" className="ine-primary-action" onClick={() => {
            setShowNew(true);
            window.setTimeout(() => document.querySelector(".ine-simple-new")?.scrollIntoView({behavior:"smooth"}), 50);
          }}><Plus size={15}/> Agregar obra</button>}
        </div>
        <div className="ine-all-filters">
          <label className="ine-search"><Search size={16}/>
            <input type="search" value={search} onChange={event => setSearch(event.target.value)}
              placeholder="Buscar obra o supervisor" aria-label="Buscar obra o supervisor"/></label>
          <div className="ine-filter-buttons">
            {(tracking ? [["all","Todas"],["pending","Por rellenar"],["complete","Completas"]] : [["all","Todas"]]).map(([key,label]) =>
              <button type="button" key={key} className={rowFilter===key?"selected":""}
                onClick={()=>setRowFilter(key)}>{label}</button>)}
          </div>
          <span className="ine-table-count">{filteredRows.length} obras</span>
        </div>
        <div className="ine-table-wrap"><table className="ine-control-table">
          <thead><tr><th>Obra / responsable</th>{tracking && <><th>Estado</th><th>Avance</th></>}
            {fields.map(col=><th key={col.key} title={col.hint}>{col.label}</th>)}<th></th></tr></thead>
          <tbody>{filteredRows.map(row=>{
            const filled=fields.filter(col=>row[col.key]!==null).length;
            const editing = expandedRow === rowKey(row) && row.editable;
            return <tr key={rowKey(row)} className={(tracking ? row.complete ? "ine-ux-done" : reported(row) ? "ine-ux-part" : "ine-ux-empty" : "") + (editing ? " ine-ux-editing" : "")}>
              <td><strong>{row.site_name}</strong><small>{row.supervisor || "—"}</small></td>
              {tracking && <><td><span className={"ine-table-status "+(row.complete?"done":reported(row)?"part":"empty")}>
                {row.complete?<><CheckCircle2 size={13}/> Completa</>:reported(row)?"En progreso":"Por rellenar"}</span></td>
              <td><div className="ine-table-progress"><span style={{width:(filled/5*100)+"%"}}/></div><small>{filled}/5</small></td></>}
              {fields.map((col,index)=><td className={tracking && row[col.key]===null?"ine-null":""} key={col.key}>
                {editing ? <input className={"ine-ux-cell " + (tracking && value(row,col.key)==="" ? "missing" : "")}
                  id={"ine-cell-"+rowKey(row)+"-"+col.key} type="number" min={0} max={1000000} step={1}
                  aria-label={col.hint+" de "+row.site_name} placeholder="—" disabled={!!busy}
                  value={value(row,col.key)} onChange={event=>setValue(row,col.key,event.target.value)}
                  onKeyDown={event=>{
                    if(event.key==="Enter"){event.preventDefault();const next=fields[index+1];
                      if(next) document.getElementById("ine-cell-"+rowKey(row)+"-"+next.key)?.focus();
                      else if(dirty(row)&&!busy) void saveRow(row);}
                  }}/> : row[col.key]===null?"—":fmtNumber(row[col.key]??0)}</td>)}
              <td><div className="ine-ux-actions">{row.editable ? editing ? <>
                <button type="button" className="ine-save" disabled={!!busy || !dirty(row)} onClick={()=>void saveRow(row)}>
                  <Save size={14}/>{busy===rowKey(row)?"Guardando…":"Guardar"}</button>
                <button type="button" className="ine-table-edit" disabled={!!busy || dirty(row)} onClick={()=>{setExpandedRow("");setEditingDetails("");}}>Cerrar</button>
                {admin && row.id && <button type="button" className="ine-table-edit" disabled={!!busy || dirty(row)} onClick={()=>{setDetailName(row.site_name);setDetailSupervisor(row.supervisor);setEditingDetails(row.id || "");window.setTimeout(()=>document.getElementById("ine-quick-editor")?.scrollIntoView({block:"nearest"}),50);}}>Datos de obra</button>}
                </> : <button type="button" className="ine-table-edit" disabled={!!busy || loading} onClick={()=>openRow(row)}>Rellenar <Pencil size={13}/></button>
                : <LockKeyhole size={14} color="#94a3b8"/>}</div></td>
            </tr>;
          })}</tbody></table>
          {!filteredRows.length && <div className="ine-simple-empty"><Info size={22}/>
            <span>No hay obras que coincidan con esta búsqueda.</span></div>}
        </div>
      </section>
    </>}

    {tab === "analisis" && !loading && period && <IneAnalytics key={period.slice(0,4)} period={period} rows={rows} graph={graph} onMonth={gotoMonth}/>}
    {tab === "historico" && <section className="ine-panel ine-history-library">
      <div className="ine-section-head"><div><span className="ine-eyebrow">CONSULTA DE SOLO LECTURA</span>
        <h2>Histórico del Excel</h2><p>Consulta cualquier hoja original. No se modifican sus cifras ni fórmulas.</p></div>
        <span className="ine-history-lock"><LockKeyhole size={14}/> Solo lectura</span></div>
      {archive?.sheets.length ? <div className="ine-archive-layout">
        <aside className="ine-archive-sidebar">
          <div className="ine-archive-search"><Search size={15}/><input type="search"
            value={archiveSearch} onChange={event=>setArchiveSearch(event.target.value)}
            placeholder="Buscar hoja" aria-label="Buscar hoja"/></div>
          <select aria-label="Filtrar año" value={archiveFilter} onChange={event=>setArchiveFilter(event.target.value)}>
            {sheetGroups.map(group=><option key={group} value={group}>{group}</option>)}</select>
          <p>{archive.sheets.length} hojas disponibles</p>
          <div className="ine-sheet-list">{sheets.map(sheet=><button type="button" key={sheet.id}
            className={selectedSheet===sheet.id?"selected":""} onClick={()=>setSelectedSheet(sheet.id)}>
            <span><BookOpenText size={13}/>{sheet.name}</span></button>)}</div>
        </aside>
        <div className="ine-archive-main">
          {busy==="sheet"||!preview?<div className="ine-loading">Cargando hoja…</div>:<>
            <div className="ine-archive-heading"><div><span>EXCEL ORIGINAL</span><h3>{preview.name}</h3>
              <p>{preview.rows.length} filas con contenido</p></div><span><LockKeyhole size={14}/> Protegido</span></div>
            <div className="ine-table-scroll ine-historic-scroll"><table className="ine-original-table">
              <thead><tr><th>Fila</th>{columns.map(col=><th key={col}>{col}</th>)}</tr></thead>
              <tbody>{preview.rows.map(line=><tr key={line.row}><th>{line.row}</th>
                {columns.map(col=>{
                  const val=line.cells[col],display=val==null?"":String(val);
                  return <td key={col} title={line.formulas?.[col]||display}
                    className={(display.startsWith("#")?"ine-error-cell ":"")+
                    (line.formulas?.[col]?"ine-formula-cell":"")}>{display}</td>;
                })}</tr>)}</tbody></table></div>
            <p className="ine-footnote"><Info size={14}/> Las fórmulas del Excel se conservan. Puede haber errores presentes en el archivo original.</p>
          </>}
        </div>
      </div>:<div className="ine-simple-empty"><BookOpenText size={26}/>
        <strong>Histórico pendiente de cargar</strong><span>El administrador debe importar el Excel original una vez.</span>
        {admin&&<button type="button" className="ine-primary-action" onClick={()=>setTab("respaldo")}>Ir a importar</button>}
      </div>}
    </section>}

    {tab === "auditoria" && admin && <section className="ine-panel">
      <div className="ine-section-head"><div><span className="ine-eyebrow">SOLO ADMINISTRADORES</span>
        <h2>Registro de cambios</h2><p>Quién modificó una obra, cuándo y qué cifras cambiaron.</p></div>
        <span className="ine-history-lock"><ShieldCheck size={14}/> Privado</span></div>
      {audit.length?<div className="ine-history">{audit.map(log=><article key={log.id}>
        <div><b>{log.actor_name}</b><time>{new Date(log.created_at).toLocaleString("es-CL",{timeZone:"America/Santiago"})}</time></div>
        <p>{log.site_name} · {monthLabel(log.period)} · {log.action==="create"?"Nuevo registro":log.action==="link"?"Vinculación":log.action==="details"?"Datos de obra":"Modificación"}</p>
        {changedFields(log).map(field=><div className="ine-diff" key={field}>
          <strong>{field.toUpperCase()}</strong><span>{String(log.previous[field]??"Vacío")}</span>
          <ChevronRight size={13}/><b>{String(log.current[field]??"Vacío")}</b></div>)}</article>)}</div>:
        <div className="ine-simple-empty"><Info size={23}/><span>Todavía no se registran cambios.</span></div>}
    </section>}

    {tab === "respaldo" && admin && <section className="ine-panel ine-backup-panel">
      <div className="ine-section-head"><div><span className="ine-eyebrow">ARCHIVOS</span>
        <h2>Excel original y respaldo</h2><p>El archivo original se conserva intacto. Los cambios se guardan en GALANT.</p></div></div>
      <div className="ine-archive-actions">
        <div className="ine-archive-card"><BookOpenText size={24}/><h3>Excel original</h3>
          <p>{config?.source?.name || "Todavía no se ha importado."}</p>
          {config?.source&&<button type="button" onClick={()=>void downloadFile("/ine/original","INE-original-sin-modificaciones.xlsx").catch(e=>setError(errText(e)))}>
            <Download size={15}/> Descargar original</button>}</div>
        <div className="ine-archive-card"><Download size={24}/><h3>Respaldo de GALANT</h3>
          <p>Descarga las cifras registradas del año {period.slice(0,4)}.</p>
          <button type="button" onClick={()=>void downloadFile("/ine/export?year="+period.slice(0,4),
            "GALANT-INE-respaldo-"+period.slice(0,4)+".xlsx").catch(e=>setError(errText(e)))}>
            <Download size={15}/> Descargar respaldo</button></div>
      </div>
      {!config?.source&&<section className="ine-import"><h3>Importar el Excel original</h3>
        <p>Solo una vez. El archivo original se conserva sin modificaciones y todas sus hojas podrán consultarse.</p>
        <div className="ine-import-form">
          <label>Año<input type="number" min={1900} max={2199} value={uploadYear}
            onChange={event=>setUploadYear(Number(event.target.value))}/></label>
          <label>Archivo .xlsx<input type="file" accept=".xlsx"
            onChange={event=>setUpload(event.target.files?.[0]||null)}/></label>
          <button type="button" disabled={!upload||!!busy} onClick={()=>void importExcel()}>
            <UploadCloud size={15}/>{busy==="import"?"Transcribiendo…":"Transcribir sin modificar"}</button>
        </div></section>}
    </section>}
  </main>;
}


type Metric = "workers" | "contractors" | "ind";
const metricFields: Record<Metric, Field[]> = {workers:["th","tm"],contractors:["cct","cesp","ind"],ind:["ind"]};
const metricLabels: Record<Metric,string> = {workers:"Trabajadores",contractors:"Contratistas",ind:"Independientes"};
function observed(row: Counts, metric: Metric) {
  return metricFields[metric].every(key=>row[key]!==null) ? sumFields(row,metricFields[metric]) : null;
}
function IneAnalytics({period,rows,graph,onMonth}: {period:string;rows:SheetRow[];graph:MonthSummary[];onMonth:(period:string)=>void}) {
  const [metric,setMetric]=useState<Metric>("workers");
  const [site,setSite]=useState("");
  const [history,setHistory]=useState<Record<string,SheetRow[]> | null>(null);
  const [historyError,setHistoryError]=useState("");
  const year=period.slice(0,4);
  const identity=(r:SheetRow)=>r.site_id ? "site:"+r.site_id : "name:"+r.site_name;
  const allSites=Array.from(new Map([...Object.values(history||{}).flat(),...rows].map(r=>[identity(r),r])).values()).sort((a,b)=>a.site_name.localeCompare(b.site_name,"es-CL"));
  const selected=allSites.find(r=>identity(r)===site);
  useEffect(()=>{
    let active=true; setHistory(null); setHistoryError("");
    const periods=Array.from({length:12},(_,i)=>year+"-"+String(i+1).padStart(2,"0"));
    void Promise.all(periods.map(async target=>{
      const result=await request<{rows:SheetRow[]}>("/ine/rows?period="+encodeURIComponent(target));
      return [target,result.rows] as const;
    })).then(items=>{if(active)setHistory(Object.fromEntries(items));})
      .catch(e=>{if(active)setHistoryError(errText(e));});
    return()=>{active=false;};
  },[year]);
  const totals=fields.map(f=>({ ...f, value: rows.reduce((n,r)=>n+(r[f.key]??0),0), known:rows.filter(r=>r[f.key]!==null).length }));
  const workers=totals[3].value+totals[4].value, contractors=totals[0].value+totals[1].value+totals[2].value;
  const ranked=rows.map(row=>({name:row.site_name,key:identity(row),value:observed(row,metric)}))
    .filter((item):item is {name:string;key:string;value:number}=>item.value!==null).sort((a,b)=>b.value-a.value);
  const peak=ranked[0];
  const points=Array.from({length:12},(_,i)=>{
    const target=year+"-"+String(i+1).padStart(2,"0");
    const monthRows=target===period ? rows : history?.[target]||[];
    const matches=site?monthRows.filter(r=>identity(r)===site):monthRows;
    const known=matches.filter(r=>metricFields[metric].some(key=>r[key]!==null));
    const value=site ? matches.length===1?observed(matches[0],metric):null :
      known.length ? known.reduce((sum,r)=>sum+sumFields(r,metricFields[metric]),0):null;
    return {period:target,label:monthsShort[i],value,coverage:known.length};
  });
  const scale=Math.max(1,...points.map(p=>p.value??0));
  const current=points.find(p=>p.period===period);
  const previousIndex=points.findIndex(p=>p.period===period)-1;
  const previous=points[previousIndex];
  const delta=current?.value!=null && previous?.value!=null ? current.value-previous.value : null;
  const observedCount=rows.filter(row=>observed(row,metric)!==null).length;
  const knownWorkers=totals.slice(3).some(f=>f.known>0), knownContractors=totals.slice(0,3).some(f=>f.known>0);
  return <section className="ine-ux-analysis">
    <div className="ine-dashboard-section-head"><div><h2>Análisis de {monthLabel(period)}</h2><p>Cifras registradas · {rows.filter(reported).length} obras con información de {rows.length}</p></div></div>
    <div className="ine-ux-kpis">
      <div><span>Trabajadores</span><strong>{numOrDash(workers,knownWorkers)}</strong><small>{numOrDash(totals[3].value,totals[3].known>0)} hombres · {numOrDash(totals[4].value,totals[4].known>0)} mujeres</small></div>
      <div><span>Contratistas</span><strong>{numOrDash(contractors,knownContractors)}</strong><small>Permanentes + esporádicos + independientes</small></div>
      <div><span>Independientes</span><strong>{numOrDash(totals[2].value,totals[2].known>0)}</strong><small>Sobre cifras informadas</small></div>
    </div>
    <div className="ine-ux-insights"><strong>Lectura de los datos</strong>
      <p>{peak ? peak.name+" registra la mayor cantidad de "+metricLabels[metric].toLowerCase()+" ("+fmtNumber(peak.value)+"), entre "+observedCount+" obras con esta cifra completa." : "No hay cifras completas para comparar obras en este indicador."}</p>
      {totals[2].known>0 && knownContractors && contractors>0 && <p>Los independientes representan {Math.round(totals[2].value/contractors*100)}% de los contratistas registrados (CCT + CESP + IND). No equivale al porcentaje oficial de independientes de la planilla.</p>}
    </div>
    <div className="ine-ux-analysis-grid">
      <section className="ine-simple-chart"><h3>Composición de contratistas</h3>
        {totals.slice(0,3).map((f,i)=><div key={f.key} className="ine-ux-bar-row"><span>{f.hint}</span><div><i style={{width:(contractors?f.value/contractors*100:0)+"%",background:["#245c88","#469b90","#c18a47"][i]}}/></div><b>{numOrDash(f.value,f.known>0)}</b></div>)}
      </section>
      <section className="ine-simple-chart"><h3>Dotación de trabajadores</h3>
        {totals.slice(3).map((f,i)=><div key={f.key} className="ine-ux-bar-row"><span>{f.hint}</span><div><i style={{width:(workers?f.value/workers*100:0)+"%",background:["#245c88","#469b90"][i]}}/></div><b>{numOrDash(f.value,f.known>0)}</b></div>)}
      </section>
    </div>
    <section className="ine-simple-chart ine-ux-trend">
      <div className="ine-ux-chart-head"><div><h3>Evolución {year}</h3><p>{selected?selected.site_name:"Todas las obras · cifras registradas"}</p></div>
        <label>Indicador<select value={metric} onChange={e=>setMetric(e.target.value as Metric)}>{Object.entries(metricLabels).map(([k,label])=><option key={k} value={k}>{label}</option>)}</select></label>
        <label>Obra<select value={site} onChange={e=>setSite(e.target.value)}><option value="">Todas las obras</option>{allSites.map(r=><option key={identity(r)} value={identity(r)}>{r.site_name}</option>)}</select></label>
      </div>
      {!history && !historyError ? <p role="status">Consultando evolución…</p> : historyError ? <p role="alert">{historyError}</p> :
      <><div className="ine-ux-line-scroll"><svg viewBox="0 0 720 245" role="img" aria-label={"Evolución anual de "+metricLabels[metric]}>
        {[0,.25,.5,.75,1].map(f=><g key={f}><line x1="45" x2="700" y1={200-f*165} y2={200-f*165} stroke="#dce5ec"/><text x="38" y={204-f*165} textAnchor="end" fontSize="11" fill="#617589">{fmtNumber(Math.round(scale*f))}</text></g>)}
        {points.map((p,i)=>{const prev=points[i-1];const x=50+i*58;const y=200-(p.value??0)/scale*165;return <g key={p.period}>
          {p.value!==null && prev && prev.value!==null && <line x1={x-58} y1={200-prev.value/scale*165} x2={x} y2={y} stroke="#297f78" strokeWidth="3"/>}
          {p.value!==null&&<circle cx={x} cy={y} r={p.period===period?6:4} fill={p.period===period?"#1d3b58":"#297f78"}><title>{p.label}: {fmtNumber(p.value)}</title></circle>}
          <text x={x} y="223" fontSize="11" fill="#617589" textAnchor="middle">{p.label}</text>
        </g>;})}
      </svg></div>
      <p>{delta===null?"No hay dos meses consecutivos con cifras para comparar.": "Variación registrada frente al mes anterior: "+(delta>0?"+":"")+fmtNumber(delta)+ (previous?.value ? " ("+(delta>0?"+":"")+(delta/previous.value*100).toFixed(1)+"%).":".")} {!site && "La cobertura de obras puede variar entre meses."}</p>
      <div className="ine-ux-month-values">{points.map(p=><button key={p.period} type="button" aria-pressed={p.period===period} onClick={()=>onMonth(p.period)}><span>{p.label}</span><b>{p.value===null?"—":fmtNumber(p.value)}</b></button>)}</div></>}
    </section>
    <section className="ine-simple-chart"><h3>Comparación por obra · {metricLabels[metric]}</h3><p>Selecciona una obra para analizar su historial.</p>
      {ranked.map(item=><button type="button" key={item.key} className="ine-ux-bar-row ine-ux-rank" onClick={()=>setSite(item.key)}><span>{item.name}</span><div><i style={{width:(peak?.value?item.value/peak.value*100:0)+"%"}}/></div><b>{fmtNumber(item.value)}</b></button>)}
      {!ranked.length && <p>Sin cifras completas para este indicador.</p>}
    </section>
  </section>;
}
