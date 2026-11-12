import {useCallback, useEffect, useState} from "react";
import {CheckCircle2, Eye, FileText, LogOut, ShieldCheck, AlertTriangle} from "lucide-react";
import {request} from "./api";
import "./javiera-review-v17.css";

type ReviewDraft={id:string;code:string;sheet:string;revision:number;specialty:string;
  checks:string[];regulatory_basis:string;source_sha256:string};
type Queue={authorized:boolean;scopes?:string[];documents:ReviewDraft[];message:string};
type VisualBlock={id:number;text:string;reviewed:boolean};
type VisualImage={id:number;title:string;anchor_row:number|null;data_uri:string;sha256:string};
type VisualReview={id:string;revision:number;title:string;reason:string;source_layout_status:string;
  images:VisualImage[];blocks:VisualBlock[]};
type VisualQueue={authorized:boolean;items:VisualReview[];warning?:string};
const IRL_CHECKS=[
  "riesgos_reales_de_la_actividad","matriz_y_medidas_de_control",
  "puestos_sustancias_y_entorno","eventos_capacitaciones_y_epp",
  "coherencia_con_ds44",
];
const IRL_BASIS="D.S. 44, artículos 7 y 15; https://www.bcn.cl/leychile/navegar?idNorma=1205298";
const pretty=(value:string)=>value.replaceAll("_"," ").replace(/^./,x=>x.toUpperCase());
export default function JavieraReviewerV17({onLogout}:{onLogout:()=>void}){
  const [queue,setQueue]=useState<Queue|null>(null);
  const [visualQueue,setVisualQueue]=useState<VisualQueue|null>(null);
  const [visualCheck,setVisualCheck]=useState<Record<string,boolean>>({});
  const [visualComments,setVisualComments]=useState("");
  const [visualVerdict,setVisualVerdict]=useState<"approved"|"rejected">("approved");
  const [activeId,setActiveId]=useState("");
  const [check,setCheck]=useState<Record<string,boolean>>({});
  const [comments,setComments]=useState("");
  const [verdict,setVerdict]=useState<"approved"|"rejected">("approved");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const load=useCallback(async()=>{
    const next=await request<Queue>("/javiera/v17/review/queue");
    // Revisores sólo laborales no deben pedir imágenes preventivas; para
    // revisores preventivos, no ocultar un error del servidor como cola vacía.
    const visual=next.scopes?.includes("prevencion")
      ?await request<VisualQueue>("/javiera/v195/irl-blocks/review-queue")
      :{authorized:false,items:[]};
    setQueue(next);setVisualQueue(visual);
    setActiveId(old=>next.documents.some(x=>x.id===old)?old:next.documents[0]?.id||"");
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
  async function decideVisual(item:VisualReview){
    setBusy(true);setError("");setNotice("");
    try{
      await request("/javiera/admin/reviews/signoff",{
        method:"POST",body:JSON.stringify({
          resource_kind:"template",resource_id:item.id,specialty:"prevencion",
          verdict:visualVerdict,
          checklist:Object.fromEntries(IRL_CHECKS.map(key=>[key,!!visualCheck[key]])),
          comments:visualComments,regulatory_basis:IRL_BASIS,
        }),
      });
      setNotice("Acta del IRL registrada. El administrador podrá publicar solo después de las demás aprobaciones.");
      setVisualCheck({});setVisualComments("");
      await load();
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
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
        <div><span>Pendientes asignados</span><b>{queue.documents.length+(visualQueue?.items.length||0)}</b></div>
        <div><span>Especialidades autorizadas</span><b>{queue.scopes?.map(x=>x==="laboral"?"Laboral":"Prevención").join(" y ")||"Sin alcance"}</b></div>
      </div>
      {!queue.documents.length&&!visualQueue?.items.length?<section className="j17-review-panel">
        <CheckCircle2 size={28}/><h2>No hay versiones pendientes para revisar</h2>
        <p>Los nuevos borradores aparecerán aquí cuando una persona distinta de ti los importe o modifique.</p>
      </section>:queue.documents.length>0?<div className="j17-review-body">
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
      </div>:null}
      {visualQueue?.warning&&<p className="j17-review-error">{visualQueue.warning}</p>}
      {visualQueue?.items.map(item=><section className="j17-review-panel j17-irl-editorial" key={item.id}>
        <h2>{item.title} · Revisión {item.revision}</h2>
        <p>Compara las cinco imágenes originales con el texto que se propone convertir
          en HTML. La aprobación es personal y no puede efectuarla el autor.</p>
        {item.source_layout_status!=="approved"&&<p className="j17-review-source">
          El Excel fuente aún requiere aprobación. Puedes revisar la transcripción,
          pero el administrador no podrá publicarla hasta que apruebe también el formato original.
        </p>}
        {item.images.map(image=>{
          const block=item.blocks.find(x=>x.id===image.id);
          return <section className="j17-irl-block" key={image.sha256}>
            <h3>{image.id}. {image.title} · Fila {image.anchor_row}</h3>
            <div className="j17-irl-columns">
              <figure><img src={image.data_uri} alt={image.title}/><figcaption>Fuente Excel original</figcaption></figure>
              <div><strong>Transcripción a revisar</strong>
                <pre>{block?.text||"Sin transcripción"}</pre>
                <p className="j17-review-source">{block?.reviewed?
                  "Marcado como cotejado por el autor; requiere tu verificación independiente.":
                  "El autor todavía no ha marcado este bloque como cotejado."}</p>
              </div>
            </div>
          </section>;
        })}
        <h3>Acta independiente de prevención</h3>
        {IRL_CHECKS.map(key=><label className="j17-review-check" key={key}>
          <input type="checkbox" checked={!!visualCheck[key]}
            onChange={e=>setVisualCheck(old=>({...old,[key]:e.target.checked}))}/>
          <span>{pretty(key)}</span>
        </label>)}
        <label className="j17-review-field">Decisión
          <select value={visualVerdict} onChange={e=>setVisualVerdict(e.target.value as "approved"|"rejected")}>
            <option value="approved">Aprobar después del cotejo</option>
            <option value="rejected">Rechazar y devolver al autor</option>
          </select>
        </label>
        <label className="j17-review-field">Fundamento y observaciones
          <textarea rows={5} value={visualComments}
            onChange={e=>setVisualComments(e.target.value)}
            placeholder="Indica las diferencias encontradas y evidencia de tu revisión (mínimo 40 caracteres)."/>
        </label>
        <button className="j17-review-submit" disabled={busy||visualComments.trim().length<40||
          (visualVerdict==="approved"&&(!IRL_CHECKS.every(key=>visualCheck[key])||
            !item.blocks.every(block=>block.reviewed)))}
          onClick={()=>void decideVisual(item)}>
          <ShieldCheck size={17}/> {busy?"Registrando...":
            visualVerdict==="approved"?"Registrar aprobación preventiva":"Registrar rechazo y observaciones"}
        </button>
      </section>)}
    </>}
  </main>;
}
