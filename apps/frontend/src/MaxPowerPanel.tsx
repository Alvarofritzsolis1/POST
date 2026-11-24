import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, BrainCircuit, CheckCircle2, Clock3, Download, Gauge, History, Power, RefreshCw, ShieldCheck, Zap } from "lucide-react";
import { request } from "./api";
import "./max-power.css";
import FineTuneProgress from "./FineTuneProgress";
import MaxPowerLive from "./MaxPowerLive";

type Sample = { quality_score: number | null; reviewed_cases: number; minimum_cases: number;
  dimension_scores: Record<string, number | null>; quality_source: string };
type Delta = { initial: number | null; latest: number | null; delta_points: number | null; sample_count: number };
type Event = { id: string; at: string; event: string; reason: string; evidence: Record<string, unknown> };
type CheckCount = { passed: number | null; samples: number };
type PracticeSample = {
  cases: number;
  dimensions: Record<string, CheckCount>;
  fields: Record<string, CheckCount>;
  style_signals: CheckCount;
  safety: {gate_passed: boolean; unsupported_values: number; privacy_or_promise_failures: number};
};
type LiveActivity = {
  updated_at: string;
  controller_at: string | null;
  next_check_at: string | null;
  practice_cases: number;
  qwen: {state: "off" | "waiting" | "running"; reason: string; completed?: number | null;
         total?: number; unit?: string; started_at?: string | null; retry_at?: string | null; required_ram_mb?: number};
};
type Status = {
  enabled: boolean; controller_online: boolean; trainer_online: boolean;
  neural_2b?: {stage:string;live:boolean;completed_steps:number;target_steps:number;data_kind:string;conversation_gate:boolean;production_promoted:boolean;holdout_loss_before:number|null;holdout_loss_after:number|null;blockers:string[]};
  cpu_learning?: {status:string;reason:string;last_update_at:string|null;
                  manager_online:boolean;weights_trained:boolean;synthetic_weights_trained?:boolean;
                  training_kind?:string;model:string};
  status: string; reason: string; active_seconds: number; sessions: number; experiments: number;
  examined_cases: number; observed_holdout_wins: number; observed_holdout_regressions: number;
  first_started_at: string | null; session_started_at: string | null; active_round_id: string | null;
  priorities: Array<{channel: string; criterion: string; failures: number}>;
  quality: Record<string, Sample>; quality_deltas: Record<string, Delta>;
  messenger_experiments?: {trials: number; objective_gains: number; regressions: number; inconclusive: number; active: number};
  automatic_quality?: Record<string,{pairs:number; baseline:number|null;candidate:number|null;delta_points:number|null;scope:string;minimum_cases:number;notes:string}>;
  synthetic_practice?: {at: string; development: PracticeSample; holdout: PracticeSample;
                       target_weights: Record<string,number>} | null;
  synthetic_qwen?: {queued_or_running: number; completed?: number; blocked: number; reserved_pairs: number;
                    baseline_passes: number; candidate_passes: number; gains: number;
                    regressions: number; safety_failures: number} | null;
  resource_snapshot?: Record<string,number | null>;
  live_activity?: LiveActivity;
  latest_result: Record<string, unknown>;
  latency_diagnosis: {code: string; reason: string; measured_ms?: number; suggestion?: string};
  events: Event[]; limitations: string;
};
const f = (n: number) => new Intl.NumberFormat("es-CL").format(n);
const time = (s: number) => {
  const days = Math.floor(s / 86400), hours = Math.floor(s % 86400 / 3600), minutes = Math.floor(s % 3600 / 60);
  return (days ? days + " d " : "") + hours + " h " + minutes + " min";
};
const pretty: Record<string,string> = {
  reasoning:"Razonamiento", accuracy:"Exactitud", grounding:"Datos fundamentados",
  context:"Memoria y contexto", understanding:"Comprensión", profile:"Ficha y oficio",
  naturalness:"Naturalidad", helpfulness:"Utilidad", safety:"Seguridad y permisos"
};
const channels = [{id:"messenger", label:"Messenger"},{id:"general",label:"Galancito General"}];
const grade = (n:number|null|undefined) => n == null ? "Sin nota" : n.toLocaleString("es-CL",{maximumFractionDigits:1}) + "/100";
const date = (v:string|null) => v ? new Date(v).toLocaleString("es-CL", {timeZone:"America/Santiago"}) : "—";
const clock = (value: string) => new Date(value).toLocaleTimeString("es-CL", {
  timeZone: "America/Santiago", hour: "2-digit", minute: "2-digit", second: "2-digit",
});
const practiceDimensions = {profile:"Precisión de ficha", understanding:"Comprensión",
  humanity:"Trato humano", continuity:"Continuidad"};
const profileFields: Record<string,string> = {
  availability:"Disponibilidad", contact_email:"Correo voluntario", contact_phone:"Teléfono voluntario",
  contact_state:"Canal de contacto", display_name:"Nombre declarado", entity_type:"Empresa o independiente",
  experience:"Experiencia", has_employees:"Tiene personal contratado", employee_count:"Personas contratadas", interest_type:"Interés laboral",
  specialty:"Oficio principal", trades:"Oficios declarados", team_available:"Disponibilidad de cuadrilla",
  workers:"Capacidad de cuadrilla", work_communes:"Comunas de trabajo", name_opt_out:"Decisión sobre compartir nombre"
};
const checks = (count: CheckCount) => count.passed == null || count.samples === 0
  ? "Datos insuficientes" : f(count.passed) + " / " + f(count.samples);
const controllerStatus: Record<string,string> = {
  resource_guard:"En espera de recursos", synthetic_practice_completed:"Práctica de fichas terminada",
  awaiting_new_evidence:"En espera de datos nuevos", preparing_qwen:"Preparando Qwen 2B privado",
  cpu_neural_training:"Turno reservado para LoRA CPU", synthetic_model_evaluation:"Evaluación de Qwen 2B",
  messenger_evaluation:"Evaluación de Messenger", starting:"Iniciando", off:"En pausa",
};
const neuralStages: Record<string,string> = {
  awaiting_resources:"En espera de memoria o disco", waiting_turn:"En espera de turno",
  loading:"Cargando modelo", training:"Entrenando adaptador", evaluating:"Evaluando casos reservados",
  paused:"En pausa", completed:"Ronda completada", awaiting_approved_dataset:"En espera de datos autorizados",
  failed:"Ronda interrumpida", retry_exhausted:"Reintentos agotados",
};
const neuralBlockers: Record<string,string> = {
  host_free_mb:"RAM disponible del VPS", cgroup_limit_mb:"Límite de RAM del contenedor",
  cgroup_available_mb:"RAM disponible del contenedor", disk_free_mb:"Espacio en disco",
};

export default function MaxPowerPanel(){
  const [data,setData] = useState<Status|null>(null);
  const [busy,setBusy] = useState(false);
  const [downloading,setDownloading] = useState(false);
  const [error,setError] = useState("");
  const refreshing = useRef<AbortController | null>(null);
  const changingPower = useRef(false);
  const refresh = useCallback(async()=> {
    if (refreshing.current || changingPower.current) return;
    const controller = new AbortController();
    refreshing.current = controller;
    try {
      const next = await request<Status>("/admin/ai/max-power", {signal: controller.signal});
      if (!controller.signal.aborted) {setData(next); setError("");}
    } catch(e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "No se pudo leer MAX POWER");
    } finally {
      if (refreshing.current === controller) refreshing.current = null;
    }
  },[]);
  useEffect(()=>{
    void refresh();
    const whenVisible = () => {if (!document.hidden) void refresh();};
    const timer = window.setInterval(whenVisible, 5000);
    document.addEventListener("visibilitychange", whenVisible);
    return ()=>{
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", whenVisible);
      refreshing.current?.abort();
      refreshing.current = null;
    };
  },[refresh]);
  const toggle=async()=>{
    if(!data || changingPower.current) return;
    changingPower.current = true;
    refreshing.current?.abort();
    setBusy(true);
    try {
      const next=await request<Status>("/admin/ai/max-power/control/" + (data.enabled?"off":"on"),{method:"POST"});
      setData(next);setError("");
    } catch(e){setError(e instanceof Error?e.message:"No se pudo cambiar el estado");}
    finally{changingPower.current = false; setBusy(false);}
  };
  const downloadForChatGPT=async()=>{
    if(downloading)return;
    setDownloading(true);
    try{
      const response=await fetch("/api/v1/admin/ai/max-power/export",{
        credentials:"include",cache:"no-store",headers:{"Accept":"application/json"}
      });
      if(!response.ok){
        if(response.status===401)window.dispatchEvent(new window.Event("galant-session-ended"));
        throw new Error("No se pudo generar el informe (HTTP "+response.status+").");
      }
      const blob=await response.blob();
      if(!blob.size)throw new Error("El informe generado está vacío.");
      const localUrl=URL.createObjectURL(blob);
      const anchor=document.createElement("a");
      anchor.href=localUrl;
      anchor.download="galant-max-power-chatgpt-"+new Date().toISOString().replace(/[:.]/g,"-")+".json";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(()=>URL.revokeObjectURL(localUrl),1500);
      setError("");
    }catch(e){setError(e instanceof Error?e.message:"No se pudo descargar el informe.");}
    finally{setDownloading(false);}
  };
  const result=data?.latest_result || {};
  const practice = data?.synthetic_practice;
  const qwen = data?.synthetic_qwen;
  const resources = data?.resource_snapshot;
  const live = data?.live_activity;
  const model = live?.qwen;
  const practiceCompleted = practice ? practice.development.cases + practice.holdout.cases : null;
  const cpuStatus = data?.cpu_learning;
  const neural2b=data?.neural_2b;
  const neuralRunning=Boolean(data?.enabled && neural2b?.live && ["loading","training","evaluating"].includes(neural2b.stage));
  const cpuRunning = Boolean(data?.enabled && ["training", "training_synthetic"].includes(cpuStatus?.status ?? ""));
  const cpuPreparing = Boolean(data?.enabled && cpuStatus?.status === "preparing_synthetic");
  const cpuLabFinished = cpuStatus?.status === "finished_synthetic";
  const hasMeasuredActivity = Boolean(data?.enabled && data.controller_online &&
    (model?.state === "running" || cpuRunning || cpuPreparing || neuralRunning));
  const powerTitle = !data?.enabled ? "MAX POWER apagado"
    : !data.controller_online ? "MAX POWER encendido · controlador desconectado"
    : hasMeasuredActivity ? "MAX POWER encendido · trabajando"
    : "MAX POWER encendido · en espera";
  const powerExplanation = !data?.enabled ? "Los resultados se mantienen guardados"
    : !data.controller_online ? "Sin conexión con el controlador; no hay ejecución verificada"
    : hasMeasuredActivity ? "Hay tareas reales en ejecución; consulta sus resultados abajo"
    : data.reason || "Sin nuevas tareas verificables; el controlador sigue conectado";
  // Unmodified, measured experimental latency. Differences in workload mix
  // mean this chart must never be labelled a causal speed improvement.
  const latencyHistory=(data?.events || [])
    .filter(e=>e.event==="experiment_completed" &&
      typeof e.evidence.inference_p95_ms==="number" &&
      Number.isFinite(e.evidence.inference_p95_ms) &&
      (e.evidence.inference_p95_ms as number)>=0)
    .slice(0,30).reverse()
    .map(e=>({at:e.at,p95:e.evidence.inference_p95_ms as number}));
  const latencyMin=latencyHistory.length?Math.min(...latencyHistory.map(e=>e.p95)):0;
  const latencyMax=latencyHistory.length?Math.max(...latencyHistory.map(e=>e.p95)):0;
  const latencyLine=latencyHistory.map((event,i)=>{
    const x=16+i*668/Math.max(1,latencyHistory.length-1);
    const y=92-(event.p95-latencyMin)*68/Math.max(1,latencyMax-latencyMin);
    return x.toFixed(1)+","+y.toFixed(1);
  }).join(" ");
  return <section className="max-power">
    <header className="max-power-header">
      <div><span className="max-power-eyebrow"><BrainCircuit size={14}/> APRENDIZAJE ADAPTATIVO</span>
        <h2>MAX POWER</h2>
        <p>Práctica de fichas, evaluación de Galancito y entrenamiento LoRA.</p>
      </div>
      <button className="max-power-refresh" type="button" title="Actualizar datos" onClick={()=>void refresh()}><RefreshCw size={17}/></button>
    </header>
    {error && <p className="max-power-error" role="alert">{error}</p>}
    <div className="max-power-hero">
      <div className="max-power-control">
        <button type="button" onClick={()=>void toggle()} disabled={!data||busy}
          aria-label={data?.enabled?"Apagar MAX POWER":"Encender MAX POWER"}
          className={"max-power-switch" + (data?.enabled?" on":"")} aria-pressed={data?.enabled??false}>
          <Power size={26}/>
        </button>
        <div><strong>{powerTitle}</strong>
          <span>{powerExplanation}</span>
        </div>
      </div>
      <div className="max-power-pulse">
        <span className="max-power-stat"><Clock3 size={16}/> Tiempo activo <strong>{data?time(data.active_seconds):"—"}</strong></span>
        <span className="max-power-stat"><Activity size={16}/> Experimentos <strong>{data?f(data.experiments):"—"}</strong></span>
        <span className="max-power-stat"><ShieldCheck size={16}/> Casos examinados <strong>{data?f(data.examined_cases):"—"}</strong></span>
      </div>
    </div>
    {data && <div className="max-power-status">
      <div><strong>Qwen3.5 2B · QLoRA por CPU · {neural2b ? neuralStages[neural2b.stage] ?? "Estado pendiente" : "Sin informe del entrenador"}</strong>
        <p>{neural2b ? `${neural2b.completed_steps} de ${neural2b.target_steps} pasos con pesos modificados` : "Esperando datos medidos del contenedor aislado"}</p>
        {neural2b && <>
          <progress aria-label="Pasos de entrenamiento QLoRA completados" value={neural2b.completed_steps} max={neural2b.target_steps}/>
          <small>{neural2b.live ? "Informe reciente" : "Último informe guardado"}</small>
          {neural2b.blockers.length > 0 && <small>Recursos insuficientes · {neural2b.blockers.map(key => neuralBlockers[key] ?? key).join(", ")}</small>}
        </>}
      </div>
    </div>}
    {data && <div className="max-power-status">
      <span className={"max-power-dot" + (data.enabled && data.controller_online?" live":"")}/>
      <strong>{controllerStatus[data.status] ?? data.status.replaceAll("_"," ")}</strong>
      <span>{data.reason}</span>
    </div>}
    <MaxPowerLive resources={resources}/>
    <article className="max-power-card max-power-live">
      <div className="max-power-live-header">
        <div className="max-power-section-title"><Activity size={17}/><h3>Actividad en vivo</h3></div>
        {live && <small>{error ? "Última lectura" : "Lectura del panel"} {clock(live.updated_at)} · se consulta cada 5 s</small>}
      </div>
      <div className="max-power-live-grid">
        <div className="max-power-stage" data-state={practice ? "complete" : data?.enabled ? "waiting" : "off"}>
          <h4>Práctica de fichas</h4>
          <strong>{practiceCompleted != null ? `${f(practiceCompleted)} fichas evaluadas` : data?.enabled ? "Pendiente" : "En pausa"}</strong>
          {practiceCompleted != null && live && <progress aria-label="Fichas sintéticas evaluadas"
            value={practiceCompleted} max={Math.max(practiceCompleted, live.practice_cases)} />}
          <p>{practice ? `Resultado guardado ${date(practice.at)}`
            : live ? `${f(live.practice_cases)} casos sintéticos preparados.` : "Esperando el resultado del controlador."}</p>
        </div>
        <div className="max-power-stage" data-state={model?.state ?? "off"}>
          <h4>Evaluación · Qwen 2B</h4>
          <strong>{model?.state === "running" ? "En ejecución" : data?.enabled ? "En espera" : "En pausa"}</strong>
          <p>{model?.reason ?? data?.reason ?? "Esperando el estado del controlador."}</p>
          {model?.required_ram_mb && typeof resources?.available_ram_mb === "number" &&
            <small>{f(resources.available_ram_mb)} MB libres de {f(model.required_ram_mb)} MB requeridos</small>}
          {model?.completed != null && model.total != null && model.total > 0 && <>
            <progress aria-label={`Progreso Qwen 2B por ${model.unit}`} value={model.completed} max={model.total} />
            <small>{f(model.completed)} de {f(model.total)} {model.unit}</small>
          </>}
          {model?.started_at && <small>Etapa iniciada a las {clock(model.started_at)}</small>}
          {model?.retry_at && <small>Próximo intento a partir de las {clock(model.retry_at)}</small>}
          {qwen?.completed != null && qwen.completed > 0 && <small>{f(qwen.completed)} ensayos sintéticos terminados</small>}
        </div>
        <div className="max-power-stage" data-state={cpuRunning ? "running" : cpuLabFinished ? "complete" : data?.enabled ? "waiting" : "off"}>
          <h4>{cpuStatus?.training_kind === "curated_synthetic" ? "LoRA CPU · laboratorio sintético" : "Entrenamiento LoRA CPU"}</h4>
          <strong>{cpuRunning ? "Entrenando pesos" : cpuPreparing ? "Preparando entrenamiento" : cpuLabFinished ? "Prueba LoRA sintética completada" : data?.enabled ? "En espera" : "En pausa"}</strong>
          <p>{data?.enabled ? cpuStatus?.reason ?? "Esperando al supervisor" : "Se conservan los checkpoints."}</p>
          {cpuStatus?.synthetic_weights_trained && <small>Pesos de prueba actualizados con ejemplos ficticios. No hay mejora comprobada del modelo de Messenger.</small>}
          {cpuStatus?.last_update_at && <small>Supervisor {clock(cpuStatus.last_update_at)}</small>}
        </div>
      </div>
      {data?.enabled && live?.controller_at && <small>
        Última comprobación del controlador {clock(live.controller_at)}
        {live.next_check_at && ` · Próxima comprobación a partir de las ${clock(live.next_check_at)}`}
      </small>}
    </article>
    <article className="max-power-card max-power-practice">
      <div className="max-power-section-title"><ShieldCheck size={17}/><h3>Práctica sintética de fichas y conversación</h3></div>
      {practice ? <>
        <p>{f(practice.development.cases)} casos de desarrollo · {f(practice.holdout.cases)} reservados · {date(practice.at)}</p>
        <div className="max-power-competencies">
          {Object.entries(practiceDimensions).map(([key,label]) => <div className="max-power-competency" key={key}>
            <span>{label} · peso objetivo {practice.target_weights[key]}%</span>
            <span>{checks(practice.holdout.dimensions[key])}</span>
          </div>)}
          <div className="max-power-competency"><span>Señales objetivas de estilo</span>
            <span>{checks(practice.holdout.style_signals)}</span></div>
          <div className="max-power-competency"><span>Privacidad y datos inventados</span>
            <span>{practice.holdout.safety.gate_passed ? "Sin incidentes detectados" :
              f(practice.holdout.safety.unsupported_values + practice.holdout.safety.privacy_or_promise_failures) + " fallas"}</span></div>
        </div>
        <details><summary>Ver aciertos por campo en casos reservados</summary>
          {Object.entries(practice.holdout.fields).map(([key,count]) => <div className="max-power-competency" key={key}>
            <span>{profileFields[key] ?? (profileFields[key.replace("_estado", "")] + " · estado y origen")}</span>
            <span>{checks(count)}</span>
          </div>)}
        </details>
      </> : <p>Esperando una evaluación con casos sintéticos. Los resultados se guardan al terminar.</p>}
      {qwen && <div className="max-power-competencies">
        <div className="max-power-competency"><span>Qwen 2B aislado · respuestas sintéticas</span>
          <span>{qwen.reserved_pairs ? `A/B ${qwen.baseline_passes} → ${qwen.candidate_passes} de ${qwen.reserved_pairs} pares reservados`
            : "Datos insuficientes"}</span></div>
        {(qwen.reserved_pairs > 0 || qwen.queued_or_running > 0 || qwen.blocked > 0) && <p>
          {qwen.gains} ganancias y {qwen.regressions} regresiones en reserva, con {qwen.safety_failures} fallas de seguridad.
          {" "}{qwen.queued_or_running} ensayos pendientes y {qwen.blocked} bloqueados.
        </p>}
      </div>}
      {resources && typeof resources.host_cpu_percent === "number" && <p>
        CPU {f(Math.round(resources.host_cpu_percent))}%
        {typeof resources.available_ram_mb === "number" && " · RAM disponible " + f(resources.available_ram_mb) + " MB"}
        {typeof resources.disk_free_mb === "number" && " · Disco libre " + f(resources.disk_free_mb) + " MB"}
      </p>}
    </article>
    <FineTuneProgress/>
    <div className="max-power-section-title"><Gauge size={17}/><h3>Resultados verificables de cada experimento</h3></div>
    <div className="max-power-channel-grid">
      {channels.map(c=>{
        const score=data?.automatic_quality?.[c.id];
        return <article key={c.id} className="max-power-card">
          <div className="max-power-card-top"><strong>{c.label}</strong><span>Evaluación automática</span></div>
          <div className="max-power-scores">
            <div><small>Referencia A/B</small><strong>{grade(score?.baseline)}</strong></div>
            <div><small>Variante probada</small><strong>{grade(score?.candidate)}</strong></div>
            <div><small>Ganancia observada</small><strong>{score?.delta_points==null?"Sin evidencia":(score.delta_points>0?"+":"")+score.delta_points.toLocaleString("es-CL")+" pts"}</strong></div>
          </div>
          <p>{score ? f(score.pairs)+" pares evaluados automáticamente; mínimo "+score.minimum_cases+"." : "Sin pruebas automáticas terminadas."} {score?.notes || "Las notas aparecen solo con casos verificables."}</p>
          <div className="max-power-competencies">
            <div className="max-power-competency"><span>Ámbito de evaluación</span><span>{score?.scope.replaceAll("_"," ")||"No evaluado"}</span></div>
          </div>
        </article>;
      })}
    </div>
    <article className="max-power-card max-power-latency-history">
      <div className="max-power-section-title"><Activity size={17}/><h3>Evolución de latencia del laboratorio</h3></div>
      {latencyHistory.length>=2 ? <>
        <svg viewBox="0 0 700 114" width="100%" role="img" aria-label={"Latencia p95 observada en "+latencyHistory.length+" experimentos"}>
          <path d="M16 92 H684" stroke="#d6e5e1" strokeWidth="1" fill="none"/>
          <polyline points={latencyLine} stroke="#177a68" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
          {latencyHistory.map((event,i)=>{
            const x=16+i*668/Math.max(1,latencyHistory.length-1);
            const y=92-(event.p95-latencyMin)*68/Math.max(1,latencyMax-latencyMin);
            return <circle key={event.at+"-"+i} cx={x} cy={y} r={3} fill="#177a68"/>;
          })}
        </svg>
        <div className="max-power-chart-labels">
          <span>{date(latencyHistory[0].at)} · {(latencyHistory[0].p95/1000).toFixed(2)} s</span>
          <span>{date(latencyHistory[latencyHistory.length-1].at)} · {(latencyHistory[latencyHistory.length-1].p95/1000).toFixed(2)} s</span>
        </div>
        <p className="max-power-note">Valores reales por experimento. La carga, los modelos y las preguntas pueden variar; una curva descendente no demuestra una mejora causada por MAX POWER.</p>
      </> : <p>Se necesitan al menos dos experimentos con latencia p95 medida. No se generan valores de demostración.</p>}
    </article>
    <div className="max-power-lower">
      <article className="max-power-card">
        <div className="max-power-section-title"><AlertTriangle size={18}/><h3>Qué impide mejorar</h3></div>
        <p><strong>Último diagnóstico:</strong> {typeof result.reason==="string"?result.reason:"Aún no hay una evaluación A/B terminada."}</p>
        <p><strong>Siguiente estrategia:</strong> {typeof result.next==="string"?result.next:"Inspeccionar casos reales y evaluar la disponibilidad del motor."}</p>
        <p><strong>Rendimiento:</strong> {data?.latency_diagnosis.reason||"Sin mediciones"}
          {data?.latency_diagnosis.suggestion ? " · " + data.latency_diagnosis.suggestion : ""}</p>
        <p><strong>Latencia p50/p95 del último laboratorio:</strong> {typeof result.inference_p50_ms==="number" ? (result.inference_p50_ms/1000).toFixed(2)+" s" : "Sin medición"} / {typeof result.inference_p95_ms==="number" ? (result.inference_p95_ms/1000).toFixed(2)+" s" : "Sin medición"}</p>
        {typeof result.paired_speed==="object" && result.paired_speed!==null ? <p><strong>Prueba pareada de velocidad:</strong> {JSON.stringify(result.paired_speed)}. Exploratoria, no mejora productiva confirmada.</p> : null}
        {data?.messenger_experiments && <p><strong>Messenger real:</strong> {f(data.messenger_experiments.trials)} ensayos; {f(data.messenger_experiments.objective_gains)} correcciones objetivas observadas; {f(data.messenger_experiments.regressions)} regresiones. No son una nota de calidad general.</p>}
        <div className="max-power-mini">
          <span>Casos corregidos en reserva <strong>{data?f(data.observed_holdout_wins):"—"}</strong></span>
          <span>Regresiones detectadas <strong>{data?f(data.observed_holdout_regressions):"—"}</strong></span>
        </div>
        <p className="max-power-note">Resultados de laboratorio, no equivalentes a una modificación de los pesos ni a una mejora desplegada.</p>
      </article>
      <article className="max-power-card">
        <div className="max-power-section-title"><History size={18}/><h3>Histórico permanente</h3></div>
        <p>Primer encendido: {date(data?.first_started_at??null)} · Sesiones: {data?f(data.sessions):"—"}</p>
        <div className="max-power-events">
          {(data?.events||[]).length===0 && <p>Los experimentos y decisiones aparecerán aquí sin inventar resultados.</p>}
          {(data?.events||[]).slice(0,9).map(e=><div key={e.id} className="max-power-event">
            {e.event==="experiment_completed"?<CheckCircle2 size={15}/>:<Zap size={15}/>}
            <div><strong>{e.event.replaceAll("_"," ")}</strong><small>{date(e.at)}</small><p>{e.reason}</p></div>
          </div>)}
        </div>
      </article>
    </div>
    <div className="max-power-export">
      <div><strong>Informe para analizar con ChatGPT</strong>
        <p>Descarga un archivo JSON con errores, métricas, experimentos e historial. No incluye conversaciones privadas ni credenciales.</p>
      </div>
      <button className="max-power-download" type="button" onClick={()=>void downloadForChatGPT()}
        disabled={downloading} aria-label="Descargar informe para ChatGPT">
        <Download size={16}/>{downloading?"Preparando informe…":"Descargar informe"}
      </button>
    </div>
    <p className="max-power-disclaimer">{data?.limitations||"Las calificaciones solo aparecen tras reunir evidencia real suficiente."}</p>
  </section>;
}
