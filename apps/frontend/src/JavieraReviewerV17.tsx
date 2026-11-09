import {useCallback, useEffect, useState} from "react";
import {CheckCircle2, Eye, FileText, LogOut, ShieldCheck, AlertTriangle} from "lucide-react";
import {request} from "./api";
import "./javiera-review-v17.css";

type ReviewDraft={id:string;code:string;sheet:string;revision:number;specialty:string;
  checks:string[];regulatory_basis:string;source_sha256:string};
type Queue={authorized:boolean;scopes?:string[];documents:ReviewDraft[];message:string};
const pretty=(value:string)=>value.replaceAll("_"," ").replace(/^./,x=>x.toUpperCase());
export default function JavieraReviewerV17({onLogout}:{onLogout:()=>void}){
  const [queue,setQueue]=useState<Queue|null>(null);
  const [activeId,setActiveId]=useState("");
  const [check,setCheck]=useState<Record<string,boolean>>({});
  const [comments,setComments]=useState("");
  const [verdict,setVerdict]=useState<"approved"|"rejected">("approved");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const load=useCallback(async()=>{
    const next=await request<Queue>("/javiera/v17/review/queue");
    setQueue(next);setActiveId(old=>next.documents.some(x=>x.id===old)?old:next.documents[0]?.id||"");
  },[]);
  useEffect(()=>{void load().catch(e=>setError(e instanceof Error?e.message:String(e)));},[load]);
  const active=queue?.documents.find(x=>x.id===activeId);
  const allChecked=!!active&&active.checks.every(key=>check[key]);
  async function decide(){
    if(!active)return;
    setBusy(true);setError("");setNotice("");
    try{
      const result=await request<{message:string}>("/javiera/v17/review/layouts/"+
        active.id+"/decision",{method:"POST",body:JSON.stringify({
          expected_revision:active.revision,verdict,
          checklist:Object.fromEntries(active.checks.map(key=>[key,!!check[key]])),
          comments,
        })});
      setNotice(result.message);
      setCheck({});setComments("");
      await load();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  return <main className="j17-review">
    <header><div><small>GALANT 17 · REVISIÓN DOCUMENTAL</small>
      <h1>Mesa de revisión</h1>
      <p>Solo puedes revisar plantillas para las que tengas designación. No tienes acceso a la base operativa de GALANT.</p>
    </div><button className="j17-review-logout" onClick={onLogout}><LogOut size={16}/> Cerrar sesión</button></header>
    {error&&<p className="j17-review-error" role="alert"><AlertTriangle size={17}/>{error}</p>}
    {notice&&<p className="j17-review-notice" role="status"><CheckCircle2 size={17}/>{notice}</p>}
    {!queue&&<p>Consultando tu designación y los documentos pendientes…</p>}
    {queue&&!queue.authorized&&<section className="j17-review-panel">
      <ShieldCheck size={25}/><h2>Aún no tienes una especialidad autorizada</h2>
      <p>{queue.message}</p><p>Solicita al administrador que registre tu designación laboral o de prevención.</p>
    </section>}
    {queue?.authorized&&<>
      <div className="j17-review-metrics">
        <div><span>Pendientes asignados</span><b>{queue.documents.length}</b></div>
        <div><span>Especialidades autorizadas</span><b>{queue.scopes?.map(x=>x==="laboral"?"Laboral":"Prevención").join(" y ")||"Sin alcance"}</b></div>
      </div>
      {!queue.documents.length?<section className="j17-review-panel">
        <CheckCircle2 size={28}/><h2>No hay versiones pendientes para revisar</h2>
        <p>Los nuevos borradores aparecerán aquí cuando una persona distinta de ti los importe o modifique.</p>
      </section>:<div className="j17-review-body">
        <aside className="j17-review-list">
          <h2>Plantillas pendientes</h2>
          {queue.documents.map(item=><button key={item.id}
            className={activeId===item.id?"selected":""}
            onClick={()=>{setActiveId(item.id);setCheck({});setComments("");setVerdict("approved");}}>
            <FileText size={16}/><span><b>{item.sheet}</b><small>Revisión {item.revision} · {item.specialty==="laboral"?"Laboral":"Prevención"}</small></span>
          </button>)}
        </aside>
        {active&&<section className="j17-review-panel">
          <h2>{active.sheet}</h2>
          <p>Versión {active.revision} · Consulta primero la vista previa con datos de prueba.
            Verifica contenido, condiciones y campos antes de registrar tu decisión.</p>
          <a className="j17-review-preview" target="_blank" rel="noreferrer"
            href={"/api/v1/javiera/v17/review/layouts/"+active.id+"/preview"}>
            <Eye size={17}/> Abrir vista previa PDF
          </a>
          <h3>Comprobación profesional</h3>
          {active.checks.map(key=><label className="j17-review-check" key={key}>
            <input type="checkbox" checked={!!check[key]} onChange={e=>setCheck(old=>({...old,[key]:e.target.checked}))}/>
            <span>{pretty(key)}</span></label>)}
          <p className="j17-review-source">Referencia registrada: {active.regulatory_basis}</p>
          <label className="j17-review-field">Conclusión
            <select value={verdict} onChange={e=>setVerdict(e.target.value as "approved"|"rejected")}>
              <option value="approved">Aprobar tras revisar efectivamente</option>
              <option value="rejected">Observar y devolver al autor</option>
            </select></label>
          <label className="j17-review-field">Fundamento y evidencia de tu revisión
            <textarea rows={5} value={comments} onChange={e=>setComments(e.target.value)}
              placeholder="Indica qué revisaste, cómo lo comprobaste y qué observaciones corresponden (mínimo 40 caracteres)."/>
          </label>
          <button className="j17-review-submit" disabled={busy||comments.trim().length<40||
             (verdict==="approved"&&!allChecked)} onClick={()=>void decide()}>
            <ShieldCheck size={17}/> {busy?"Registrando revisión…":
             verdict==="approved"?"Registrar revisión y publicar":"Registrar observaciones"}
          </button>
          <p className="j17-review-source">Publicar una plantilla no acredita que una persona haya firmado, recibido EPP o participado en una inducción.</p>
        </section>}
      </div>}
    </>}
  </main>;
}
