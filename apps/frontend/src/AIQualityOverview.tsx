import { useCallback, useEffect, useState } from "react";
import { Activity, ArrowRight, CheckCircle2, Clock3, FlaskConical, RefreshCw, Server, ShieldCheck, TriangleAlert } from "lucide-react";
import { request } from "./api";
import "./ai-quality-overview.css";

type ChannelName = "messenger" | "general";
type Channel = {
  runs: number;
  sample_capped: boolean;
  p50_ms: number | null;
  p95_ms: number | null;
  latency_sample: number;
  latency_basis: string;
  feedback: { useful: number; incorrect: number; total: number; useful_percent: number | null };
  model_errors: number;
  delivery_errors: number;
  cancelled: number;
  quality_score: number | null;
  quality_source: string;
  reviewed_cases: number;
  minimum_cases: number;
  rubric_version: number;
  dimension_scores: Record<string, number | null>;
  limitation: string;
  delivery_states?: Record<string, number>;
};
type Overview = {
  period_days: number;
  generated_at: string;
  score_method: string;
  channels: Record<ChannelName, Channel>;
  operational_lab: null | {
    created_at: string; cases: number; passed: number; score: number | null;
    holdout_gain_cases: number | null; holdout_regressions: number | null;
    source: string; model: string | null;
  };
  findings: Array<{ channel: ChannelName; type: string; count: number | null; label: string; focus: string }>;
};
type Bootstrap = {
  local_engine: { enabled: boolean; status: string; loaded: boolean; model: string; messenger: boolean; red_obras: boolean };
  connections: Array<{ enabled: boolean; status: string; has_key: boolean }>;
  learning: { approved: number; pending: number };
};
const fmt = new Intl.NumberFormat("es-CL");
const ms = (value: number | null) => value == null ? "Sin medición" : (value / 1000).toLocaleString("es-CL", { maximumFractionDigits: 2 }) + " s";
const names: Record<ChannelName, string> = { messenger: "Responder mensajes", general: "Galancito General" };
const reviewCriteria: Record<ChannelName, Array<{key: string; label: string}>> = {
  messenger: [
    {key: "understanding", label: "Comprensión"}, {key: "profile", label: "Ficha y oficio"},
    {key: "context", label: "Continuidad"}, {key: "naturalness", label: "Naturalidad"},
    {key: "safety", label: "Seguridad"}, {key: "helpfulness", label: "Utilidad"},
  ],
  general: [
    {key: "accuracy", label: "Exactitud"}, {key: "grounding", label: "Datos fundamentados"},
    {key: "context", label: "Contexto"}, {key: "reasoning", label: "Razonamiento"},
    {key: "safety", label: "Permisos"}, {key: "helpfulness", label: "Utilidad"},
  ],
};
type Defect = {criterion: string; label: string; reviewed: number; failed: number;
  failure_percent: number | null; priority: string; method: string; ready_for_practice: boolean;
  proposal_ready: boolean; active_coaching: boolean;
  practice: {better: number; same: number; worse: number; pending: number} };
type Plan = {channels: Record<ChannelName, {reviewed_cases: number; items: Defect[]}>};

export default function AIQualityOverview({
  onPractice, onConnections, onLearning,
}: {
  onPractice: (channel: ChannelName, focus?: string) => void;
  onConnections: () => void;
  onLearning: () => void;
}) {
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [expanded, setExpanded] = useState<ChannelName | null>(null);
  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    let active = true;
    setBusy(true);
    Promise.all([
      request<Overview>("/admin/ai/quality-overview?days=" + days),
      request<Bootstrap>("/admin/ai/bootstrap"),
      request<Plan>("/admin/ai/real-learning/plan?days=" + days),
    ]).then(([quality, config, learning]) => {
      if (!active) return;
      setOverview(quality);
      setBootstrap(config);
      setPlan(learning);
      setError("");
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "No se pudo consultar el servidor");
    }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [days, revision]);

  const connectionCount = bootstrap?.connections.filter(connection => connection.has_key && connection.enabled && connection.status === "verified").length ?? 0;
  const engine = bootstrap?.local_engine;
  const healthy = Boolean(engine?.enabled && engine.status === "available");

  return <div className="ai-quality" data-testid="ai-quality-overview">
    <header className="ai-quality-head">
      <div>
        <span className="ai-quality-eyebrow"><Activity size={14} /> SUPERVISIÓN</span>
        <h2>Estado de la IA</h2>
        <p>Datos registrados por GALANT. Sin notas inventadas.</p>
      </div>
      <div className="ai-quality-actions">
        <label>Período
          <select aria-label="Período de medición" value={days} onChange={event => setDays(Number(event.target.value))}>
            <option value={7}>7 días</option><option value={30}>30 días</option><option value={90}>90 días</option>
          </select>
        </label>
        <button type="button" title="Actualizar métricas" aria-label="Actualizar métricas" disabled={busy} onClick={reload}><RefreshCw size={17} /></button>
      </div>
    </header>
    {error && <p className="ai-quality-error" role="alert">{error}</p>}
    {busy && <p className="ai-quality-loading" role="status">Consultando mediciones…</p>}

    <div className="ai-quality-health">
      <div className="ai-quality-health-primary">
        <Server size={19} aria-hidden="true" />
        <div><strong>Modelo principal</strong><span>{engine?.model ?? "Sin verificar"}</span></div>
        <span className={"ai-quality-state" + (healthy ? " is-ready" : "")}>
          {engine ? (healthy ? "Disponible" : "No disponible") : "Consultando"}
        </span>
      </div>
      <div className="ai-quality-health-minor">
        <span>En memoria <strong>{engine ? (engine.loaded ? "Sí" : "No") : "—"}</strong></span>
        <span>API verificadas <strong>{bootstrap ? fmt.format(connectionCount) : "—"}</strong></span>
        <button type="button" onClick={onConnections}>Configurar modelos <ArrowRight size={14} /></button>
      </div>
    </div>

    <div className="ai-quality-channels">
      {(["messenger", "general"] as const).map(channel => {
        const data = overview?.channels[channel];
        return <section className="ai-quality-channel" key={channel} aria-label={names[channel]}>
          <div className="ai-quality-channel-head">
            <div><span className="ai-quality-channel-kicker">{channel === "messenger" ? "FACEBOOK / MESSENGER" : "CHAT INTERNO"}</span><h3>{names[channel]}</h3></div>
            <span className="ai-quality-source"><ShieldCheck size={13} /> Producción</span>
          </div>
          <div className="ai-quality-grade">
            <strong>{data?.quality_score == null ? "—" : data.quality_score}<small> / 100</small></strong>
            <div><b>Calidad de respuestas</b><span>{data?.quality_score == null
              ? (data ? `Sin nota todavía · ${data.reviewed_cases} de ${data.minimum_cases} auditorías` : "Pendiente de evaluación humana")
              : `Muestra revisada · ${data.reviewed_cases} conversaciones`}</span></div>
          </div>
          <div className="ai-quality-channel-stats">
            <div><span>Interacciones</span><strong>{data ? fmt.format(data.runs) : "—"}</strong></div>
            <div><span>{channel === "messenger" ? "Mediana a entrega" : "Mediana"}</span><strong>{ms(data?.p50_ms ?? null)}</strong></div>
            <div><span>Latencia p95</span><strong>{ms(data?.p95_ms ?? null)}</strong></div>
            <div><span>Reportes incorrectos</span><strong>{data ? fmt.format(data.feedback.incorrect) : "—"}</strong></div>
          </div>
          <p className="ai-quality-footnote">
            {data?.feedback.total
              ? `${fmt.format(data.feedback.total)} valoraciones de personas · ${data.feedback.useful_percent}% útiles. No equivalen a exactitud factual.`
              : "Sin valoraciones de personas para este período."}
            {data?.sample_capped ? " Últimas 2.000 interacciones (muestra acotada)." : ""}
            {channel === "messenger" && data ? ` Latencia de ${data.latency_sample} entregas confirmadas (desde el mensaje recibido).` : ""}
            {data && data.latency_sample < 20 ? " El p95 procede de pocas muestras y puede variar mucho." : ""}
            {data?.quality_score != null ? " Nota de muestra auditada, sin representatividad poblacional garantizada." : ""}
          </p>
          <button type="button" className="ai-quality-inspect" aria-expanded={expanded === channel}
            onClick={() => setExpanded(expanded === channel ? null : channel)}>
            {expanded === channel ? "Cerrar diagnóstico" : "Ver diagnóstico por competencia"} <ArrowRight size={14}/>
          </button>
          {expanded === channel && <section className="ai-quality-breakdown" aria-label={"Diagnóstico real de " + names[channel]}>
            <p>{data?.reviewed_cases || 0} conversaciones auditadas. Las proporciones por criterio solo describen esta muestra,
              incluso si hay menos de 30. No son una nota global.</p>
            {reviewCriteria[channel].map(({key, label}) => {
              const dimension = data?.dimension_scores?.[key];
              const item = plan?.channels[channel]?.items.find(row => row.criterion === key);
              return <article key={key}>
                <div className="ai-quality-breakdown-head">
                  <b>{label}</b>
                  <strong>{dimension == null ? "Sin muestras" : dimension.toLocaleString("es-CL") + "% en muestra"}</strong>
                </div>
                <p>{item ? `${item.failed} fallas de ${item.reviewed} revisiones · Prioridad: ${item.priority.replaceAll("_", " ")}` : "Sin evaluación disponible"}
                  {item?.active_coaching ? " · Guía aprobada y activa" : ""}
                </p>
                {item && <p>Corrección propuesta: {item.method} · Qwen real: {item.practice.better} mejoras revisadas,
                  {" "}{item.practice.same} sin cambio y {item.practice.worse} regresiones. No demuestra mejora general.</p>}
                {item?.ready_for_practice && <button type="button" onClick={() => onPractice(channel, key)}>
                  Práctica complementaria <ArrowRight size={13}/>
                </button>}
              </article>;
            })}
            <small>Para una prueba con mensajes reales, utiliza «Revisar respuestas de producción» y evalúa cada candidata.
              Nunca se entrena con mensajes privados en servicios externos.</small>
          </section>}
          {channel === "messenger" && data?.delivery_states && Object.keys(data.delivery_states).length > 0 &&
            <details className="ai-quality-technical"><summary>Estados reales de entrega</summary>
              {Object.entries(data.delivery_states).map(([state, count]) => <span key={state}>{state}: {fmt.format(count)}</span>)}
            </details>}
          <button className="ai-quality-practice" type="button" onClick={() => onPractice(channel)}>
            <FlaskConical size={16} /> Abrir pruebas de {channel === "messenger" ? "Messenger" : "Galancito"} <ArrowRight size={15} />
          </button>
        </section>;
      })}
    </div>

    <section className="ai-quality-findings">
      <div className="ai-quality-section-head"><div><h3>Qué necesita mejorar</h3><p>Hallazgos de registros reales, no de simulaciones.</p></div>
        <span>{overview ? overview.findings.length + " hallazgos" : "—"}</span></div>
      {overview?.findings.length === 0 && <div className="ai-quality-empty"><CheckCircle2 size={19} />
        No se encontraron incidencias según los indicadores disponibles. Esto no confirma que las respuestas sean correctas.</div>}
      {overview?.findings.map((finding, index) => <div className="ai-quality-finding" key={finding.channel + finding.type + index}>
        <TriangleAlert size={16} aria-hidden="true" />
        <div><strong>{finding.label}</strong><span>{names[finding.channel]}{finding.count != null ? " · " + fmt.format(finding.count) + " registros" : ""}</span></div>
        <button type="button" onClick={() => onPractice(finding.channel, finding.focus)}>Evaluar <ArrowRight size={14} /></button>
      </div>)}
      {overview?.operational_lab && <div className="ai-quality-lab">
        <Clock3 size={16} /><div><strong>Última prueba con agregados de GALANT: {overview.operational_lab.score ?? "—"} / 100</strong>
          <span>{overview.operational_lab.passed} de {overview.operational_lab.cases} ejercicios correctos. Son pruebas operativas de laboratorio, no conversaciones de producción.</span></div>
      </div>}
    </section>

    <section className="ai-quality-next">
      <div><span className="ai-quality-eyebrow"><CheckCircle2 size={14} /> ÚLTIMO PASO</span>
        <h3>Aprendizaje y mejora</h3><p>Diagnosticar, corregir, probar de nuevo y validar antes de aplicar. Una práctica sintética nunca se presenta como mejora real.</p></div>
      <button type="button" onClick={onLearning}>Revisar aprendizaje <ArrowRight size={16} /></button>
    </section>
  </div>;
}
