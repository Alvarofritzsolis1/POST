import { useCallback, useEffect, useState, type FormEvent } from "react";
import { change, net } from "./networkApi";
import { request } from "./api";
import { errorText } from "./NetworkUI";
import "./galancito-knowledge.css";

type Knowledge = {
  id: string; title: string; category: string; kind: string; scope: string;
  content: string; phrases: string[]; status: string; version: number;
  updated_at: string; updated_by: string; approved_by: string | null;
};
type Performance = {
  queries: number; average_ms: number | null; p50_ms: number | null; p95_ms: number | null;
  incorrect: number; model: string; keep_alive: string; num_predict: number;
  sources: Record<string, number>; stages_ms: Record<string, number>;
  health: {state: string; loaded?: boolean; model_ram_bytes: number | null};
};
type Revision = {version: number; responsible_id: string; created_at: string;
  snapshot: {title: string; content: string; status: string}};
const empty = () => ({title: "", category: "General", kind: "faq", scope: "red_obras", content: "", phrases: ""});
const formFor = (row: Knowledge) => ({title: row.title, category: row.category, kind: row.kind,
  scope: row.scope, content: row.content, phrases: row.phrases.join("\n")});
const states: Record<string, string> = {pending: "Pendiente de aprobación", approved: "Aprobado", disabled: "Desactivado"};
const kinds: Record<string, string> = {faq: "Pregunta y respuesta", procedure: "Procedimiento", trade: "Oficio y sinónimos",
  example: "Conversación de ejemplo", correction: "Corrección", avoid: "Respuesta que evitar", handoff: "Atención humana"};
const times = (v: number | null | undefined) => v == null ? "Sin muestras" : `${(v / 1000).toFixed(2)} s`;

export default function GalancitoKnowledgeCenter({mode = "knowledge"}: {mode?: "knowledge" | "performance" | "summary"}) {
  const [rows, setRows] = useState<Knowledge[]>([]);
  const [performance, setPerformance] = useState<Performance | null>(null);
  const [edit, setEdit] = useState<Knowledge | null>(null);
  const [form, setForm] = useState(empty);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const refresh = useCallback(async () => {
    const [stats, knowledge] = await Promise.all([
      mode === "knowledge" ? Promise.resolve(null) : net<Performance>("/galancito/performance"),
      mode === "performance" ? Promise.resolve([]) : net<Knowledge[]>("/galancito/knowledge"),
    ]);
    setPerformance(stats); setRows(knowledge);
  }, [mode]);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [stats, knowledge] = await Promise.all([mode === "knowledge" ? Promise.resolve(null) : net<Performance>("/galancito/performance"),
          mode === "performance" ? Promise.resolve([]) : net<Knowledge[]>("/galancito/knowledge")]);
        if (active) { setPerformance(stats); setRows(knowledge); }
      } catch (e) { if (active) setError(errorText(e)); }
    };
    void load();
    return () => { active = false; };
  }, [mode]);
  async function act(action: () => Promise<void>, message: string) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); await refresh(); setNotice(message); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  function select(row: Knowledge | null) {
    setEdit(row); setRevisions([]);
    setForm(row ? formFor(row) : empty());
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    await act(async () => {
      const payload = {...form, phrases: form.phrases.split("\n").map(x => x.trim()).filter(Boolean)};
      const saved = await change<Knowledge>("/galancito/knowledge" + (edit ? "/" + edit.id : ""),
        edit ? {...payload, version: edit.version} : payload, edit ? "PUT" : "POST");
      select(saved);
    }, "Guardado como pendiente. Revisa y aprueba el contenido para que Galancito pueda usarlo.");
  }
  const visible = rows.filter(row => (!filter || row.status === filter) &&
    [row.title, row.category, ...row.phrases].join(" ").toLocaleLowerCase("es").includes(query.toLocaleLowerCase("es")));
  const health = performance?.health;
  return <section className="gkc" aria-label="Centro de conocimientos de Galancito">
    <header className="gkc-heading"><div>
      <h3>{mode === "knowledge" ? "Centro de conocimientos" : mode === "summary" ? "Resumen de Galancito" : "Rendimiento de Galancito"}</h3>
      <p>{mode === "knowledge" ? "Enséñale con guías y ejemplos. Cada cambio necesita aprobación antes de usarse." :
        "Consultas de las últimas 24 horas, hasta 500 muestras. Actualiza para consultar el estado actual."}</p>
    </div><button className="nw-btn" type="button" disabled={busy} onClick={() => void act(async () => {}, "Datos actualizados.")}>Actualizar</button></header>
    {error && <p role="alert" className="fbc-error">{error}</p>}
    {notice && <p role="status" className="fbc-notice">{notice}</p>}
    {mode !== "knowledge" && <>
      <div className="gkc-metrics">
        <article><small>Estado de Ollama</small><b>{health?.state === "available" ? "Disponible" : health?.state === "disabled" ? "Desactivado" : "Modelo no disponible"}</b></article>
        <article><small>Consultas medidas</small><b>{performance?.queries ?? 0}</b></article>
        <article><small>Tiempo promedio</small><b>{times(performance?.average_ms)}</b></article>
        <article><small>Respuestas por revisar</small><b>{performance?.incorrect ?? 0}</b></article>
      </div>
      {mode === "summary" && <p>Conocimientos aprobados: {rows.filter(r => r.status === "approved").length} · Pendientes: {rows.filter(r => r.status === "pending").length}.</p>}
      {mode === "performance" && <div className="gkc-performance">
        <p>Modelo: {performance?.model} · Permanencia: {performance?.keep_alive} · Límite de respuesta: {performance?.num_predict} tokens.</p>
        <p>Mediana: {times(performance?.p50_ms)} · Percentil 95: {times(performance?.p95_ms)}.</p>
        <p>Memoria de modelos informada por Ollama: {health?.model_ram_bytes == null ? "Sin medición" : `${(health.model_ram_bytes / 1024 ** 3).toFixed(2)} GiB`}.
          El límite del contenedor es 3 GiB y 1,5 CPU; el uso real de CPU se mide con el benchmark en el servidor.</p>
        <table><caption>Promedios por etapa con muestras disponibles</caption><thead><tr><th>Etapa</th><th>Tiempo</th></tr></thead><tbody>
          {Object.entries(performance?.stages_ms ?? {}).map(([stage, value]) => <tr key={stage}><td>{({db_ms: "Base de datos", load_ms: "Carga del modelo", prompt_ms: "Lectura del contexto", generation_ms: "Generación", transport_ms: "Transporte y otros tiempos", queue_ms: "Espera local"} as Record<string, string>)[stage] || stage}</td><td>{times(value)}</td></tr>)}
        </tbody></table>
        <p>{Object.entries(performance?.sources ?? {}).map(([s, count]) => `${s}: ${count}`).join(" · ") || "Aún no hay consultas medidas."}</p>
      </div>}
    </>}
    {mode === "knowledge" && <>
      <div className="gkc-tools">
        <button className="nw-btn" type="button" onClick={() => select(null)}>Nuevo conocimiento</button>
        <button className="nw-btn" type="button" disabled={busy} onClick={() => void act(async () => {
          await change("/galancito/knowledge-examples");
        }, "Ejemplos cargados como pendientes. Revisa su contenido y aprueba los que correspondan.")}>Cargar 12 ejemplos iniciales</button>
        <label className="gkc-upload">Importar documento<input type="file" accept=".pdf,.docx,.txt" disabled={busy}
          onChange={e => {
            const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
            if (file.size > 2 * 1024 ** 2) { setError("Máximo 2 MiB por documento."); return; }
            void act(async () => {const data = new FormData(); data.append("file", file);
              const saved = await request<Knowledge>("/network/galancito/knowledge-import", {method: "POST", body: data});
              select(saved);
            }, "Texto importado como pendiente y visible solo en Red de Obras. Revisa el contenido antes de aprobar.");
          }}/></label>
      </div>
      <p className="gkc-note">PDF con texto, Word .docx o TXT, hasta 2 MiB y 24.000 caracteres. No incluyas datos personales. Los ejemplos no son ofertas de empleo vigentes.</p>
      <div className="gkc-layout"><aside aria-label="Lista de conocimientos">
        <label>Buscar<input value={query} onChange={e => setQuery(e.target.value)} placeholder="Título, categoría o frase"/></label>
        <label>Estado<select value={filter} onChange={e => setFilter(e.target.value)}><option value="">Todos</option>
          {Object.entries(states).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        {!visible.length && <p>No hay conocimientos para este filtro.</p>}
        {visible.map(row => <button type="button" key={row.id} className={"gkc-item " + (edit?.id === row.id ? "selected" : "")} onClick={() => select(row)}>
          <strong>{row.title}</strong><small>{row.category} · v{row.version}</small><small>{states[row.status]}</small>
        </button>)}
        <small>Se muestran hasta 100 conocimientos recientes.</small>
      </aside><form onSubmit={e => void save(e)}>
        <h4>{edit ? "Editar conocimiento" : "Nuevo conocimiento"}</h4>
        <label>Título<input required minLength={2} maxLength={180} value={form.title} onChange={e => setForm({...form, title: e.target.value})}/></label>
        <div className="gkc-fields"><label>Categoría<input required maxLength={80} value={form.category} onChange={e => setForm({...form, category: e.target.value})}/></label>
          <label>Tipo<select value={form.kind} onChange={e => setForm({...form, kind: e.target.value})}>
            {Object.entries(kinds).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
        <label>Contenido<textarea required minLength={2} maxLength={24000} rows={8} value={form.content} onChange={e => setForm({...form, content: e.target.value})}/></label>
        <label>Preguntas o sinónimos relacionados (uno por línea)<textarea rows={3} value={form.phrases} onChange={e => setForm({...form, phrases: e.target.value})}/></label>
        <label>Dónde puede usarlo<select value={form.scope} onChange={e => setForm({...form, scope: e.target.value})}>
          <option value="red_obras">Solo asesor interno de Red de Obras</option><option value="messenger">Solo Messenger</option><option value="both">Red de Obras y Messenger</option>
        </select></label>
        <button type="submit" className="nw-btn nw-primary" disabled={busy}>Guardar como pendiente</button>
        {edit && <div className="gkc-review"><p>{states[edit.status]} · v{edit.version} · {new Date(edit.updated_at).toLocaleString("es-CL")}</p>
          <small>Responsable: {edit.updated_by}{edit.approved_by ? ` · Aprobó: ${edit.approved_by}` : ""}</small>
          <p>La aprobación corresponde a la versión guardada. Guarda tus cambios antes de aprobar.</p>
          <button type="button" className="nw-btn" disabled={busy || edit.status === "approved" || JSON.stringify(form) !== JSON.stringify(formFor(edit))}
            onClick={() => void act(async () => { select(await change<Knowledge>(`/galancito/knowledge/${edit.id}/state`, {version: edit.version, state: "approved"})); }, "Conocimiento aprobado.")}>Aprobar versión guardada</button>
          <button type="button" className="nw-btn" disabled={busy || edit.status === "disabled"} onClick={() => void act(async () => {
            select(await change<Knowledge>(`/galancito/knowledge/${edit.id}/state`, {version: edit.version, state: "disabled"}));
          }, "Conocimiento desactivado.")}>Desactivar</button>
          <button type="button" className="nw-btn" disabled={busy} onClick={() => void act(async () => {
            setRevisions(await net<Revision[]>(`/galancito/knowledge/${edit.id}/versions`));
          }, "Historial cargado.")}>Ver historial</button>
          {revisions.map(r => <details key={r.version}><summary>Versión {r.version} · {states[r.snapshot.status]} · {new Date(r.created_at).toLocaleString("es-CL")}</summary>
            <small>Responsable: {r.responsible_id}</small><pre>{r.snapshot.content}</pre></details>)}
        </div>}
      </form></div>
    </>}
  </section>;
}
