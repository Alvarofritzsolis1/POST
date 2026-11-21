import { useEffect, useState } from "react";
import {
  Activity, ArrowLeft, Beaker, ChevronRight, Download, History, Moon, Pause,
  Play, RotateCcw, Square, TriangleAlert,
} from "lucide-react";
import { request } from "./api";
import "./galancito-training.css";

const endpoint = "/admin/ai/training";
const labels: Record<string, string> = {
  queued: "En espera", practicing: "Practicando", evaluating: "Evaluando", correcting: "Corrigiendo",
  paused: "Pausado", completed: "Completado", stopped: "Detenido", error: "Error",
};
const internalDimensions: Record<string, string> = {
  accuracy: "Exactitud factual", tools: "Evidencia y herramientas", context: "Contexto",
  usefulness: "Utilidad", security: "Seguridad", limits: "Reconoce límites",
};
const profiles: Record<string, string> = { postulantes: "Postulantes", interno: "Interno 360°" };
const dimensions: Record<string, string> = {
  understanding: "Comprensión del mensaje", context: "Coherencia contextual",
  profile: "Extracción de ficha", naturalness: "Naturalidad estimada",
  trades: "Identificación de oficios", repetition: "Ausencia de repeticiones", efficiency: "Eficiencia",
};
const errorNames: Record<string, string> = {
  extraccion: "Extracción", repeticion: "Repetición", respuesta: "Respuesta",
  contexto: "Contexto", critico: "Crítico", compatibilidad: "Compatibilidad",
  menu_numerado: "Opciones numeradas",
  exactitud: "Exactitud", herramienta: "Herramientas", utilidad: "Utilidad", seguridad: "Seguridad", limites: "Límites",
};
const fieldNames: Record<string, string> = {
  name: "Nombre", trades: "Especialidades", experience: "Experiencia", work_communes: "Comunas",
  availability: "Disponibilidad", interest_type: "Interés", entity_type: "Tipo de postulante",
  workers: "Personas", team_available: "Cuadrilla", has_employees: "Empleados", phone: "Teléfono",
  documents_state: "Documentos", contact_status: "Estado del contacto", match: "Compatibilidad",
};
const levels = ["Básico", "Intermedio", "Avanzado", "Experto", "Casos difíciles"];
const suites: Record<string, string> = { reference: "Referencia", practice: "Práctica", holdout: "Prueba reservada" };
const running = ["queued", "practicing", "evaluating", "correcting", "paused"];
const format = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat("es-CL", {
  dateStyle: "short", timeStyle: "short", timeZone: "America/Santiago",
});
const price = new Intl.NumberFormat("es-CL", { style: "currency", currency: "USD", maximumFractionDigits: 6 });
const number = (value?: number | null) => value == null ? "—" : format.format(value);
const percent = (value?: number | null) => value == null ? "—" : number(100 * value) + "%";
const timestamp = (value?: string | null) => value ? dateFormat.format(new Date(value)) : "—";
const displayField = (value: unknown) => Array.isArray(value) ? (value.join(", ") || "Sin datos") :
  typeof value === "boolean" ? (value ? "Sí" : "No") : (value == null || value === "" ? "Sin datos" : String(value));
const errorText = (error: unknown) => error instanceof Error ? error.message : "No se pudo completar la operación";

type Model = { id: string; provider: string; model: string };
type Metrics = {
  passed: number; failed: number; turns: number; critical: number; score: number | null;
  fields: number; correct_fields: number; profile_accuracy: number | null;
  dimensions: Record<string, number | null>; average_latency_ms: number | null;
  input_tokens: number; output_tokens: number; reserved_tokens: number;
  estimated_cost_usd: number; reserved_cost_usd: number; repetition_rate: number | null; judged_turns: number;
  reply_sources: Record<string, number> | null; questions: number; repeated_questions: number;
};
type Round = {
  id: string; state: string; target: number; completed: number; reason: string | null; next_at: string;
  created_at: string; previous_id: string | null; dataset_hash: string; leased: boolean;
  config: { profile?: "postulantes" | "interno"; level: number; suite: string; model: Model; judge: Model; night: boolean; evaluation_version?: number; profile_review?: boolean };
  metrics: Metrics;
};
type Overview = {
  active_id: string | null; rounds: Round[]; detail_days: number;
  local_model: string; training_mode: string; internal_categories?: string[];
  worker: { available: boolean; seen: string | null; resources: {
    host_ram_mb: number | null; available_ram_mb: number | null; worker_ram_mb: number | null;
    worker_ram_limit_mb: number | null; host_cpu_percent: number | null; disk_free_mb: number;
    host_cores: number | null; worker_cores: number | null;
    gpu: { name: string; vram_mb: number }[] | null;
  } | null };
  knowledge: { version: number; revisions: number[]; corrections: { phrase: string; reply: string; instruction: string }[] };
  providers: { id: string; label: string; model: string }[];
};
type Case = {
  id: string; critical: number; errors: Record<string, number>; ai_proposal?: string | null;
  turns?: { turn: number; message: string; reply: string; issues?: string[]; expected: Record<string, unknown>; differences: Record<string, unknown> }[];
};
type Failures = { cases: Case[]; more: boolean; proposals: Record<string, string> };
const defaults = {
  profile: "postulantes" as "postulantes" | "interno", level: 1, cases: 100, suite: "reference", seed: "",
  model: "ollama", judge: "rules", corrector: "rules", profile_review: false, night_start: 23, night_end: 7, minutes: 480,
  concurrency: 0, ram_limit_mb: 0, cpu_limit_percent: 75, token_budget: 6000000, cost_budget: 0,
};
const fields = [
  ["minutes", "Duración activa (min)", 1, 1440, 1],
  ["concurrency", "Concurrencia (0 = automática)", 0, 4, 1],
  ["ram_limit_mb", "RAM del trabajador (MB, 0 = servidor)", 0, 384, 1],
  ["cpu_limit_percent", "Umbral de CPU (%)", 10, 90, 1],
  ["token_budget", "Presupuesto de tokens", 1, 50000000, 1],
  ["cost_budget", "Presupuesto de API (USD)", 0, 100, 0.01],
  ["night_start", "Hora nocturna inicial en Chile", 0, 23, 1],
  ["night_end", "Hora nocturna final en Chile", 0, 23, 1],
] as const;

export default function GalancitoTraining({ back }: { back: () => void }) {
  const [data, setData] = useState<Overview | null>(null);
  const [form, setForm] = useState(defaults);
  const [selection, setSelection] = useState<string | null>(null);
  const [failureRound, setFailureRound] = useState("");
  const [failures, setFailures] = useState<Failures | null>(null);
  const [offset, setOffset] = useState(0);
  const [corrections, setCorrections] = useState("");
  const [restoreVersion, setRestoreVersion] = useState(0);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let timer: number;
    let mounted = true;
    async function poll() {
      try {
        const result = await request<Overview>(endpoint);
        if (mounted) { setData(result); setLoadError(""); }
      } catch (err) {
        if (mounted) setLoadError(errorText(err));
      } finally {
        if (mounted) timer = window.setTimeout(poll, 4000);
      }
    }
    void poll();
    return () => { mounted = false; window.clearTimeout(timer); };
  }, []);

  const active = data?.rounds.find(round => round.id === data.active_id);
  const history = (data?.rounds ?? []).filter(item => (item.config.profile ?? "postulantes") === form.profile);
  const round = history.find(item => item.id === selection) ??
    (active && (active.config.profile ?? "postulantes") === form.profile ? active : undefined) ?? history[0];
  const comparison = data?.rounds.find(item => item.id === round?.previous_id);
  const stats = round?.metrics;
  const sameEvaluation = round?.config.evaluation_version === comparison?.config.evaluation_version &&
    round?.config.judge.id === comparison?.config.judge.id &&
    round?.config.judge.model === comparison?.config.judge.model &&
    (stats?.dimensions.naturalness == null) === (comparison?.metrics.dimensions.naturalness == null);
  const resources = data?.worker.resources;

  async function perform(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
      setData(await request<Overview>(endpoint));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function json<T>(path: string, body: unknown) {
    return request<T>(endpoint + path, { method: "POST", body: JSON.stringify(body) });
  }

  function start(night: boolean) {
    const formElement = document.getElementById("galancito-training-form") as HTMLFormElement | null;
    if (!formElement?.reportValidity()) return;
    void perform(async () => {
      const row = await json<Round>("/rounds", { ...form, night, seed: form.seed === "" ? null : Number(form.seed) });
      setSelection(row.id);
      setNotice(night ? "Ronda nocturna programada para " + timestamp(row.next_at) : "Ronda guardada. El servidor la iniciará automáticamente.");
    });
  }

  function repeatRound(id: string, profileReview?: boolean) {
    void perform(async () => {
      const body = profileReview === undefined ? null : { profile_review: profileReview };
      const queued = await json<Round>("/rounds/" + id + "/repeat", body);
      setSelection(queued.id);
      setNotice(profileReview ? "Comparación con verificación en cola." : "Reevaluación en cola.");
    });
  }

  async function viewErrors(id: string, next = 0) {
    const result = await request<Failures>(endpoint + "/rounds/" + id + "/errors?offset=" + next);
    setFailureRound(id);
    setFailures(result);
    setOffset(next);
  }

  const exportUrl = (slug: string) => "/api/v1" + endpoint + slug;
  const modelOptions = (data?.providers ?? []).map(item =>
    <option value={item.id} key={item.id}>{item.label} · {item.model}</option>
  );

  return <div className="ai-center training" data-testid="galancito-training">
    <button className="training-back" onClick={back}><ArrowLeft size={16} /> Inteligencia artificial</button>
    <div className="ai-banner training-banner">
      <div>
        <span className="ai-eyebrow"><Beaker size={15} /> GALANT AI TRAINING LAB</span>
        <h1>Práctica Bot · Galancito</h1>
        <p>{form.profile === "interno" ? "Practica consultas internas con resultados de herramientas simulados, sin acceder a datos de producción." :
          "Simula conversaciones de construcción chilena y evalúa las fichas, las respuestas y el contexto."}</p>
      </div>
      <span className={"training-status " + (active?.state ?? (data?.worker.available ? "available" : ""))}>
        <span aria-hidden="true" />
        {!data ? "Cargando" : !data.worker.available ? "Servicio sin conexión" : active ? labels[active.state] : "Disponible"}
      </span>
    </div>
    <div className="training-profile-tabs" role="group" aria-label="Perfil de Galancito que se evalúa">
      {(["postulantes", "interno"] as const).map(profile =>
        <button type="button" key={profile} aria-pressed={form.profile === profile}
          className={"training-profile-tab" + (form.profile === profile ? " is-active" : "")}
          onClick={() => {
            setForm(prev => ({ ...prev, profile, judge: "rules", corrector: "rules", profile_review: false,
              cases: profile === "interno" ? 400 : 100 }));
            setSelection(null); setFailures(null);
          }}>
          {profiles[profile]}
        </button>
      )}
    </div>
    {form.profile === "interno" && <div className="ai-panel" role="note">
      <strong>Galancito Interno · 20 categorías de práctica</strong>
      <p className="training-muted">Incluye navegación, obras, contratistas, fichas, publicaciones, informes,
        versiones, rendimiento, permisos y búsqueda web. Los 400 casos son ejemplos sintéticos,
        no lecturas del VPS ni entrenamiento de pesos del modelo.</p>
      <p className="training-muted">Elige Ollama para evaluar respuestas generadas por IA.
        “Reglas locales” solo valida la referencia determinista.</p>
    </div>}
    {data && <div className="ai-panel" aria-label="Motores de Galancito">
      <strong>Motor principal: Ollama · {data.local_model}</strong>
      <p className="training-muted">Próximas prácticas con Ollama: {data.local_model} · {data.training_mode === "motor_principal_compartido" ? "motor local compartido, sin duplicar el modelo en RAM" : "motor de entrenamiento separado"}.</p>
      <p className="training-muted">Las rondas anteriores conservan el modelo con el que se realizaron. {data.worker.available ? "Servicio de prácticas conectado." : "Entrenador detenido; no hay prácticas automáticas en ejecución."}</p>
    </div>}
    {loadError && <p role="alert" className="ai-error">{loadError}</p>}
    {error && <p role="alert" className="ai-error">{error}</p>}
    {notice && <p role="status" className="ai-notice">{notice}</p>}
    {data && !data.worker.available && <p className="ai-warning" role="status">El servidor de entrenamiento está desconectado. Tu ronda guardada continuará cuando vuelva a estar disponible.</p>}

    <div className="training-grid">
      <section className="ai-panel training-launch">
        <div className="ai-panel-head"><h3>Nueva práctica · {profiles[form.profile]}</h3></div>
        <form id="galancito-training-form" onSubmit={event => { event.preventDefault(); start(false); }}>
          <div className="training-fields">
            <label>Nivel<select value={form.level} onChange={event => setForm({ ...form, level: Number(event.target.value) })}>
              {levels.map((level, index) => <option key={level} value={index + 1}>{index + 1} · {level}</option>)}
            </select></label>
            <label>Casos objetivo<input required min="1" max="10000" type="number" value={form.cases} onChange={event => setForm({ ...form, cases: Number(event.target.value) })} /></label>
            <label>Conjunto<select value={form.suite} onChange={event => setForm({ ...form, suite: event.target.value })}>
              {Object.entries(suites).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select></label>
            <label>Modelo de respuesta<select value={form.model} onChange={event => setForm({ ...form, model: event.target.value })}>
              <option value="ollama">Ollama · {data?.local_model ?? "Modelo local"}</option><option value="guided">Reglas locales</option>{modelOptions}
            </select></label>
          </div>
          <details className="training-details">
            <summary>Opciones avanzadas</summary>
            <div className="training-fields">
              {form.profile === "postulantes" && <label>Evaluación<select value={form.judge} onChange={event => setForm({ ...form, judge: event.target.value })}>
                <option value="rules">Pruebas deterministas</option><option value="ollama">Ollama · {data?.local_model ?? "Modelo local"}</option>{modelOptions}
              </select></label>}
              {form.profile === "postulantes" && <label>Verificación de ficha<select value={form.profile_review ? "on" : "off"}
                onChange={event => setForm({ ...form, profile_review: event.target.value === "on" })}>
                <option value="off">Base</option><option value="on">Nombres y oficios declarados</option>
              </select></label>}
              {form.profile === "postulantes" && <label>Propuestas de corrección<select value={form.corrector} onChange={event => setForm({ ...form, corrector: event.target.value })}>
                <option value="rules">Por categoría</option><option value="ollama">Ollama · {data?.local_model ?? "Modelo local"}</option>{modelOptions}
              </select></label>}
              {form.suite === "practice" && <label>Semilla<input placeholder="Aleatoria" type="number" min="0" max="2147483647" value={form.seed} onChange={event => setForm({ ...form, seed: event.target.value })} /></label>}
              {fields.map(([key, label, min, max, step]) => <label key={key}>{label}
                <input required type="number" min={min} max={max} step={step} value={form[key]} onChange={event => setForm({ ...form, [key]: Number(event.target.value) })} />
              </label>)}
            </div>
          </details>
          <div className="training-actions">
            <button type="submit" className="gc-primary" disabled={busy || Boolean(active)}><Play size={16} /> Iniciar entrenamiento</button>
            <button type="button" className="gc-secondary" disabled={busy || Boolean(active)} onClick={() => start(true)}><Moon size={16} /> Entrenamiento nocturno</button>
          </div>
        </form>
      </section>
      <section className="ai-panel training-current">
        <div className="ai-panel-head"><h3>{round ? "Resultados de la ronda" : "Estado del entrenamiento"}</h3>
          {round && <span className={"training-pill " + round.state}>{labels[round.state]}</span>}
        </div>
        {round ? <>
          <div className="training-progress">
            <div><strong>{number(round.completed)}</strong><span> / {number(round.target)} casos</span></div>
            <span>{profiles[round.config.profile ?? "postulantes"]} · {suites[round.config.suite]} · Nivel {round.config.level} · {round.config.model.model}</span>
            <progress aria-label="Casos completados" value={round.completed} max={round.target} />
          </div>
          {round.reason && <p className={round.state === "error" ? "ai-error" : "training-muted"}>{round.reason}
            {round.state === "queued" && round.config.night ? " · " + timestamp(round.next_at) : ""}</p>}
          <dl className="training-metrics">
            <div><dt>Correctos</dt><dd>{number(stats?.passed)}</dd></div>
            <div><dt>Incorrectos</dt><dd>{number(stats?.failed)}</dd></div>
            <div><dt>Pendientes</dt><dd>{number(round.target - round.completed)}</dd></div>
            <div><dt>Alertas críticas</dt><dd className={stats?.critical ? "training-danger" : ""}>{number(stats?.critical)}</dd></div>
            <div><dt>{form.profile === "interno" ? "Exactitud factual" : "Exactitud de fichas"}</dt><dd>{percent(form.profile === "interno" ? stats?.dimensions.accuracy : stats?.profile_accuracy)}</dd></div>
            <div><dt>Comprensión del contexto</dt><dd>{percent(stats?.dimensions.context)}</dd></div>
            <div><dt>Naturalidad estimada por IA</dt><dd>{stats?.judged_turns ? percent(stats.dimensions.naturalness) : "Sin revisión IA"}</dd></div>
            <div><dt>Latencia de simulación por turno</dt><dd>{number(stats?.average_latency_ms)} {stats?.average_latency_ms != null && "ms"}</dd></div>
            <div><dt>Tokens registrados</dt><dd>{number((stats?.input_tokens ?? 0) + (stats?.output_tokens ?? 0))}</dd></div>
            <div><dt>Costo estimado de API</dt><dd>{price.format(stats?.estimated_cost_usd ?? 0)}</dd></div>
          </dl>
          {stats?.reply_sources && <p className="training-muted">
            Respuestas por origen · {number(stats.reply_sources.model ?? 0)} IA · {number(stats.reply_sources.rules ?? 0)} reglas · {number(stats.reply_sources.approved_correction ?? 0)} aprobadas · {number(stats.reply_sources.fallback ?? 0)} respaldo
          </p>}
          {form.profile === "postulantes" && !!stats?.questions && <p className="training-muted">
            Preguntas sobre datos ya entregados · {number(stats.repeated_questions)} de {number(stats.questions)} ({percent(stats.repetition_rate)})
          </p>}
          {!!stats?.judged_turns && <p className="training-muted">{number(stats.judged_turns)} turnos revisados para estimar naturalidad.</p>}
          {!!stats?.reserved_tokens && <p className="training-muted">{number(stats.reserved_tokens)} tokens reservados sin medición del proveedor.</p>}
          {form.profile === "postulantes" && stats?.fields ? <p className="training-muted">Fichas: {number(stats.correct_fields)} de {number(stats.fields)} campos presentes correctos.</p> : null}
          <div className="training-actions">
            {running.includes(round.state) && <>
              <button className="gc-secondary" disabled={busy} onClick={() => void perform(async () => {
                await json("/rounds/" + round.id + "/control/" + (round.state === "paused" ? "resume" : "pause"), null);
              })}>{round.state === "paused" ? <><Play size={15} /> Reanudar</> : <><Pause size={15} /> Pausar</>}</button>
              <button className="gc-secondary training-stop" disabled={busy} onClick={() => void perform(async () => {
                await json("/rounds/" + round.id + "/control/stop", null);
              })}><Square size={15} /> Detener</button>
            </>}
            <button className="gc-secondary" disabled={!stats?.failed || busy} onClick={() => void perform(() => viewErrors(round.id))}>
              <TriangleAlert size={15} /> Ver errores
            </button>
            {round.completed > 0 && <>
              <a className="gc-secondary" aria-describedby="training-export-help"
                href={exportUrl("/rounds/" + round.id + "/export/json")}>
                <Download size={15} /> Exportar resultados a ChatGPT
              </a>
              <a className="gc-secondary" href={exportUrl("/rounds/" + round.id + "/export/md")}>Informe Markdown</a>
            </>}
          </div>
          {round.completed > 0 && <p id="training-export-help" className="training-muted">
            Adjunta el archivo descargado en ChatGPT y escribe <strong>GALANT PRACTICA</strong>.
          </p>}
        </> : <div className="ai-empty">Las mediciones aparecerán cuando el trabajador complete los primeros casos.</div>}
      </section>
    </div>

    {failures && failureRound === round?.id && <section className="ai-panel">
      <div className="ai-panel-head"><h3>Casos fallidos</h3><button className="gc-secondary" onClick={() => setFailures(null)}>Cerrar</button></div>
      {failures.cases.length === 0 && <p className="training-muted">No hay detalles disponibles para esta ronda.</p>}
      {failures.cases.map(item => <details className="training-case" key={item.id}>
        <summary><strong>{item.id}</strong><span>{item.critical ? "Alerta crítica · " : ""}{Object.keys(item.errors).map(code => errorNames[code] ?? code).join(", ")}</span></summary>
        <ul>{Object.keys(item.errors).map(code => <li key={code}>{failures.proposals[code]}</li>)}</ul>
        {item.ai_proposal && <p className="training-muted">{item.ai_proposal}</p>}
        {item.turns?.map(turn => <div key={turn.turn} className="training-turn">
          <strong>Turno {turn.turn}</strong><p>{turn.message}</p><p>{turn.reply}</p>
          {Boolean(turn.issues?.length) && <p className="training-danger">
            {turn.issues?.map(code => errorNames[code] ?? code).join(" · ")}
          </p>}
          {Object.entries(turn.differences).map(([key, actual]) => <p key={key} className="training-danger">
            <strong>{fieldNames[key] ?? key}</strong> · Esperado {displayField(turn.expected[key])} · Registrado {displayField(actual)}
          </p>)}
        </div>)}
      </details>)}
      <div className="training-actions">
        {offset > 0 && <button className="gc-secondary" disabled={busy} onClick={() => void perform(() => viewErrors(failureRound, offset - 20))}>Anterior</button>}
        {failures.more && <button className="gc-secondary" disabled={busy} onClick={() => void perform(() => viewErrors(failureRound, offset + 20))}>Siguiente</button>}
      </div>
    </section>}

    <div className="training-grid">
      <section className="ai-panel">
        <div className="ai-panel-head"><h3><History size={17} /> Historial de rondas</h3></div>
        {history.length ? <div className="training-history">
          {history.map(item => <button key={item.id} aria-pressed={round?.id === item.id} className="training-history-row"
            onClick={() => { setSelection(item.id); setFailures(null); }}>
            <span><strong>{timestamp(item.created_at)}</strong><small>{suites[item.config.suite]} · Nivel {item.config.level} · {labels[item.state]} · {item.config.model.model}</small></span>
            <span className="training-bar" aria-hidden="true"><span style={{ width: (item.metrics.score ?? 0) + "%" }} /></span>
            <span>{item.metrics.score == null ? "—" : number(item.metrics.score) + " / 100"}</span><ChevronRight size={15} />
          </button>)}
        </div> : <p className="training-muted">Aún no hay rondas registradas.</p>}
        {round && <div className="training-history-info">
          <div><strong>{round.config.model.model}</strong><small>Evaluación · {round.config.judge.model}</small>
            {round.config.profile_review && <small>Verificación de ficha activa</small>}
          </div>
          {comparison && <div><strong>Comparación con {timestamp(comparison.created_at)}</strong><small>
            {sameEvaluation ? `${number(round.metrics.score)} / 100 frente a ${number(comparison.metrics.score)} / 100 · mismo conjunto`
              : "Metodología o evaluador distinto"}
          </small></div>}
          {!active && <div className="training-actions">
            <button className="gc-secondary" disabled={busy} onClick={() => repeatRound(round.id)}>
              <RotateCcw size={15} /> Reevaluar conjunto
            </button>
            {form.profile === "postulantes" && !round.config.profile_review && round.state === "completed" && round.completed === round.target &&
              <button className="gc-secondary" disabled={busy}
              onClick={() => repeatRound(round.id, true)}>Comparar con verificación</button>}
          </div>}
        </div>}
      </section>
      <section className="ai-panel">
        <div className="ai-panel-head"><h3><Activity size={17} /> Recursos del servidor</h3></div>
        <dl className="training-metrics">
          <div><dt>RAM disponible / total</dt><dd>{number(resources?.available_ram_mb)} / {number(resources?.host_ram_mb)} MB</dd></div>
          <div><dt>RAM del trabajador / límite</dt><dd>{number(resources?.worker_ram_mb)} / {number(resources?.worker_ram_limit_mb)} MB</dd></div>
          <div><dt>CPU del servidor</dt><dd>{resources?.host_cpu_percent != null ? number(resources.host_cpu_percent) + "%" : "—"}</dd></div>
          <div><dt>Núcleos del trabajador / servidor</dt><dd>{number(resources?.worker_cores)} / {number(resources?.host_cores)}</dd></div>
          <div><dt>Almacenamiento libre</dt><dd>{resources ? number(resources.disk_free_mb / 1024) + " GB" : "—"}</dd></div>
          <div><dt>GPU / VRAM detectada</dt><dd>{resources?.gpu?.length ? resources.gpu.map(gpu => gpu.name + " · " + number(gpu.vram_mb) + " MB").join(", ") : "Sin medición"}</dd></div>
        </dl>
        {stats && <details className="training-details"><summary>Resultados por competencia</summary>
          <dl className="training-metrics">
            {Object.entries(form.profile === "interno" ? internalDimensions : dimensions).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{percent(stats.dimensions[key])}</dd></div>)}
          </dl>
        </details>}
      </section>
    </div>

    {form.profile === "postulantes" && <section className="ai-panel">
      <div className="ai-panel-head"><div><h3>Correcciones aprobadas</h3><p>Conocimiento del laboratorio · versión {data?.knowledge.version ?? 0} · {data?.knowledge.corrections.length ?? 0} ejemplos activos</p></div></div>
      <details className="training-details"><summary>Importar correcciones o restaurar una versión</summary>
        <p className="training-muted">Elige una ronda finalizada. Cada entrada JSON debe incluir <code>case_id</code>, <code>turn</code>, <code>reply</code> e <code>instruction</code>.</p>
        <div className="training-review">
          <label htmlFor="training-json">Correcciones revisadas (arreglo JSON)</label>
          <textarea id="training-json" rows={5} value={corrections} onChange={event => setCorrections(event.target.value)} />
          <label>O carga un archivo JSON <input type="file" accept=".json,application/json" onChange={event => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (file.size > 30000) { setError("El archivo de correcciones supera 30 kB."); return; }
            void file.text().then(setCorrections).catch(err => setError(errorText(err)));
          }} /></label>
          <button className="gc-primary" disabled={busy || !round || !data || !corrections.trim() || running.includes(round.state) || round.config.suite === "holdout"}
            onClick={() => void perform(async () => {
              let entries: unknown;
              try { entries = JSON.parse(corrections); } catch { throw new Error("El texto debe contener un arreglo JSON válido."); }
              if (!Array.isArray(entries)) throw new Error("Entrega las correcciones como arreglo JSON.");
              const result = await json<{ version: number }>("/rounds/" + round?.id + "/corrections", {
                version: data?.knowledge.version, corrections: entries,
              });
              setCorrections("");
              setNotice("Correcciones aplicadas al laboratorio · versión " + result.version);
            })}>Aplicar correcciones aprobadas</button>
          {Boolean(data?.knowledge.version) && <div className="training-actions">
            <label>Versión anterior <select value={restoreVersion} onChange={event => setRestoreVersion(Number(event.target.value))}>
              <option value={0}>Sin correcciones</option>
              {data?.knowledge.revisions.filter(version => version !== data.knowledge.version).map(version =>
                <option key={version} value={version}>Versión {version}</option>)}
            </select></label>
            <button className="gc-secondary" disabled={busy} onClick={() => void perform(async () => {
              await json("/knowledge/rollback", { version: data?.knowledge.version, restore_version: restoreVersion });
              setRestoreVersion(0);
              setNotice("Versión de conocimiento restaurada.");
            })}>Restaurar</button>
          </div>}
        </div>
      </details>
      <details className="training-details"><summary>Dataset para ajuste de parámetros</summary>
        <p className="training-muted">Ejemplos sintéticos aprobados en JSONL. El ajuste de parámetros se ejecuta por separado.</p>
        <div className="training-actions">
          {([["train", "Entrenamiento"], ["validation", "Validación"], ["test", "Prueba"]] as const).map(([key, label]) =>
            <a key={key} className="gc-secondary" href={exportUrl("/knowledge/dataset/" + key)}><Download size={15} /> {label}</a>)}
        </div>
      </details>
    </section>}
  </div>;
}
