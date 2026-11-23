import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, BrainCircuit, Cpu, RefreshCw, ShieldCheck } from "lucide-react";
import { request } from "./api";
import "./fine-tune-progress.css";

type MetricPoint = {
  sequence: number; timestamp: string; kind: string; step: number; epoch?: number | null;
  loss?: number | null; eval_loss?: number | null; grad_norm?: number | null;
  cpu_memory_mb?: number | null;
  learning_rate?: number | null; gpu_memory_mb?: number | null;
  gpu_memory_reserved_mb?: number | null; elapsed_seconds?: number | null;
  train_samples_per_second?: number | null; holdout_loss_before?: number | null;
  preflight_ready?: boolean | null; host_free_mb?: number | null;
  cgroup_free_mb?: number | null; cgroup_limit_mb?: number | null;
  disk_free_mb?: number | null;
  holdout_loss_after?: number | null; holdout_pass_before?: number | null;
  holdout_pass_after?: number | null; holdout_regressions?: number | null;
};
type FineTuneRun = {
  run_id: string; model: string; dataset_sha256: string; stage: string;
  step: number; total_steps: number; percent: number | null;
  started_at: string; last_update_at: string; weights_trained: boolean;
  candidate_accepted: boolean; points: MetricPoint[];
};
type FineTuneStatus = {
  configured: boolean; source: string; refresh_seconds: number; runs: FineTuneRun[];
  cpu_preflight?: FineTuneRun | null;
  production_promoted: boolean; disclaimer: string;
};
type Metric = "loss" | "eval_loss" | "grad_norm" | "gpu_memory_mb" | "cpu_memory_mb" | "learning_rate";
const metrics: Array<{id:Metric; title:string; unit:string}> = [
  {id:"loss",title:"Pérdida de entrenamiento",unit:""},
  {id:"eval_loss",title:"Pérdida de validación",unit:""},
  {id:"grad_norm",title:"Norma del gradiente",unit:""},
  {id:"gpu_memory_mb",title:"Memoria GPU",unit:" MB"},
  {id:"cpu_memory_mb",title:"RAM del entrenamiento CPU",unit:" MB"},
  {id:"learning_rate",title:"Tasa de aprendizaje",unit:""},
];
const stageLabels: Record<string,string> = {
  preflight:"Revisión de recursos CPU", start:"Preparando entrenamiento", baseline:"Evaluando referencia", metric:"Actualizando pesos LoRA",
  eval:"Validando", checkpoint:"Checkpoint guardado", finished:"Entrenamiento terminado",
  failed:"Entrenamiento interrumpido", paused:"Pausado para proteger recursos", unknown:"Estado no verificable"
};
const fmt = (n:number|null|undefined,digits=3) =>
  typeof n==="number" && Number.isFinite(n) ? n.toLocaleString("es-CL",{maximumFractionDigits:digits}) : "—";

export default function FineTuneProgress(){
  const [data,setData]=useState<FineTuneStatus|null>(null);
  const [error,setError]=useState("");
  const [runId,setRunId]=useState("");
  const [metric,setMetric]=useState<Metric>("loss");
  const [selected,setSelected]=useState<number|null>(null);
  const [showConnect,setShowConnect]=useState(false);
  const [copyBusy,setCopyBusy]=useState(false);
  const [connectedMessage,setConnectedMessage]=useState("");
  const [preflightMessage,setPreflightMessage]=useState("");
  const refresh=useCallback(async()=>{
    try {
      const next=await request<FineTuneStatus>("/admin/ai/max-power/finetune");
      setData(next);setError("");
    }catch(e){setError(e instanceof Error?e.message:"Sin conexión al historial neuronal");}
  },[]);
  useEffect(()=>{
    void refresh();
    const timer=window.setInterval(()=>{if(!document.hidden)void refresh();},5000);
    const visible=()=>{if(!document.hidden)void refresh();};
    document.addEventListener("visibilitychange",visible);
    return ()=>{window.clearInterval(timer);document.removeEventListener("visibilitychange",visible);};
  },[refresh]);
  const run= data?.runs.find(x=>x.run_id===runId) ?? data?.runs[0];
  const lastPreflight=data?.cpu_preflight?.points.at(-1);
  const copyPreflight=async()=>{
    const command="cd /opt/galant-post\n"+
      "docker compose --env-file .env.preview -f docker-compose.preview.yml "+
      "--profile cpu-lora run --build --rm --no-deps cpu-lora --preflight";
    try{await navigator.clipboard.writeText(command);
      setPreflightMessage("Comando copiado. Ejecútalo en tu VPS; solo comprueba recursos, no entrena.");}
    catch{setPreflightMessage("No se pudo copiar. Abre la guía de CPU LoRA.");}
  };
  const samples=useMemo(()=>run?.points.filter(p=>typeof p[metric]==="number" && Number.isFinite(p[metric]))??[],[run,metric]);
  const values=samples.map(p=>p[metric] as number);
  const min=values.length?Math.min(...values):0, max=values.length?Math.max(...values):1;
  const spread=Math.max(1e-10,max-min);
  const coords=samples.map((p,i)=>({
    p, x:36+(samples.length===1?320:i*640/(samples.length-1)),
    y:164-((p[metric] as number)-min)/spread*128,
  }));
  const line=coords.map(({x,y})=>x.toFixed(1)+","+y.toFixed(1)).join(" ");
  const current=selected==null?coords[coords.length-1]:coords.find(p=>p.p.sequence===selected);
  const lastUpdate=run?.last_update_at?new Date(run.last_update_at).getTime():0;
  const stale=!!run && !["finished","failed","paused"].includes(run.stage) && Date.now()-lastUpdate>60000;
  const cpuRun=run?.model==="Qwen/Qwen3.5-0.8B";
  const lastBy=(key:keyof MetricPoint):number|null=>{
    for(const p of [...(run?.points||[])].reverse()){
      const value=p[key];
      if(typeof value==="number" && Number.isFinite(value))return value;
    }
    return null;
  };
  const copyConnection=async()=>{
    if(copyBusy)return;
    setCopyBusy(true);setConnectedMessage("");
    try{
      const credentials=await request<{organization_id:string;telemetry_token:string}>(
        "/admin/ai/max-power/finetune/token",{method:"POST"});
      const text=[
        "GALANT_FINETUNE_TELEMETRY_TOKEN="+credentials.telemetry_token,
        "GALANT_FINETUNE_ORG="+credentials.organization_id,
        "GALANT_FINETUNE_TELEMETRY_URL="+window.location.origin+"/api/v1/admin/ai/max-power/finetune/telemetry"
      ].join("\n");
      await navigator.clipboard.writeText(text);
      setConnectedMessage("Credenciales copiadas. Utilízalas solo en el equipo de entrenamiento autorizado.");
    }catch(e){setConnectedMessage(e instanceof Error?e.message:"No se pudo copiar la conexión");}
    finally{setCopyBusy(false);}
  };
  return <section className="ft-panel" aria-label="Entrenamiento neuronal Qwen">
    <div className="ft-heading">
      <div><span className="ft-eyebrow"><BrainCircuit size={15}/> CPU LORA · GPU QLORA</span>
        <h3>Entrenamiento real de pesos</h3>
        <p>Métricas de entrenamiento de pesos en trabajador aislado. Qwen3.5 4B de Messenger permanece intacto.</p></div>
      <button type="button" className="ft-refresh" onClick={()=>void refresh()} title="Actualizar ahora"><RefreshCw size={17}/></button>
    </div>
    {error && <p role="alert" className="ft-error">{error}</p>}
    {!data?.configured && <p className="ft-warning">Canal de métricas sin configurar. Para entrenar con el VPS actual existe una opción LoRA por CPU aislada (Qwen3.5 0.8B), sujeta a autorización de datos y memoria disponible. MAX POWER local por sí solo todavía no modifica pesos.</p>}
    {data?.configured && <div className="ft-connect">
      <button type="button" onClick={()=>setShowConnect(x=>!x)}>
        <ShieldCheck size={16}/> {showConnect?"Ocultar conexión":"Vincular entrenamiento CPU/GPU"}
      </button>
      {showConnect && <div className="ft-connect-details">
        <p>Solo el administrador puede generar la credencial por organización. Guárdala en el trabajador aislado, nunca en GitHub.</p>
        <button type="button" disabled={copyBusy} onClick={()=>void copyConnection()}>
          {copyBusy?"Generando…":"Copiar credenciales de entrenamiento"}
        </button>
        {connectedMessage && <span role="status">{connectedMessage}</span>}
      </div>}
    </div>}
    <div className="ft-heldout" aria-label="Comprobación CPU LoRA">
      <strong>Capacidad del VPS para entrenar Qwen3.5 0.8B</strong>
      <span>{lastPreflight
        ? lastPreflight.preflight_ready
          ? "Última comprobación: recursos iniciales suficientes; no significa que los pesos ya se hayan entrenado."
          : "Última comprobación: recursos insuficientes; no iniciar entrenamiento."
        : "Sin comprobación de recursos registrada. El entrenamiento continúa desactivado."}</span>
      {lastPreflight && <span>
        RAM del servidor libre: {fmt(lastPreflight.host_free_mb,0)} MB ·
        RAM disponible en contenedor: {fmt(lastPreflight.cgroup_free_mb,0)} MB ·
        Disco libre: {fmt(lastPreflight.disk_free_mb,0)} MB
      </span>}
      <button type="button" className="ft-refresh" onClick={()=>void copyPreflight()}>
        <Cpu size={16}/> Copiar comprobación del VPS
      </button>
      {preflightMessage && <small role="status">{preflightMessage}</small>}
      <small>Esta orden puede construir la imagen opcional y descargar dependencias. No ejecuta gradientes.
        Para mostrar resultados aquí, conecta antes la telemetría y ejecuta el preflight con sus parámetros HTTPS.
        No se emplean datos de Messenger.</small>
    </div>
    {(!data?.runs.length) ? <div className="ft-empty"><Cpu size={28}/>
      <strong>Sin pasos de entrenamiento neuronal registrados</strong>
      <p>Cuando el trabajador CPU o GPU entrene con datos autorizados y reporte por HTTPS, aparecerán la pérdida, los pasos, los checkpoints y la validación.</p>
      </div> : <>
      <div className="ft-run-select">
        <label htmlFor="ft-run">Ejecución</label>
        <select id="ft-run" value={run?.run_id??""} onChange={e=>{setRunId(e.target.value);setSelected(null);}}>
          {data.runs.map(x=><option key={x.run_id} value={x.run_id}>
            {x.run_id.slice(0,8)} · {stageLabels[x.stage]??x.stage}</option>)}
        </select>
      </div>
      <div className="ft-status-line">
        <span className={"ft-led"+(!stale && run?.stage!=="finished"?" active":"")}/>
        <strong>{stageLabels[run?.stage||"unknown"]??"No verificable"}</strong>
        <span>{stale?"Señal detenida o sin conexión":run?.stage==="finished"?"Resultado guardado":run?.stage==="paused"?"Pausado por recursos":run?.stage==="failed"?"Interrumpido":"Actualiza cada 5 segundos"}</span>
      </div>
      <div className="ft-progress-label">
        <strong>{fmt(run?.percent,1)}{run?.percent!=null?"%":""}</strong>
        <span>{fmt(run?.step,0)} / {fmt(run?.total_steps,0)} pasos de optimización</span>
      </div>
      <div className="ft-progress-track" role="progressbar" aria-label="Pasos reales de entrenamiento"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={run?.percent??0}>
        <div style={{width:(run?.percent??0)+"%"}}/>
      </div>
      <div className="ft-kpis">
        <div><span>Pérdida entrenamiento</span><strong>{fmt(lastBy("loss"))}</strong></div>
        <div><span>Pérdida validación</span><strong>{fmt(lastBy("eval_loss"))}</strong></div>
        <div><span>{cpuRun?"RAM CPU medida":"Memoria GPU medida"}</span><strong>{fmt(lastBy(cpuRun?"cpu_memory_mb":"gpu_memory_mb"),0)} MB</strong></div>
        <div><span>Checkpoint / época</span><strong>{fmt(lastBy("epoch"),1)}</strong></div>
      </div>
      <div className="ft-chart-header">
        <div><Activity size={17}/> <strong>Gráfico interactivo</strong></div>
        <div className="ft-chart-tabs" role="group" aria-label="Elegir medición">
          {metrics.map(x=><button type="button" key={x.id} className={metric===x.id?"current":""}
            onClick={()=>{setMetric(x.id);setSelected(null);}}>{x.title}</button>)}
        </div>
      </div>
      {coords.length ? <>
        <svg className="ft-chart" viewBox="0 0 710 194" role="img"
          aria-label={metrics.find(m=>m.id===metric)?.title+" por paso de optimización"}>
          {[36,100,164].map(y=><line key={y} x1={36} y1={y} x2={680} y2={y} stroke="currentColor" opacity=".1"/>)}
          <text x="32" y="26" fontSize="12" fill="currentColor" textAnchor="end">{fmt(max)}</text>
          <text x="32" y="168" fontSize="12" fill="currentColor" textAnchor="end">{fmt(min)}</text>
          <polyline points={line} fill="none" stroke="#42a98e" strokeWidth="2.7" strokeLinejoin="round"/>
          {coords.map(({x,y,p})=><circle key={p.sequence} cx={x} cy={y}
            r={p.sequence===current?.p.sequence?6:4} fill="#42a98e" stroke="currentColor"
            strokeWidth={p.sequence===current?.p.sequence?1.5:0}
            onMouseEnter={()=>setSelected(p.sequence)}
            onFocus={()=>setSelected(p.sequence)} tabIndex={0}
            role="button" aria-label={"Paso "+p.step+"; "+fmt(p[metric] as number)}/>)}
          <text x="38" y="186" fontSize="11" fill="currentColor">Paso {samples[0]?.step}</text>
          <text x="680" y="186" fontSize="11" fill="currentColor" textAnchor="end">Paso {samples.at(-1)?.step}</text>
        </svg>
        <div className="ft-hover" aria-live="polite">
          <strong>Paso {current?.p.step ?? "—"}</strong>
          <span>{metrics.find(m=>m.id===metric)?.title}: {fmt(current?.p[metric] as number)}{metrics.find(m=>m.id===metric)?.unit}</span>
          <small>Época {fmt(current?.p.epoch,2)} · {current?.p.timestamp?new Date(current.p.timestamp).toLocaleString("es-CL"):"—"}</small>
        </div>
      </> : <p className="ft-warning">Aún no hay mediciones de esta serie. No se generan valores de demostración.</p>}
      <div className="ft-heldout">
        <strong>Comprobación con datos reservados</strong>
        <span>Pérdida antes: {fmt(lastBy("holdout_loss_before"))} · Después: {fmt(lastBy("holdout_loss_after"))}</span>
        <span>Aciertos antes: {fmt(lastBy("holdout_pass_before"),0)} · Después: {fmt(lastBy("holdout_pass_after"),0)} · Regresiones: {fmt(lastBy("holdout_regressions"),0)}</span>
        <span>{run?.weights_trained ? (run.candidate_accepted?"Adaptador candidato aprobado en laboratorio":"Pesos LoRA entrenados; candidato no aprobado"):"Sin entrenamiento de pesos concluido"}</span>
        <small>Producción intacta. Los adaptadores no se publican automáticamente.</small>
      </div>
    </>}
    <p className="ft-disclaimer">{data?.disclaimer??"La calidad solo puede evaluarse con pruebas independientes verificadas."}</p>
  </section>;
}
