import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, BrainCircuit, CheckCircle2, Clock3, Download, Gauge, History, Power, RefreshCw, ShieldCheck, Zap } from "lucide-react";
import { request } from "./api";
import "./max-power.css";

type Sample = { quality_score: number | null; reviewed_cases: number; minimum_cases: number;
  dimension_scores: Record<string, number | null>; quality_source: string };
type Delta = { initial: number | null; latest: number | null; delta_points: number | null; sample_count: number };
type Event = { id: string; at: string; event: string; reason: string; evidence: Record<string, unknown> };
type Status = {
  enabled: boolean; controller_online: boolean; trainer_online: boolean;
  status: string; reason: string; active_seconds: number; sessions: number; experiments: number;
  examined_cases: number; observed_holdout_wins: number; observed_holdout_regressions: number;
  first_started_at: string | null; session_started_at: string | null; active_round_id: string | null;
  priorities: Array<{channel: string; criterion: string; failures: number}>;
  quality: Record<string, Sample>; quality_deltas: Record<string, Delta>;
  messenger_experiments?: {trials: number; objective_gains: number; regressions: number; inconclusive: number; active: number};
  automatic_quality?: Record<string,{pairs:number; baseline:number|null;candidate:number|null;delta_points:number|null;scope:string;minimum_cases:number;notes:string}>;
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
const date = (v:string|null) => v ? new Date(v).toLocaleString("es-CL") : "—";

export default function MaxPowerPanel(){
  const [data,setData] = useState<Status|null>(null);
  const [busy,setBusy] = useState(false);
  const [downloading,setDownloading] = useState(false);
  const [error,setError] = useState("");
  const refresh = useCallback(async()=> {
    try { const next=await request<Status>("/admin/ai/max-power"); setData(next); setError(""); }
    catch(e){setError(e instanceof Error ? e.message : "No se pudo leer MAX POWER");}
  },[]);
  useEffect(()=>{
    void refresh();
    const timer=window.setInterval(()=>void refresh(),10000);
    return ()=>window.clearInterval(timer);
  },[refresh]);
  const toggle=async()=>{
    if(!data || busy) return;
    setBusy(true);
    try {
      const next=await request<Status>("/admin/ai/max-power/control/" + (data.enabled?"off":"on"),{method:"POST"});
      setData(next);setError("");
    } catch(e){setError(e instanceof Error?e.message:"No se pudo cambiar el estado");}
    finally{setBusy(false);}
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
  return <section className="max-power">
    <header className="max-power-header">
      <div><span className="max-power-eyebrow"><BrainCircuit size={14}/> APRENDIZAJE ADAPTATIVO</span>
        <h2>MAX POWER</h2>
        <p>Prueba automáticamente lo que puede verificar. Conserva cada resultado y explica por qué una mejora no se logró.</p>
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
        <div><strong>{data?.enabled?"MAX POWER encendido":"MAX POWER apagado"}</strong>
          <span>{data?.enabled ? (data.controller_online?"Controlador conectado":"En espera del controlador") : "Los resultados se mantienen guardados"}</span>
        </div>
      </div>
      <div className="max-power-pulse">
        <span className="max-power-stat"><Clock3 size={16}/> Tiempo activo <strong>{data?time(data.active_seconds):"—"}</strong></span>
        <span className="max-power-stat"><Activity size={16}/> Experimentos <strong>{data?f(data.experiments):"—"}</strong></span>
        <span className="max-power-stat"><ShieldCheck size={16}/> Casos examinados <strong>{data?f(data.examined_cases):"—"}</strong></span>
      </div>
    </div>
    {data && <div className="max-power-status">
      <span className={"max-power-dot" + (data.enabled && data.controller_online?" live":"")}/>
      <strong>{data.status.replaceAll("_"," ")}</strong>
      <span>{data.reason}</span>
    </div>}
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
