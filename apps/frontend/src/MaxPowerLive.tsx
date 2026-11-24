import { useEffect, useState } from "react";
import { Activity, BrainCircuit } from "lucide-react";
import { request } from "./api";

type Point = { at:string; baseline?:number|null; candidate?:number|null; delta?:number|null;
  observed_baseline?:number; observed_candidate?:number; pairs?:number; gains?:number|null; regressions?:number|null; net_cases?:number;
  total_seconds?:number; prompt_seconds?:number; generation_seconds?:number; load_seconds?:number; phase?:string; preliminary?:boolean; safety_regressions?:number; lab_verified?:boolean; host_cpu_percent?:number;
  host_ram_mb?:number; available_ram_mb?:number; worker_ram_mb?:number; disk_free_mb?:number };
type History = {at:string; general:Point[]; messenger:Point[]; resources:Point[]; synthetic_4b?:Point[]; latency_4b?:Point[]};
type Series = {label:string; color:string; value:(p:Point)=>number|null|undefined};
const fmt = (v:number|null|undefined, digits=1) => v == null ? "—" : v.toLocaleString("es-CL",{maximumFractionDigits:digits});
const stamp = (s:string) => new Date(s).toLocaleString("es-CL",{timeZone:"America/Santiago",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
const signed = (n:number|null|undefined) => n == null ? "—" : (n>0?"+":"")+fmt(n);
const passSeries:Series[] = [
  {label:"Referencia",color:"#64748b",value:p=>p.baseline},
  {label:"Candidata",color:"#087d75",value:p=>p.candidate}
];
const observedSeries:Series[] = [
  {label:"Referencia observada",color:"#64748b",value:p=>p.observed_baseline??p.baseline},
  {label:"Candidata observada",color:"#087d75",value:p=>p.observed_candidate??p.candidate}
];
const resourceSeries:Series[] = [
  {label:"CPU",color:"#087d75",value:p=>p.host_cpu_percent},
  {label:"RAM usada (host)",color:"#5868bb",value:p=>p.host_ram_mb && p.available_ram_mb!=null ? 100*(1-p.available_ram_mb/p.host_ram_mb):null}
];
const latencySeries:Series[] = [
  {label:"Contexto",color:"#d97706",value:p=>p.prompt_seconds},
  {label:"Generación",color:"#087d75",value:p=>p.generation_seconds},
  {label:"Total",color:"#5868bb",value:p=>p.total_seconds}
];
const resultSeries:Series[] = [
  {label:"Ganancias",color:"#087d75",value:p=>p.gains},
  {label:"Regresiones",color:"#b54b43",value:p=>p.regressions}
];

function Plot({points,series,unit="",bounds}:{points:Point[];series:Series[];unit?:string;bounds?:[number,number]}){
  const [selected,setSelected]=useState<number|null>(null);
  const values = points.flatMap(p=>series.map(s=>s.value(p))).filter((n):n is number=>typeof n==="number"&&Number.isFinite(n));
  if (!values.length) return <p className="mp-chart-empty">Sin mediciones suficientes. No se generan puntos de demostración.</p>;
  const times=points.map(p=>Date.parse(p.at));
  const start=times[0], end=times.at(-1)??start;
  const low=bounds?.[0]??Math.min(0,...values);
  const high=bounds?.[1]??Math.max(low+1,...values);
  const x=(i:number)=>end===start?342:52+580*(times[i]-start)/(end-start);
  const y=(n:number)=>174-150*(n-low)/Math.max(high-low,1);
  const index=selected!==null&&selected<points.length?selected:points.length-1;
  const current=points[index];
  return <div className="mp-chart">
    <div className="mp-chart-legend">{series.map(s=><span key={s.label}><i style={{background:s.color}}/>{s.label}</span>)}</div>
    <svg viewBox="0 0 650 206" role="img" aria-label={series.map(s=>s.label).join(" y ")+" · mediciones registradas"}>
      {[0,.25,.5,.75,1].map(f=>{const n=low+(high-low)*f;return <g key={f}>
        <line x1="52" x2="632" y1={y(n)} y2={y(n)} stroke="#e1e9e7"/>
        <text x="45" y={y(n)+4} textAnchor="end" fontSize="10" fill="currentColor">{fmt(n,0)}{unit}</text>
      </g>})}
      {series.map(s=>{
        const groups:Array<Array<{i:number;n:number}>>=[];
        let group:Array<{i:number;n:number}>=[];
        points.forEach((p,i)=>{const n=s.value(p);
          // Do not bridge missing readings or long resource sampling gaps.
          if (n==null || !Number.isFinite(n) || (unit==="%" && series===resourceSeries && i>0 && times[i]-times[i-1]>180000)){
            if(group.length)groups.push(group);group=[];
          }
          if(n!=null&&Number.isFinite(n))group.push({i,n});
        });
        if(group.length)groups.push(group);
        return <g key={s.label}>{groups.map((g,j)=><polyline key={j} points={g.map(({i,n})=>x(i)+","+y(n)).join(" ")} stroke={s.color} strokeWidth="2" fill="none"/>)}
          {groups.flat().map(({i,n})=><circle key={i} cx={x(i)} cy={y(n)} r={points.length>100?1.8:3.5} fill={s.color}><title>{stamp(points[i].at)} · {s.label}: {fmt(n)}{unit}</title></circle>)}</g>;
      })}
      <text x="52" y="198" fontSize="10" fill="currentColor">{stamp(points[0].at)}</text>
      <text x="632" y="198" textAnchor="end" fontSize="10" fill="currentColor">{stamp(points.at(-1)!.at)}</text>
    </svg>
    <label className="mp-chart-select">Consultar punto <select value={index} onChange={e=>setSelected(Number(e.target.value))}>
      {points.map((p,i)=><option key={i} value={i}>{stamp(p.at)} · #{i+1}{p.phase?" · "+p.phase:""}</option>)}
    </select></label>
    {current&&<div className="mp-chart-values">{series.map(s=><span key={s.label}>{s.label}: <b>{fmt(s.value(current))}{s.value(current)==null?"":unit}</b></span>)}
      {current.pairs!=null&&<span>Pares: <b>{current.pairs}</b></span>}
      {current.preliminary&&<span>Muestra preliminar; sin calificación validada</span>}
      {current.lab_verified===true&&<span>Validación de laboratorio superada</span>}
    </div>}
  </div>;
}
export default function MaxPowerLive({resources}:{resources?:Record<string,number|null>}){
  const [data,setData]=useState<History|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    let mounted=true;let timer:number;let controller:AbortController;
    async function refresh(){
      controller=new AbortController();
      try{
        const next=await request<History>("/admin/ai/max-power/live/history",{signal:controller.signal});
        if(mounted){setData(next);setError("");}
      }catch(e){if(mounted&&!controller.signal.aborted)setError(e instanceof Error?e.message:"Sin conexión con las mediciones");}
      finally{if(mounted)timer=window.setTimeout(refresh,15000);}
    }
    void refresh();
    return()=>{mounted=false;controller?.abort();window.clearTimeout(timer);};
  },[]);
  const messenger=data?.messenger??[], general=data?.general??[];
  const lastM=messenger.at(-1),lastG=general.at(-1);
  return <section className="max-power-card mp-live-evidence" aria-label="Evolución de conocimiento medido">
    <div className="max-power-section-title"><BrainCircuit size={20}/><h3>Conocimiento medido · en vivo</h3></div>
    <p>El progreso se registra con comparaciones A/B terminadas. Entrenar más pasos no aumenta automáticamente la calificación. Los resultados son del laboratorio, no una nota de producción ni de IQ.</p>
    {error&&<p role="alert">Última lectura conservada: {error}</p>}
    <div className="mp-evidence-kpis">
      <div><small>Messenger · diferencia A/B</small><strong>{signed(lastM?.delta)}{lastM?.delta!=null?" pts":""}</strong><span>{lastM?.pairs??0} controles distintos en la ventana</span></div>
      <div><small>General · última diferencia A/B</small><strong>{signed(lastG?.delta)}{lastG?.delta!=null?" pts":""}</strong><span>{lastG?.pairs??0} pares reservados</span></div>
      <div><small>Messenger · saldo observado</small><strong>{signed(lastM?.net_cases)}</strong><span>{lastM?.gains??0} ganancias · {lastM?.regressions??0} regresiones</span></div>
    </div>
    <div className="mp-evidence-grid">
      <article><h4>Qwen 4B · práctica reservada sintética</h4><Plot points={data?.synthetic_4b??[]} series={passSeries} bounds={[0,100]} unit="%"/><p>Observación preliminar desde el primer par. Solo casos de laboratorio reservados; no implica cambios de pesos ni mejora productiva.</p></article>
      <article><h4>Qwen 4B · duración real de inferencia</h4><Plot points={data?.latency_4b??[]} series={latencySeries} unit=" s"/><p>Duración registrada de cada respuesta, no estimaciones. Contexto y generación se muestran por separado.</p></article>
      <article><h4>Messenger · comprensión y controles reales</h4><Plot points={messenger} series={observedSeries} bounds={[0,100]} unit="%"/><p>Observaciones desde el primer control, preliminares hasta 8 controles distintos. La diferencia validada permanece sin nota hasta ese mínimo. No mide toda la conversación.</p></article>
      <article><h4>Galancito General · exactitud de casos reservados</h4><Plot points={general} series={passSeries} bounds={[0,100]} unit="%"/><p>Cada punto es una ronda completa con un conjunto distinto. Las rondas pueden tener diferente dificultad; el cambio válido es entre las dos variantes de cada punto.</p></article>
      <article><h4>Messenger · mejoras y regresiones observadas</h4><Plot points={messenger} series={resultSeries}/><p>{lastM?.safety_regressions??0} regresiones de seguridad registradas en esta ventana. No se consideran pesos promovidos.</p></article>
      <article><h4><Activity size={15}/> Recursos del servidor</h4><Plot points={data?.resources??[]} series={resourceSeries} bounds={[0,100]} unit="%"/>
        <div className="mp-chart-values"><span>CPU actual: <b>{fmt(resources?.host_cpu_percent)}%</b></span><span>RAM libre: <b>{fmt(resources?.available_ram_mb,0)} MB</b></span><span>Disco libre: <b>{fmt(resources?.disk_free_mb,0)} MB</b></span></div>
        <p>Historial persistente de 24 h, una muestra por minuto mientras MAX POWER está encendido. Lectura actual del controlador, si está disponible.</p>
      </article>
    </div>
    <small>{data?"Última consulta: "+stamp(data.at)+" · actualización cada 15 s":"Consultando evidencia registrada…"}</small>
  </section>;
}
