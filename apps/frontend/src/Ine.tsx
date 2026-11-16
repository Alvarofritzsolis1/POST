import { useCallback, useEffect, useMemo, useState } from "react";
import type { Profile } from "./api";
import { request } from "./api";
import { ArrowLeft, BarChart3, CheckCircle2, Clock3, Download, FileSpreadsheet, History, LockKeyhole, RefreshCw, Save, Search, UploadCloud } from "lucide-react";
import "./ine.css";

type Field = "cct" | "cesp" | "ind" | "th" | "tm";
type Counts = Record<Field, number | null>;
type Site = {id: string; name: string};
type SheetRow = Counts & {
  id: string | null; period: string; site_id: string | null;
  site_name: string; supervisor: string; complete: boolean;
  editable: boolean; version: number; source_sheet: string; source_row: number;
  source_status: string | null; source_total: number | null; source_percent: number | null;
};
type Configuration = {
  role: string; current_month: string; previous_month: string;
  sites: Site[]; source: {name: string; sha256: string; id: string} | null;
};
type Summary = {year: number; months: (Counts & {period: string; rows: number; complete: number; pending: number})[]};
type Log = {
  id: string; actor_name: string; action: string; period: string; site_name: string;
  previous: Record<string, unknown>; current: Record<string, unknown>; created_at: string;
};
type Archive = {sheets: {id: string; name: string; rows: number}[]};
type ArchiveSheet = {name: string; rows: {row: number; cells: Record<string, unknown>}[]};

const cols: {key: Field; label: string; hint: string}[] = [
  {key: "cct", label: "CCT", hint: "Contratistas permanentes"},
  {key: "cesp", label: "CESP", hint: "Contratistas esporádicos"},
  {key: "ind", label: "IND", hint: "Independientes"},
  {key: "th", label: "TH", hint: "Trabajadores hombres"},
  {key: "tm", label: "TM", hint: "Trabajadoras mujeres"},
];
const number = (value: number) => value.toLocaleString("es-CL");
const msg = (err: unknown) => err instanceof Error ? err.message : String(err);
const formatMonth = (s: string) => {
  const [y, m] = s.split("-").map(Number);
  return new Intl.DateTimeFormat("es-CL", {month: "long", year: "numeric", timeZone: "UTC"})
    .format(new Date(Date.UTC(y, m - 1, 1)));
};
const rowKey = (row: SheetRow) => row.id || "site:" + row.site_id;
const parseValue = (s: string): number | null => s === "" ? null : Number(s);
const changedFields = (log: Log) => Object.keys(log.current).filter(key => log.previous[key] !== log.current[key]);
const exportFile = async (url: string, filename: string) => {
  const response = await fetch("/api/v1" + url, {credentials: "include", cache: "no-store"});
  if (!response.ok) throw new Error("No fue posible descargar el respaldo");
  const link = document.createElement("a");
  const objectUrl = URL.createObjectURL(await response.blob());
  link.href = objectUrl; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1200);
};

export default function Ine({user, version, onBack, logout}: {
  user: Profile; version?: string | null; onBack?: () => void; logout?: () => void;
}) {
  const admin = user.role === "admin";
  const [config, setConfig] = useState<Configuration | null>(null);
  const [period, setPeriod] = useState("");
  const [rows, setRows] = useState<SheetRow[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Record<Field, string>>>({});
  const [summary, setSummary] = useState<Summary | null>(null);
  const [logs, setLogs] = useState<Log[]>([]);
  const [archive, setArchive] = useState<Archive | null>(null);
  const [preview, setPreview] = useState<ArchiveSheet | null>(null);
  const [selectedSheet, setSelectedSheet] = useState("");
  const [tab, setTab] = useState<"registro" | "analisis" | "historial" | "archivo">("registro");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState("");
  const [uploadYear, setUploadYear] = useState(2026);
  const [upload, setUpload] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  const loadConfig = useCallback(async () => {
    const settings = await request<Configuration>("/ine/config");
    setConfig(settings);
    setPeriod(old => old || settings.current_month);
    return settings;
  }, []);
  const loadMonth = useCallback(async (target: string) => {
    const response = await request<{rows: SheetRow[]}>("/ine/rows?period=" + target);
    setRows(response.rows);
    setDrafts({});
  }, []);
  const loadSummary = useCallback(async (target: string) => {
    setSummary(await request<Summary>("/ine/summary?year=" + target.slice(0, 4)));
  }, []);
  useEffect(() => {
    let active = true;
    void loadConfig().catch(e => {if(active) setError(msg(e));})
      .finally(() => {if(active) setLoading(false);});
    return () => {active = false;};
  }, [loadConfig]);
  useEffect(() => {
    if (!period) return;
    let active = true;
    setLoading(true);
    void Promise.all([loadMonth(period), loadSummary(period)]).catch(e => {
      if(active) setError(msg(e));
    }).finally(() => {if(active) setLoading(false);});
    return () => {active = false;};
  }, [period, loadMonth, loadSummary]);
  useEffect(() => {
    if (tab === "historial" && admin) void request<Log[]>("/ine/history?limit=150")
      .then(setLogs).catch(e => setError(msg(e)));
    if (tab === "archivo" && admin) void request<Archive>("/ine/archive")
      .then(setArchive).catch(e => setError(msg(e)));
  }, [tab, admin]);

  const visibleRows = useMemo(() => rows.filter(row => {
    if (search && !(row.site_name + " " + row.supervisor).toLocaleLowerCase("es-CL").includes(search.toLocaleLowerCase("es-CL"))) return false;
    if (filter === "pending" && row.complete) return false;
    if (filter === "complete" && !row.complete) return false;
    if (filter === "linked" && !row.site_id) return false;
    return true;
  }), [rows, search, filter]);
  const totals = useMemo(() => {
    const sum = (field: Field) => rows.reduce((acc, row) => acc + (row[field] || 0), 0);
    return {contractors: sum("cct") + sum("cesp") + sum("ind"),
            workers: sum("th") + sum("tm"),
            complete: rows.filter(r => r.complete).length,
            pending: rows.filter(r => !r.complete).length};
  }, [rows]);
  const dirty = (row: SheetRow) => {
    const draft = drafts[rowKey(row)];
    return !!draft && cols.some(col => parseValue(draft[col.key]) !== row[col.key]);
  };
  function value(row: SheetRow, key: Field): string {
    return drafts[rowKey(row)]?.[key] ?? (row[key] === null ? "" : String(row[key]));
  }
  function setValue(row: SheetRow, field: Field, next: string) {
    setDrafts(old => {
      const id = rowKey(row);
      const defaults = Object.fromEntries(cols.map(c => [c.key, row[c.key] === null ? "" : String(row[c.key])])) as Record<Field, string>;
      return {...old, [id]: {...(old[id] || defaults), [field]: next}};
    });
  }
  async function save(row: SheetRow) {
    const key = rowKey(row);
    setBusy(key); setError(""); setNotice("");
    try {
      const data = Object.fromEntries(cols.map(c => [c.key, parseValue(value(row, c.key))]));
      if (Object.values(data).some(v => v !== null && (!Number.isSafeInteger(v) || Number(v) < 0))) {
        throw Error("Ingresa números enteros mayores o iguales a cero");
      }
      if (row.id) {
        await request("/ine/rows/" + row.id, {method: "PUT", body: JSON.stringify({...data, version: row.version})});
      } else {
        await request("/ine/rows", {method: "POST", body: JSON.stringify({
          ...data, version: 0, site_id: row.site_id, period,
        })});
      }
      await Promise.all([loadMonth(period), loadSummary(period)]);
      setNotice("Guardado correctamente. El registro de auditoría quedó protegido.");
    } catch (err) {setError(msg(err));}
    finally {setBusy("");}
  }
  async function link(row: SheetRow, next: string) {
    if (!row.id) return;
    setBusy(rowKey(row)); setError("");
    try {
      await request("/ine/rows/" + row.id + "/link", {
        method: "PUT", body: JSON.stringify({site_id: next || null}),
      });
      await loadMonth(period);
      setNotice("Obra vinculada. La información original del Excel permanece intacta.");
    } catch(e) {setError(msg(e));}
    finally {setBusy("");}
  }
  async function importExcel() {
    if (!upload) return;
    setBusy("upload"); setError(""); setNotice("");
    const data = new FormData();
    data.append("file", upload);
    data.append("year", String(uploadYear));
    try {
      const result = await request<{sheets: number; transcribed_rows: number}>("/ine/import", {method: "POST", body: data});
      await Promise.all([loadConfig(), loadMonth(period), loadSummary(period)]);
      setNotice("Excel transcrito: " + result.sheets + " hojas y " + result.transcribed_rows +
        " filas mensuales. El original se conservó sin modificaciones.");
      setUpload(null);
    } catch(e) {setError(msg(e));}
    finally {setBusy("");}
  }
  async function inspect(sheet: {id: string; name: string}) {
    setSelectedSheet(sheet.id); setBusy("archive"); setError("");
    try {setPreview(await request<ArchiveSheet>("/ine/archive/" + sheet.id));}
    catch(e) {setError(msg(e));}
    finally {setBusy("");}
  }
  const monthOptions = config ? [config.current_month, config.previous_month] : [];
  const graph = summary?.months || [];
  const maxGraph = Math.max(1, ...graph.map(m => (m.cct || 0) + (m.cesp || 0) + (m.ind || 0)));
  return <div className={"ine " + (!admin ? "ine-supervisor" : "")}>
    <section className="ine-hero">
      <div className="ine-hero-left">
        {onBack && <button className="ine-back" type="button" onClick={onBack}><ArrowLeft size={17}/> Volver a GALANT</button>}
        <div className="ine-kicker"><FileSpreadsheet size={17}/> GALANT · CONTROL INE <span>v{version || "20.5"}</span></div>
        <h1>Registro mensual de obras</h1>
        <p>Completa las cinco cifras del Excel. Los valores vacíos permanecen pendientes, y cada cambio queda registrado.</p>
      </div>
      <div className="ine-hero-right">
        <span className="ine-role"><LockKeyhole size={16}/> {admin ? "Administrador · acceso completo" : "Supervisor INE · mis obras"}</span>
        {!admin && logout && <button type="button" className="ine-light-btn" onClick={logout}>Cerrar sesión</button>}
      </div>
    </section>

    {error && <div className="ine-alert ine-error" role="alert">{error} <button onClick={() => setError("")} aria-label="Cerrar error">×</button></div>}
    {notice && <div className="ine-alert ine-success" role="status">{notice} <button onClick={() => setNotice("")} aria-label="Cerrar aviso">×</button></div>}

    <div className="ine-control">
      <label className="ine-month"><span>Mes de trabajo</span>
        {admin ? <input aria-label="Seleccionar mes INE" type="month" value={period} onChange={e => setPeriod(e.target.value)} />
          : <select aria-label="Seleccionar mes INE" value={period} onChange={e => setPeriod(e.target.value)}>
            {monthOptions.map(m => <option value={m} key={m}>{formatMonth(m)}</option>)}
          </select>}
      </label>
      <div className="ine-subnote">{admin ? "Puedes administrar todos los meses y las obras." :
        "Puedes modificar solo el mes actual y el anterior, en tus obras asignadas."}</div>
      <button type="button" className="ine-refresh" disabled={loading || !period}
        onClick={() => void Promise.all([loadMonth(period), loadSummary(period)])}><RefreshCw size={16}/> Actualizar</button>
    </div>

    <div className="ine-kpis">
      <div className="ine-kpi"><span>Contratistas registrados</span><strong>{number(totals.contractors)}</strong><small>CCT + CESP + IND</small></div>
      <div className="ine-kpi"><span>Trabajadores registrados</span><strong>{number(totals.workers)}</strong><small>TH + TM</small></div>
      <div className="ine-kpi"><span>Obras con datos completos</span><strong>{number(totals.complete)}<em> / {rows.length}</em></strong><small>Todos los campos informados</small></div>
      <div className={"ine-kpi " + (totals.pending ? "ine-alert-kpi" : "")}><span>Obras con campos pendientes</span><strong>{number(totals.pending)}</strong><small>No se convierten vacíos en cero</small></div>
    </div>

    <div className="ine-tabs" role="tablist" aria-label="Secciones INE">
      <button role="tab" aria-selected={tab === "registro"} className={tab === "registro" ? "selected" : ""} onClick={() => setTab("registro")}>Registro mensual</button>
      <button role="tab" aria-selected={tab === "analisis"} className={tab === "analisis" ? "selected" : ""} onClick={() => setTab("analisis")}><BarChart3 size={16}/> Análisis</button>
      {admin && <button role="tab" aria-selected={tab === "historial"} className={tab === "historial" ? "selected" : ""} onClick={() => setTab("historial")}><History size={16}/> Historial privado</button>}
      {admin && <button role="tab" aria-selected={tab === "archivo"} className={tab === "archivo" ? "selected" : ""} onClick={() => setTab("archivo")}><FileSpreadsheet size={16}/> Excel y archivo</button>}
    </div>

    {tab === "registro" && <section className="ine-register">
      <div className="ine-section-head">
        <div><h2>Obras de {period ? formatMonth(period) : "INE"}</h2>
          <p>Se conservan los nombres y datos del archivo; ningún valor se corrige automáticamente.</p></div>
        <span>{visibleRows.length} obras visibles</span>
      </div>
      <div className="ine-filters">
        <label className="ine-search"><Search size={17}/><input type="search" placeholder="Buscar obra o supervisor" value={search} onChange={e => setSearch(e.target.value)} aria-label="Buscar obra" /></label>
        <select value={filter} onChange={e => setFilter(e.target.value)} aria-label="Filtrar obras">
          <option value="all">Todas las obras</option>
          <option value="pending">Con campos pendientes</option>
          <option value="complete">Completas</option>
          <option value="linked">Vinculadas a GALANT</option>
        </select>
      </div>
      {loading && <p role="status" className="ine-loading">Cargando información…</p>}
      {!loading && !visibleRows.length && <div className="ine-empty">
        <FileSpreadsheet size={32}/>
        <h3>No hay obras para este filtro</h3>
        <p>{admin ? "Importa el Excel original en «Excel y archivo» o cambia los filtros." :
          "Si te asignaron obras, aparecerán aquí. Solicita al administrador revisar tus asignaciones."}</p>
      </div>}
      <div className="ine-row-list">
        {visibleRows.map(row => <article className="ine-site" key={rowKey(row)}>
          <div className="ine-site-title">
            <div className="ine-site-names"><span className={"ine-status " + (row.complete ? "complete" : "pending")}>
              {row.complete ? <CheckCircle2 size={14}/> : <Clock3 size={14}/>}
              {row.complete ? "Completo" : "Pendiente"}
            </span>
              <h3>{row.site_name}</h3>
              {row.supervisor && <small>Supervisor del Excel: {row.supervisor}</small>}
            </div>
            {admin && row.id && <label className="ine-link"><span>Relacionar con obra GALANT</span>
              <select disabled={!!busy} value={row.site_id || ""} aria-label={"Vincular " + row.site_name}
                onChange={e => void link(row, e.target.value)}>
                <option value="">Sin vincular</option>
                {config?.sites.map(site => <option value={site.id} key={site.id}>{site.name}</option>)}
              </select>
            </label>}
            {!admin && !row.editable && <span className="ine-locked"><LockKeyhole size={14}/> Mes solo lectura</span>}
          </div>
          <div className="ine-fields">
            {cols.map(col => <label key={col.key} title={col.hint}>
              <span>{col.label}</span>
              <input aria-label={col.hint + " · " + row.site_name} inputMode="numeric"
                type="number" min={0} max={1000000} step={1} placeholder="—"
                disabled={!row.editable || !!busy} value={value(row, col.key)}
                onChange={e => setValue(row, col.key, e.target.value)}/>
              <small>{col.hint}</small>
            </label>)}
          </div>
          <div className="ine-site-footer">
            <div>{row.source_sheet ? <span>Origen: hoja {row.source_sheet}, fila {row.source_row}</span> :
              <span>Nuevo registro de GALANT</span>}
              {row.source_status && <span>Estado original: {row.source_status}</span>}</div>
            {row.editable && <button type="button" className="ine-save" disabled={!dirty(row) || !!busy}
              onClick={() => void save(row)}><Save size={16}/>{busy === rowKey(row) ? "Guardando…" : "Guardar"}</button>}
          </div>
        </article>)}
      </div>
    </section>}

    {tab === "analisis" && <section className="ine-panel">
      <div className="ine-section-head"><div><h2>Evolución mensual · {period.slice(0,4)}</h2>
        <p>Visualización calculada desde los registros. No modifica los valores ni las fórmulas del Excel original.</p></div></div>
      <div className="ine-chart-legend"><span><i className="ine-legend-cct"/> Contratistas</span><span><i className="ine-legend-th"/> Trabajadores</span></div>
      <div className="ine-chart" role="img" aria-label="Gráfico mensual de contratistas y trabajadores">
        {graph.map(m => {
          const total = (m.cct || 0) + (m.cesp || 0) + (m.ind || 0);
          const workers = (m.th || 0) + (m.tm || 0);
          const max = Math.max(maxGraph, ...graph.map(item => (item.th || 0) + (item.tm || 0)), 1);
          return <div className="ine-chart-group" key={m.period} title={formatMonth(m.period) + ": " + total + " contratistas, " + workers + " trabajadores"}>
            <div className="ine-bar-pair"><div className="ine-bar-cct" style={{height: (total / max * 100) + "%"}}/><div className="ine-bar-th" style={{height: (workers / max * 100) + "%"}}/></div>
            <span>{m.period.slice(5)}</span>
          </div>;
        })}
      </div>
      <div className="ine-table-scroll"><table className="ine-stats"><thead><tr><th>Mes</th><th>CCT</th><th>CESP</th><th>IND</th><th>TH</th><th>TM</th><th>Completas</th><th>Pendientes</th></tr></thead>
        <tbody>{graph.map(m => <tr key={m.period}><th>{formatMonth(m.period)}</th>
          {cols.map(c => <td key={c.key}>{number(m[c.key] || 0)}</td>)}
          <td>{m.complete}</td><td>{m.pending}</td></tr>)}</tbody></table></div>
      <p className="ine-footnote">Los totales de visualización no reemplazan los totales originales de las hojas de cálculo. Un período pendiente no debe interpretarse como actividad cero.</p>
    </section>}

    {tab === "historial" && admin && <section className="ine-panel">
      <div className="ine-section-head"><div><h2>Historial de modificaciones</h2><p>Solo administradores. Usuario, fecha, obra y valores antes y después.</p></div><LockKeyhole size={19}/></div>
      <div className="ine-history">{logs.length ? logs.map(log => <article key={log.id}>
        <div><b>{log.actor_name}</b><time>{new Date(log.created_at).toLocaleString("es-CL", {timeZone:"America/Santiago"})}</time></div>
        <p>{log.site_name} · {formatMonth(log.period)} · {log.action === "link" ? "Vinculación" : log.action === "create" ? "Registro nuevo" : "Modificación"}</p>
        {changedFields(log).map(field => <div className="ine-diff" key={field}><strong>{field.toUpperCase()}</strong>
          <span>{String(log.previous[field] ?? "Vacío")}</span><span>→</span><b>{String(log.current[field] ?? "Vacío")}</b>
        </div>)}
      </article>) : <p>No hay cambios registrados.</p>}</div>
    </section>}

    {tab === "archivo" && admin && <section className="ine-panel">
      <div className="ine-section-head"><div><h2>Excel original y respaldos</h2>
        <p>El Excel original se almacena byte por byte, sin alteraciones. Los cambios realizados en GALANT se respaldan aparte.</p></div></div>
      <div className="ine-archive-actions">
        <div className="ine-archive-card"><h3>Excel original</h3><p>{config?.source ? config.source.name : "Todavía no se ha importado el archivo original."}</p>
          {config?.source && <button type="button" onClick={() => void exportFile("/ine/original", "INE-original-sin-modificaciones.xlsx").catch(e => setError(msg(e)))}>
            <Download size={16}/> Descargar original intacto</button>}
        </div>
        <div className="ine-archive-card"><h3>Respaldo actual</h3><p>Copia independiente de las cifras registradas en GALANT; no reemplaza el original.</p>
          <button type="button" onClick={() => void exportFile("/ine/export?year=" + period.slice(0,4), "GALANT-INE-respaldo-" + period.slice(0,4) + ".xlsx").catch(e => setError(msg(e)))}>
            <Download size={16}/> Descargar respaldo {period.slice(0,4)}</button>
        </div>
      </div>
      {!config?.source && <div className="ine-import">
        <h3>Transcribir Excel en GALANT</h3>
        <p>Selecciona el Excel sin cambiarlo. Se copiarán sus 67 hojas y sus datos originales; las hojas mensuales se convertirán en campos editables.</p>
        <div className="ine-import-form">
          <label>Año <input type="number" min="1900" max="2199" value={uploadYear} onChange={e => setUploadYear(Number(e.target.value))}/></label>
          <label>Archivo Excel <input type="file" accept=".xlsx" onChange={e => setUpload(e.target.files?.[0] || null)} /></label>
          <button type="button" disabled={!upload || !!busy} onClick={() => void importExcel()}><UploadCloud size={16}/>{busy === "upload" ? "Transcribiendo…" : "Transcribir sin modificar"}</button>
        </div>
      </div>}
      {archive?.sheets.length ? <>
        <h3 className="ine-archive-heading">Hojas originales ({archive.sheets.length})</h3>
        <div className="ine-sheet-list">{archive.sheets.map(sheet =>
          <button type="button" className={selectedSheet === sheet.id ? "selected" : ""} key={sheet.id} onClick={() => void inspect(sheet)}>{sheet.name}</button>)}</div>
        {preview && <div className="ine-sheet-preview">
          <h4>{preview.name} · vista de solo lectura</h4>
          {busy === "archive" ? <p>Cargando hoja…</p> :
          <div className="ine-table-scroll"><table><tbody>{preview.rows.slice(0, 300).map(line =>
            <tr key={line.row}><th>{line.row}</th>{Object.entries(line.cells).map(([key, value]) =>
              <td key={key} title={key}>{String(value)}</td>)}</tr>)}</tbody></table></div>}
        </div>}
      </> : null}
    </section>}
  </div>;
}
