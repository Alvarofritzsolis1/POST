import { useCallback, useEffect, useState } from "react";
import { BrainCircuit, Play, Square } from "lucide-react";
import { request } from "./api";
import FineTuneProgress from "./FineTuneProgress";

const path = "/admin/ai/max-power";
type State = {enabled:boolean; qwen_only:boolean; reason:string; cpu_learning?: {
  status:string; reason:string; manager_online:boolean; last_update_at:string|null;
}};

export default function QwenExclusiveTraining(){
  const [data,setData] = useState<State|null>(null);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [history,setHistory] = useState(false);
  const refresh = useCallback(async (signal?:AbortSignal) => {
    try {
      const result = await request<State>(path,{signal});
      if(!signal?.aborted) setData(result);
    } catch(e) {
      if(!signal?.aborted) setError(e instanceof Error?e.message:"No se pudo consultar el entrenador");
    }
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    void refresh(controller.signal);
    const timer=window.setInterval(()=>{if(!document.hidden)void refresh(controller.signal)},5000);
    return ()=>{controller.abort();window.clearInterval(timer)};
  },[refresh]);
  const active=!!data?.enabled && data.qwen_only;
  const other=!!data?.enabled && !data.qwen_only;
  async function toggle(){
    if(busy||!data||other)return;
    setBusy(true);setError("");
    try{
      const result=await request<State>(path+"/control/"+(active?"qwen-off":"qwen-on"),{method:"POST"});
      setData(result);
    }catch(e){setError(e instanceof Error?e.message:"No se pudo cambiar el estado")}
    finally{setBusy(false)}
  }
  return <section className="qwen-exclusive" aria-label="Entrenamiento exclusivo Qwen">
    <div><h3><BrainCircuit size={18} aria-hidden="true"/> Qwen 3.5 2B · entrenamiento exclusivo</h3>
      <p>LoRA supervisado con casos sintéticos difíciles y respuestas estructuradas. Sin prácticas de fichas ni modificación del modelo de producción.</p></div>
    <div className="qwen-exclusive-actions">
      <button className="qwen-start" type="button" disabled={!data||busy||other} onClick={()=>void toggle()}>
        {active?<Square size={16}/>:<Play size={16}/>}
        {busy?"Procesando…":active?"Detener entrenamiento":"Iniciar entrenamiento"}
      </button>
      <span role="status" className="qwen-exclusive-status">{!data?"Consultando estado…":other?"Detén MAX POWER antes de iniciar":active?
        (data.cpu_learning?.manager_online?data.cpu_learning.reason:"Solicitud activa; esperando supervisor neuronal"):
        "Entrenamiento exclusivo apagado"}</span>
    </div>
    {error&&<p role="alert" className="messenger-lab-error">{error}</p>}
    <p>El inicio solicita un turno de entrenamiento; los pesos solo se consideran modificados con evidencia del optimizador. Si faltan recursos, el supervisor espera.</p>
    <button type="button" className="messenger-lab-inspect" aria-expanded={history} onClick={()=>setHistory(x=>!x)}>
      {history?"Ocultar métricas":"Ver métricas e historial de pesos"}
    </button>
    {history&&<FineTuneProgress/>}
  </section>
}
