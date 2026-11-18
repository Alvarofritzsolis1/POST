import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Activity, CheckCircle2, CircleHelp, KeyRound, Plus, RefreshCw, ShieldCheck, Trash2, Zap } from "lucide-react";
import { request } from "./api";
import "./ai-configuration.css";

type Provider = { id: string; name: string; mode: string; docs: string };
type Task = { id: string; name: string; active: boolean };
type Connection = {
  id: string; name: string; provider: string; model: string; enabled: boolean;
  has_key: boolean; status: string; last_checked_at: string | null;
  price_input_per_million: number | null; price_output_per_million: number | null;
};
type Policy = {
  enabled: boolean; fallback_enabled: boolean; review_enabled: boolean; monthly_token_limit: number;
  task_routes: Record<string, string>;
};
type Bootstrap = {
  providers: Provider[]; tasks: Task[]; connections: Connection[];
  policy: Policy; monthly_tokens: number; server_ready: boolean;
  learning: { approved: number; pending: number; disabled: number; feedback: Record<string, number>; method: string };
};
type UsageGroup = {
  connection_id: string; provider: string; name: string; task: string;
  status: string; calls: number; input_tokens: number; output_tokens: number;
  total_tokens: number; estimated_cost_usd: number | null; priced_calls: number;
};
type Usage = {
  days: number; groups: UsageGroup[]; total_calls: number;
  total_tokens: number; input_tokens: number; output_tokens: number;
  estimated_cost_usd: number; unpriced_calls: number;
};
type Editor = {
  name: string; provider: string; model: string; api_key: string;
  enabled: boolean; price_input: string; price_output: string;
};
const base = "/admin/ai";
const MODEL_OPTIONS: Record<string, Array<{ id: string; label: string }>> = {
  gemini: [
    { id: "gemini-3.8-flash", label: "Gemini 3.8 Flash · recomendado" },
    { id: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash Lite · económico" },
  ],
  groq: [
    { id: "llama-3.1-8b-instant", label: "Llama 3.1 8B · rápido y ligero" },
    { id: "openai/gpt-oss-20b", label: "GPT-OSS 20B · razonamiento" },
    { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B · conversaciones" },
  ],
  zai: [
    { id: "glm-4.7", label: "GLM-4.7 · respuesta rápida" },
    { id: "glm-5.3-flash", label: "GLM-5.3 Flash · razonamiento" },
  ],
  zai_coding: [
    { id: "glm-4.7", label: "GLM-4.7 · Coding Plan" },
    { id: "glm-5.3-flash", label: "GLM-5.3 Flash · Coding Plan" },
  ],
  nvidia: [{ id: "deepseek-ai/deepseek-v4.1-flash", label: "DeepSeek V4.1 Flash" }],
  openai: [{ id: "gpt-4.1-mini", label: "GPT-4.1 Mini" }],
  mistral: [{ id: "mistral-small-latest", label: "Mistral Small" }],
  openrouter: [{ id: "openai/gpt-4o-mini", label: "GPT-4o Mini vía OpenRouter" }],
};
const defaultModel = (provider: string) => MODEL_OPTIONS[provider]?.[0]?.id || "";
const CAN_RECOVER = new Set(["gemini", "groq", "zai", "zai_coding"]);
const recoverableError = (message: string) =>
  /(HTTP 400|HTTP 404|respondió sin texto|sin texto utilizable)/i.test(message);
const empty: Editor = {
  name: "", provider: "gemini", model: defaultModel("gemini"), api_key: "", enabled: false,
  price_input: "", price_output: "",
};
const nice = (value: number) => value.toLocaleString("es-CL");
const dollars = (value: number) => value.toLocaleString("es-CL", { style: "currency", currency: "USD", maximumFractionDigits: 5 });
const displayDate = (value: string | null) => value ? new Date(value).toLocaleString("es-CL") : "Aún sin prueba";
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "No se pudo completar la operación";

export default function AIConfiguration() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [policy, setPolicy] = useState<Policy>({ enabled: false, fallback_enabled: false, review_enabled: false, monthly_token_limit: 0, task_routes: {} });
  const [days, setDays] = useState(30);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<Editor>(empty);
  const [manualModel, setManualModel] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const initializedPolicy = useRef(false);

  const refresh = useCallback(async (resetPolicy = false) => {
    const [b, u] = await Promise.all([
      request<Bootstrap>(base + "/bootstrap"),
      request<Usage>(base + "/usage?days=" + days),
    ]);
    setData(b);
    setUsage(u);
    if (resetPolicy) setPolicy(b.policy);
  }, [days]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      request<Bootstrap>(base + "/bootstrap"),
      request<Usage>(base + "/usage?days=" + days),
    ]).then(([b, u]) => {
      if (cancelled) return;
      setData(b);
      setUsage(u);
      if (!initializedPolicy.current) { setPolicy(b.policy); initializedPolicy.current = true; }
    }).catch((e) => { if (!cancelled) setError(errorMessage(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days]);

  const summary = useMemo(() => ({
    verified: data?.connections.filter(c => c.has_key && c.status === "verified" && c.enabled).length || 0,
    total: data?.connections.length || 0,
  }), [data]);

  async function perform(action: string, fn: () => Promise<void>) {
    setBusy(action);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      try { await refresh(); } catch (e) { setError(errorMessage(e)); }
      setBusy(null);
    }
  }

  function edit(conn?: Connection) {
    setError("");
    if (!conn) {
      setEditing("new");
      setManualModel(false);
      setForm({ ...empty });
      return;
    }
    setManualModel(!(MODEL_OPTIONS[conn.provider] || []).some(option => option.id === conn.model));
    setEditing(conn.id);
    setForm({
      name: conn.name, provider: conn.provider, model: conn.model, api_key: "",
      enabled: conn.enabled, price_input: conn.price_input_per_million?.toString() ?? "",
      price_output: conn.price_output_per_million?.toString() ?? "",
    });
  }

  async function saveConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = editing;
    if (!id || !form.model.trim()) return;
    const providedName = form.name.trim();
    const fallbackName = (providerName(form.provider) + " · " + form.model).slice(0, 72);
    let name = providedName || fallbackName;
    if (id === "new") {
      const existingNames = new Set((data?.connections || []).map(conn => conn.name.toLowerCase()));
      let count = 2;
      while (existingNames.has(name.toLowerCase())) {
        name = fallbackName.slice(0, 64) + " #" + count++;
      }
    }
    const payload = {
      name, model: form.model.trim(),
      ...(id === "new" ? { provider: form.provider, enabled: false } : {}),
      ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
      price_input_per_million: form.price_input.trim() ? Number(form.price_input) : null,
      price_output_per_million: form.price_output.trim() ? Number(form.price_output) : null,
    };
    await perform("save", async () => {
      const saved = await request<Connection>(base + (id === "new" ? "/connections" : "/connections/" + encodeURIComponent(id)), {
        method: id === "new" ? "POST" : "PATCH", body: JSON.stringify(payload),
      });
      // One visible action: save safely, perform a real API probe and enable ONLY on success.
      let outcome: { ok: boolean; message: string };
      try {
        outcome = await request<{ ok: boolean; message: string }>(
          base + "/connections/" + encodeURIComponent(saved.id) + "/test", { method: "POST" });
      } catch (err) {
        outcome = { ok: false, message: errorMessage(err) };
      }
      if (!outcome.ok && CAN_RECOVER.has(form.provider) && recoverableError(outcome.message)) {
        const recovered = await request<{ ok: boolean; message: string; model?: string }>(
          base + "/connections/" + encodeURIComponent(saved.id) + "/recover", { method: "POST" });
        outcome = recovered;
      }
      if (outcome.ok) {
        // Auto-recovery already enables its verified model; regular tests still need enabling.
        if (!("model" in outcome)) {
          await request(base + "/connections/" + encodeURIComponent(saved.id), {
            method: "PATCH", body: JSON.stringify({ enabled: true }),
          });
        }
        setNotice("Conectada y verificada. Ya puedes asignarla a Galancito en Equipo de IA.");
      } else {
        // Keep encrypted credential to allow fixing/retrying without asking for VPS access.
        setNotice("Se guardó la conexión, pero no se verificó: " + outcome.message + " Revisa la clave o el modelo y vuelve a probar.");
      }
      setEditing(null);
      setManualModel(false);
      setForm({ ...empty });
    });
  }

  async function recoverModel(id: string) {
    await perform("recover:" + id, async () => {
      const result = await request<{ ok: boolean; message: string; model?: string }>(
        base + "/connections/" + encodeURIComponent(id) + "/recover", { method: "POST" });
      if (!result.ok) throw new Error(result.message);
      setNotice(result.message);
    });
  }

  async function testConnection(conn: Connection) {
    await perform("test:" + conn.id, async () => {
      const result = await request<{ ok: boolean; message: string }>(
        base + "/connections/" + encodeURIComponent(conn.id) + "/test", { method: "POST" });
      if (!result.ok && CAN_RECOVER.has(conn.provider) && recoverableError(result.message)) {
        const recovered = await request<{ ok: boolean; message: string }>(
          base + "/connections/" + encodeURIComponent(conn.id) + "/recover", { method: "POST" });
        if (!recovered.ok) throw new Error(recovered.message);
        setNotice(recovered.message);
        return;
      }
      if (!result.ok) throw new Error(result.message);
      setNotice(result.message);
    });
  }

  async function toggleConnection(conn: Connection) {
    await perform("toggle:" + conn.id, async () => {
      await request(base + "/connections/" + encodeURIComponent(conn.id), {
        method: "PATCH", body: JSON.stringify({ enabled: !conn.enabled }),
      });
      setNotice(conn.enabled ? "IA pausada. Su historial se conserva." : "IA habilitada.");
    });
  }

  async function disconnect(conn: Connection) {
    if (!window.confirm("¿Desvincular " + conn.name + "? Su clave se eliminará y se conservarán las estadísticas históricas.")) return;
    await perform("disconnect:" + conn.id, async () => {
      await request(base + "/connections/" + encodeURIComponent(conn.id) + "/disconnect", { method: "POST" });
      setPolicy(p => {
        const routes = Object.fromEntries(Object.entries(p.task_routes).filter(([, id]) => id !== conn.id));
        return { ...p, enabled: Boolean(routes.red_obras) && p.enabled, review_enabled: Boolean(routes.review) && p.review_enabled, task_routes: routes };
      });
      setNotice("Credencial desvinculada. No se eliminaron los registros de consumo.");
    });
  }

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await perform("policy", async () => {
      await request<Policy>(base + "/policy", { method: "PUT", body: JSON.stringify(policy) });
      setNotice("Equipo de Galancito actualizado. Los cambios aplican a nuevas consultas.");
    });
  }

  const availableForRouting = (data?.connections || []).filter(c => c.enabled && c.has_key && c.status === "verified");
  const shownUsage = [...(usage?.groups || [])].sort((a, b) => b.total_tokens - a.total_tokens);
  const providerName = (id: string) => data?.providers.find(p => p.id === id)?.name || id;

  return (
    <div className="ai-center" data-testid="ai-control-center">
      <div className="ai-banner">
        <div>
          <span className="ai-eyebrow"><Zap size={15} /> CENTRO DE INTELIGENCIA ARTIFICIAL</span>
          <h2>Un equipo de IA para Red de Obras</h2>
          <p>Conecta diferentes modelos, asigna funciones a cada uno y revisa lo que realmente consumen. Tú decides cuándo se activan.</p>
        </div>
        <button type="button" onClick={() => { setError(""); void perform("refresh", () => refresh(true)); }} disabled={Boolean(busy)}>
          <RefreshCw size={16} /> Actualizar
        </button>
      </div>
      {loading && <p role="status">Cargando conexiones y consumo…</p>}
      {error && <p role="alert" className="ai-error">{error}</p>}
      {notice && <p role="status" className="ai-notice"><CheckCircle2 size={16} /> {notice}</p>}
      {data && !data.server_ready && (
        <p role="alert" className="ai-warning"><KeyRound size={17} /> La protección de claves del servidor aún no está lista. Se prepara automáticamente con la siguiente actualización de GALANT. No pegues claves hasta que desaparezca este aviso.</p>
      )}
      <div className="ai-kpis">
        <div><span>IA habilitadas y verificadas</span><strong>{summary.verified} <small>/ {summary.total}</small></strong><small>La verificación se realiza con una prueba real</small></div>
        <div><span>Tokens · mes en curso</span><strong>{nice(data?.monthly_tokens || 0)}</strong><small>Contador de solicitudes registradas en GALANT</small></div>
        <div><span>Solicitudes · últimos {days} días</span><strong>{nice(usage?.total_calls || 0)}</strong><small>Incluye pruebas de conexión y fallos</small></div>
        <div><span>Costo estimado · últimos {days} días</span><strong>{usage?.unpriced_calls && usage.unpriced_calls === usage.total_calls ? "No calculado" : dollars(usage?.estimated_cost_usd || 0)}</strong><small>{usage?.unpriced_calls ? nice(usage.unpriced_calls) + " llamadas sin tarifa configurada" : "Solo según tarifas ingresadas"}</small></div>
      </div>

      <section className="ai-panel">
        <div className="ai-panel-head">
          <div><h3>1. Conexiones API</h3><p>Registra tantas cuentas y modelos como necesites. Las claves se mantienen ocultas.</p></div>
          <button type="button" className="gc-primary" onClick={() => edit()} disabled={Boolean(busy)}>
            <Plus size={16} /> Agregar IA
          </button>
        </div>
        <div className="ai-connections">
          {data?.connections.length === 0 && <div className="ai-empty">Aún no has agregado proveedores. Comienza con Gemini, Groq, NVIDIA o Z.ai.</div>}
          {data?.connections.map(conn => {
            const state = !conn.has_key ? "Sin clave" : conn.status === "verified" ? (conn.enabled ? "Conectada" : "Verificada · pausada") : conn.status === "error" ? "Con error" : "Sin verificar";
            return <article className="ai-connection" key={conn.id}>
              <div className="ai-connection-title">
                <span className={"ai-dot " + (conn.enabled && conn.status === "verified" ? "ok" : conn.status === "error" ? "bad" : "")} />
                <div><h4>{conn.name}</h4><small>{providerName(conn.provider)} · {conn.model}</small></div>
                <span className="ai-state">{state}</span>
              </div>
              <div className="ai-connection-meta"><span><KeyRound size={14} /> {conn.has_key ? "Clave protegida" : "Clave pendiente"}</span><span><Activity size={14} /> {displayDate(conn.last_checked_at)}</span></div>
              <div className="ai-actions">
                <button type="button" disabled={Boolean(busy) || !conn.has_key} onClick={() => void testConnection(conn)}>Probar conexión</button>
                {CAN_RECOVER.has(conn.provider) && conn.has_key && conn.status !== "verified" && <button type="button" className="ai-repair-button" disabled={Boolean(busy)} onClick={() => void recoverModel(conn.id)}>{busy === "recover:" + conn.id ? "Buscando…" : "Buscar modelo compatible"}</button>}
                <button type="button" disabled={Boolean(busy)} onClick={() => edit(conn)}>Configurar</button>
                <button type="button" disabled={Boolean(busy) || !conn.has_key || (!conn.enabled && conn.status !== "verified")} onClick={() => void toggleConnection(conn)}>{conn.enabled ? "Pausar" : "Habilitar"}</button>
                <button type="button" disabled={Boolean(busy) || !conn.has_key} onClick={() => void disconnect(conn)} aria-label={"Desvincular " + conn.name}><Trash2 size={16} /></button>
              </div>
            </article>;
          })}
        </div>

        {editing && <form className="ai-editor ai-quick-form" onSubmit={(event) => void saveConnection(event)}>
          <div className="ai-editor-heading">
            <div><h4>{editing === "new" ? "Conectar una inteligencia artificial" : "Actualizar conexión"}</h4>
              <p>Solo necesitas la clave API. GALANT se encarga de la configuración técnica.</p>
            </div>
            <button type="button" onClick={() => { setEditing(null); setManualModel(false); setForm({ ...empty }); }}>Cerrar</button>
          </div>
          <div className="ai-form-grid ai-simple-fields">
            <label>1. ¿Qué IA quieres conectar?
              <select disabled={editing !== "new"} value={form.provider}
                onChange={e => { const next = e.target.value; setManualModel(false); setForm({ ...form, provider: next, model: defaultModel(next), api_key: "" }); }}>
                {data?.providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              {form.provider.startsWith("zai") && <small className="ai-provider-hint">
                {form.provider === "zai"
                  ? "API estándar: puede consumir saldo o paquetes de Z.ai."
                  : "Coding Plan: utiliza una clave de ese plan y su cuota, si está activa."}
                No cambiaremos de modalidad automáticamente.
              </small>}
            </label>
            <label>2. Selecciona el modelo
              <select value={manualModel ? "__manual__" : form.model}
                onChange={e => { setManualModel(e.target.value === "__manual__"); setForm({ ...form, model: e.target.value === "__manual__" ? "" : e.target.value }); }}>
                {(MODEL_OPTIONS[form.provider] || []).map(option =>
                  <option key={option.id} value={option.id}>{option.label}</option>)}
                <option value="__manual__">Otro modelo (configuración avanzada)</option>
              </select>
            </label>
            {manualModel && <label className="ai-manual-model">ID exacto del modelo
              <input required value={form.model} onChange={e => setForm({ ...form, model: e.target.value })}
                placeholder="Pega el identificador del proveedor" />
            </label>}
            <label className="ai-key-input">3. Pega tu API Key {editing !== "new" && <small>Dejar vacío conserva la clave guardada</small>}
              <input type="password" autoComplete="new-password" required={editing === "new"}
                value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })}
                placeholder="Pega aquí tu clave privada. Nadie podrá verla después." />
            </label>
          </div>
          <p className="ai-help"><KeyRound size={15} /> ¿No tienes una clave? <a href={data?.providers.find(p => p.id === form.provider)?.docs}
            target="_blank" rel="noopener noreferrer">Abrir el portal oficial de {providerName(form.provider)}</a>.
            No compartas la clave por WhatsApp ni por este chat.</p>
          <details className="ai-advanced">
            <summary>Opciones avanzadas (opcionales)</summary>
            <div className="ai-form-grid">
              <label>Nombre para identificarla<input maxLength={80} value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="Se asigna automáticamente si lo dejas vacío" /></label>
              <label>USD / millón de tokens de entrada<input type="number" min={0} step="any"
                value={form.price_input} onChange={e => setForm({ ...form, price_input: e.target.value })}
                placeholder="Sin tarifa configurada" /></label>
              <label>USD / millón de tokens de salida<input type="number" min={0} step="any"
                value={form.price_output} onChange={e => setForm({ ...form, price_output: e.target.value })}
                placeholder="Sin tarifa configurada" /></label>
            </div>
            <p className="ai-help">Las tarifas son opcionales. No escribirlas no significa que el proveedor sea gratis.</p>
          </details>
          <div className="ai-editor-footer">
            <span className="ai-help"><ShieldCheck size={15} /> Clave cifrada en GALANT. Una prueba real puede consumir cuota.</span>
            <button className="gc-primary" type="submit" disabled={Boolean(busy) || !data?.server_ready || !form.model.trim() || (editing === "new" && !form.api_key.trim())}>
              <CheckCircle2 size={16} /> {busy === "save" ? "Conectando…" : "Conectar y probar"}
            </button>
          </div>
        </form>}
      </section>

      <section className="ai-panel">
        <div className="ai-panel-head"><div><h3>2. Equipo de Galancito</h3><p>Una IA principal por función. La alternativa se usa solo ante un error y si la autorizas.</p></div><span className="ai-secure"><ShieldCheck size={16} /> Solo administrador</span></div>
        <form onSubmit={(event) => void savePolicy(event)}>
          <div className="ai-task-grid">
            {data?.tasks.map(task => <label key={task.id} className="ai-task">
              <span>{task.name}{!task.active && " · integración pendiente"}</span>
              <select disabled={!task.active} value={policy.task_routes[task.id] || ""} onChange={e => setPolicy(p => {
                const next = { ...p.task_routes };
                if (e.target.value) next[task.id] = e.target.value; else delete next[task.id];
                return { ...p, task_routes: next };
              })}>
                <option value="">Sin asignar (función desactivada)</option>
                {availableForRouting.map(conn => <option key={conn.id} value={conn.id}>{conn.name} · {providerName(conn.provider)}</option>)}
              </select>
            </label>)}
          </div>
          <div className="ai-policy-controls">
            <label className="ai-check"><input type="checkbox" checked={policy.enabled} onChange={e => setPolicy({ ...policy, enabled: e.target.checked })} /> Activar equipo IA de Red de Obras</label>
            <label className="ai-check"><input type="checkbox" checked={policy.fallback_enabled} onChange={e => setPolicy({ ...policy, fallback_enabled: e.target.checked })} /> Usar otra IA habilitada si la principal falla</label>
            <label className="ai-check"><input type="checkbox" checked={policy.review_enabled} onChange={e => setPolicy({ ...policy, review_enabled: e.target.checked })} /> Verificación por una segunda IA (opcional: consume tokens)</label>
            <label>Tope de tokens mensuales <small>(0 = sin tope propio)</small><input type="number" min={0} max={1000000000} value={policy.monthly_token_limit} onChange={e => setPolicy({ ...policy, monthly_token_limit: Math.max(0, Number(e.target.value || 0)) })} /></label>
          </div>
          <p className="ai-help"><CircleHelp size={15} /> En esta versión se ejecutan las consultas de Red de Obras y, si lo habilitas, una segunda IA valida la respuesta antes de mostrarla. La revisión requiere otro modelo, más tiempo y consumo adicional. Las demás funciones siguen siendo planificación. El aprendizaje compartido utiliza guías aprobadas en GALANT. Las IA no se entrenan unas a otras ni reciben conversaciones privadas automáticamente. Los mensajes externos requieren autorización del usuario y pasan por los controles de privacidad actuales.</p>
          <button type="submit" className="gc-primary" disabled={Boolean(busy)}>Guardar funciones y límites</button>
        </form>
      </section>

      <section className="ai-panel">
        <div className="ai-panel-head"><div><h3>3. Aprendizaje compartido</h3><p>Las IA consultan información validada. No se reentrenan ni comparten sus respuestas automáticamente.</p></div><span className="ai-secure"><ShieldCheck size={16} /> Con aprobación humana</span></div>
        <div className="ai-learning-stats">
          <div><b>{nice(data?.learning.approved || 0)}</b><span>Guías aprobadas</span></div>
          <div><b>{nice(data?.learning.pending || 0)}</b><span>Propuestas por revisar</span></div>
          <div><b>{nice(data?.learning.feedback.incorrect || 0)}</b><span>Respuestas reportadas como incorrectas</span></div>
        </div>
        <p className="ai-help"><CircleHelp size={15} /> Una corrección crea una propuesta pendiente. Solo un administrador puede aprobarla antes de que otras IA la utilicen. La segunda IA verifica respuestas, pero no modifica la base de conocimiento.</p>
      </section>

      <section className="ai-panel">
        <div className="ai-panel-head"><div><h3>4. Consumo de tokens</h3><p>Uso registrado por esta aplicación; no equivale al saldo completo de cada proveedor.</p></div><label className="ai-days">Período<select value={days} onChange={e => setDays(Number(e.target.value))}><option value={7}>7 días</option><option value={30}>30 días</option><option value={90}>90 días</option><option value={365}>1 año</option></select></label></div>
        <div className="ai-usage-head"><span>Entrada: <b>{nice(usage?.input_tokens || 0)}</b></span><span>Salida: <b>{nice(usage?.output_tokens || 0)}</b></span><span>Total: <b>{nice(usage?.total_tokens || 0)}</b></span></div>
        <div className="ai-table-scroll"><table className="ai-table"><thead><tr><th>IA</th><th>Función</th><th>Estado</th><th>Llamadas</th><th>Tokens</th><th>Estimación USD</th></tr></thead><tbody>
          {shownUsage.map((item, i) => <tr key={item.connection_id + item.task + item.status + i}>
            <td>{item.name}<small>{providerName(item.provider)}</small></td>
            <td>{data?.tasks.find(t => t.id === item.task)?.name || (item.task === "connection_test" ? "Prueba API" : item.task)}</td>
            <td>{item.status === "success" ? "Correcto" : "Error"}</td>
            <td>{nice(item.calls)}</td><td>{nice(item.total_tokens)}</td>
            <td>{item.priced_calls === item.calls ? dollars(item.estimated_cost_usd || 0) : "Sin tarifa / parcial"}</td>
          </tr>)}
          {shownUsage.length === 0 && <tr><td colSpan={6} className="ai-empty">Todavía no hay solicitudes registradas en este período.</td></tr>}
        </tbody></table></div>
        <p className="ai-help">El costo es una estimación basada en precios que configures tú; no incluye impuestos, otros sistemas que utilicen tus claves ni ajustes de facturación. Los tokens solo se cuentan cuando el proveedor los informa.</p>
      </section>
    </div>
  );
}
