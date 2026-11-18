import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
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
const empty: Editor = {
  name: "", provider: "gemini", model: "", api_key: "", enabled: false,
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
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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
      setPolicy(b.policy);
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
      setForm({ ...empty });
      return;
    }
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
    if (!id) return;
    const payload = {
      name: form.name.trim(), model: form.model.trim(),
      enabled: form.enabled, ...(id === "new" ? { provider: form.provider } : {}),
      ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
      price_input_per_million: form.price_input.trim() ? Number(form.price_input) : null,
      price_output_per_million: form.price_output.trim() ? Number(form.price_output) : null,
    };
    await perform("save", async () => {
      await request(base + (id === "new" ? "/connections" : "/connections/" + encodeURIComponent(id)), {
        method: id === "new" ? "POST" : "PATCH", body: JSON.stringify(payload),
      });
      setEditing(null);
      setForm({ ...empty });
      setNotice("Configuración guardada. Prueba la conexión antes de asignarla a Galancito.");
    });
  }

  async function testConnection(id: string) {
    await perform("test:" + id, async () => {
      const result = await request<{ ok: boolean; message: string }>(
        base + "/connections/" + encodeURIComponent(id) + "/test", { method: "POST" });
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
        <p role="alert" className="ai-warning"><KeyRound size={17} /> Para almacenar API Keys falta definir AI_CREDENTIAL_ENCRYPTION_KEY en el entorno privado del servidor. No introduzcas claves hasta completar este paso.</p>
      )}
      <div className="ai-kpis">
        <div><span>IA habilitadas y verificadas</span><strong>{summary.verified} <small>/ {summary.total}</small></strong><small>La verificación se realiza con una prueba real</small></div>
        <div><span>Tokens · mes en curso</span><strong>{nice(data?.monthly_tokens || 0)}</strong><small>Contador de solicitudes registradas en GALANT</small></div>
        <div><span>Solicitudes · últimos {days} días</span><strong>{nice(usage?.total_calls || 0)}</strong><small>Incluye pruebas de conexión y fallos</small></div>
        <div><span>Costo estimado · últimos {days} días</span><strong>{dollars(usage?.estimated_cost_usd || 0)}</strong><small>{usage?.unpriced_calls ? nice(usage.unpriced_calls) + " llamadas sin tarifa configurada" : "Solo según tarifas ingresadas"}</small></div>
      </div>

      <section className="ai-panel">
        <div className="ai-panel-head">
          <div><h3>1. Conexiones API</h3><p>Registra tantas cuentas y modelos como necesites. Las claves se mantienen ocultas.</p></div>
          <button type="button" className="gc-primary" onClick={() => edit()} disabled={Boolean(busy)}>
            <Plus size={16} /> Agregar IA
          </button>
        </div>
        <div className="ai-connections">
          {data?.connections.length === 0 && <div className="ai-empty">Aún no has agregado proveedores. Comienza con Gemini, Groq o NVIDIA.</div>}
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
                <button type="button" disabled={Boolean(busy) || !conn.has_key} onClick={() => void testConnection(conn.id)}>Probar conexión</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => edit(conn)}>Configurar</button>
                <button type="button" disabled={Boolean(busy) || !conn.has_key} onClick={() => void toggleConnection(conn)}>{conn.enabled ? "Pausar" : "Habilitar"}</button>
                <button type="button" disabled={Boolean(busy) || !conn.has_key} onClick={() => void disconnect(conn)} aria-label={"Desvincular " + conn.name}><Trash2 size={16} /></button>
              </div>
            </article>;
          })}
        </div>

        {editing && <form className="ai-editor" onSubmit={(event) => void saveConnection(event)}>
          <div className="ai-editor-heading"><h4>{editing === "new" ? "Nueva conexión" : "Editar conexión"}</h4><button type="button" onClick={() => { setEditing(null); setForm({ ...empty }); }}>Cerrar</button></div>
          <div className="ai-form-grid">
            <label>Nombre para identificarla<input required maxLength={80} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Ej. NVIDIA · DeepSeek" /></label>
            <label>Proveedor<select disabled={editing !== "new"} value={form.provider} onChange={e => setForm({ ...form, provider: e.target.value })}>{data?.providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <label>Modelo (ID exacto)<input required value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} placeholder={form.provider === "nvidia" ? "deepseek-ai/deepseek-v4.1-flash" : form.provider === "groq" ? "modelo-de-groq" : "modelo-de-gemini"} /></label>
            <label>API Key {editing !== "new" && <small>Dejar vacío mantiene la actual</small>}<input type="password" autoComplete="off" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder="Se guarda cifrada en el servidor" /></label>
            <label>USD / 1M tokens de entrada (opcional)<input type="number" min={0} step="any" value={form.price_input} onChange={e => setForm({ ...form, price_input: e.target.value })} placeholder="Tarifa contratada" /></label>
            <label>USD / 1M tokens de salida (opcional)<input type="number" min={0} step="any" value={form.price_output} onChange={e => setForm({ ...form, price_output: e.target.value })} placeholder="Tarifa contratada" /></label>
          </div>
          <div className="ai-editor-footer">
            <label className="ai-check"><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> Habilitar para usar en Galancito</label>
            <button className="gc-primary" disabled={Boolean(busy) || !data?.server_ready}>Guardar conexión</button>
          </div>
          <p className="ai-help"><ShieldCheck size={15} /> La clave nunca se devuelve al navegador. No se publica en GitHub. Guardar no implica que el modelo esté disponible; usa «Probar conexión».</p>
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
        <div className="ai-panel-head"><div><h3>3. Consumo de tokens</h3><p>Uso registrado por esta aplicación; no equivale al saldo completo de cada proveedor.</p></div><label className="ai-days">Período<select value={days} onChange={e => setDays(Number(e.target.value))}><option value={7}>7 días</option><option value={30}>30 días</option><option value={90}>90 días</option><option value={365}>1 año</option></select></label></div>
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
