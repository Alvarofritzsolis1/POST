import {useEffect,useMemo,useState} from "react";
import {CheckCircle2,FileText,Save,ShieldCheck,Upload} from "lucide-react";
import {request} from "./api";
import "./javiera-irl-visual-blocks.css";

type ImageItem={order:number;title:string;data_uri:string;sha256:string;anchor_row:number|null};
type Source={available:boolean;status?:string;source_sha256?:string;images:ImageItem[]};
type Block={id:number;text:string;reviewed:boolean};
type Data={
  source_sha256:string;source_layout_status:string;image_hashes:string[];titles:string[];
  latest:{id:string|null;revision:number|null;status:string;blocks:Block[];
    source_matches:boolean;preventive_verdict:"pending"|"approved"|"rejected";
    author_is_current_user:boolean;can_publish:boolean;
    preventive_authorization_valid:boolean};
  approved_revision:number|null;approved_source_matches:boolean;
};
const checklist=[
  ["riesgos_reales_de_la_actividad","Riesgos correspondientes a las actividades reales"],
  ["matriz_y_medidas_de_control","Medidas preventivas y matriz revisadas"],
  ["puestos_sustancias_y_entorno","Puesto, sustancias y HDS revisados"],
  ["eventos_capacitaciones_y_epp","EPP, procedimientos y capacitación revisados"],
  ["coherencia_con_ds44","Contenido cotejado con DS 44 y Excel de referencia"],
] as const;
const basis="D.S. 44, artículos 7 y 15; https://www.bcn.cl/leychile/navegar?idNorma=1205298";
const msg=(error:unknown)=>error instanceof Error?error.message:String(error);
// Cada gráfico del IRL contiene numeraciones definidas en el Excel original.
// Una casilla "cotejado" no reemplaza la presencia real de cada apartado.
const requiredOriginalNumbers:Record<number,number[]>={
  1:[8,9,10,11,12,13,14,15],
  2:[1,2,3],3:[4,5,6],4:[7,8,9],5:[10,11,12,13],
};
function missingOriginalNumbers(item:Block|undefined,id:number):number[]{
  const found=new Set<number>();
  const matcher=/^\s*(?:☐|□|\[\s*\])?\s*0*(\d{1,2})(?:\s*[-.)]|\s{1,})/gm;
  for(const match of (item?.text||"").matchAll(matcher))
    found.add(Number(match[1]));
  return (requiredOriginalNumbers[id]||[]).filter(x=>!found.has(x));
}

export default function JavieraIRLVisualBlocks({source}: {source:Source}){
  const [data,setData]=useState<Data|null>(null);
  const [blocks,setBlocks]=useState<Block[]>([]);
  const [reason,setReason]=useState("Reconstrucción editable del IRL original; cotejo visual de cinco bloques.");
  const [comments,setComments]=useState("");
  const [checks,setChecks]=useState<Record<string,boolean>>({});
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [expanded,setExpanded]=useState(false);
  const [revisionId,setRevisionId]=useState<string|null>(null);
  const [showReview,setShowReview]=useState(false);
  const five=source.images.length===5&&!!source.source_sha256;
  const complete=blocks.length===5&&blocks.every(b=>b.text.trim().length>=30);
  const reviewed=complete&&blocks.every(b=>b.reviewed);
  const missing=blocks.flatMap(block=>missingOriginalNumbers(block,block.id));
  const readyForPreventiveReview=reviewed&&missing.length===0;
  const canPublish=!!revisionId&&!!data?.latest.can_publish&&readyForPreventiveReview;
  const sourceReady=!!data&&data.source_sha256===source.source_sha256&&
    data.image_hashes.every((hash,i)=>hash===source.images[i]?.sha256);
  const completedCount=useMemo(()=>blocks.filter(b=>b.reviewed).length,[blocks]);
  async function refresh(){
    const response=await request<Data>("/javiera/v195/irl-blocks");
    setData(response);
    const initial=response.latest.source_matches?response.latest.blocks:[];
    setBlocks(Array.from({length:5},(_,index)=>initial.find(row=>row.id===index+1)||
      {id:index+1,text:"",reviewed:false}));
    setRevisionId(response.latest.id);
  }
  useEffect(()=>{
    let active=true;
    setLoading(true);
    if(!five){setLoading(false);return;}
    void request<Data>("/javiera/v195/irl-blocks").then(response=>{
      if(!active)return;setData(response);
      const initial=response.latest.source_matches?response.latest.blocks:[];
      setBlocks(Array.from({length:5},(_,index)=>initial.find(row=>row.id===index+1)||
        {id:index+1,text:"",reviewed:false}));
      setRevisionId(response.latest.id);
    }).catch(e=>{if(active)setError(msg(e))}).finally(()=>{if(active)setLoading(false)});
    return()=>{active=false};
  },[source.source_sha256,five]);
  function edit(id:number,change:Partial<Block>){
    setBlocks(prev=>prev.map(block=>block.id!==id?block:{
      ...block,...change,reviewed:change.text!==undefined?false:
        (change.reviewed??block.reviewed)
    }));
    setMessage("");setRevisionId(null);
  }
  async function importDraft(file:File){
    setError("");setMessage("");
    try{
      if(file.size>100000)throw Error("El borrador supera 100 KB.");
      const payload=JSON.parse(await file.text());
      const items=payload.items;
      // Al importar el JSON preparado desde el Excel no aceptar borradores
      // de otro juego de imágenes. El hash del libro puede variar entre
      // versiones corregidas; los cinco PNG deben coincidir exactamente.
      const hashes=payload.source?.images_sha256;
      if(Array.isArray(hashes) && (hashes.length!==5||
        hashes.some((value:unknown,index:number)=>value!==source.images[index]?.sha256)))
        throw Error("Este JSON pertenece a otras imágenes del IRL. Importa el archivo que corresponde al Excel actual.");
      if(payload.format!=="galant-irl-blocks-draft-1"||!Array.isArray(items)||
         items.length!==5||new Set(items.map((x:Block)=>x.id)).size!==5)
        throw Error("Archivo inválido: deben existir los cinco bloques IRL.");
      const result:Block[]=items.map((item:Block)=>({
        id:item.id,text:String(item.text||""),reviewed:false,
      })).sort((a,b)=>a.id-b.id);
      if(result.some((item,i)=>item.id!==i+1||item.text.length<30||item.text.length>18000))
        throw Error("Transcripción incompleta o demasiado extensa.");
      setBlocks(result);
      setRevisionId(null);
      setMessage("Borrador importado. Debes cotejar de nuevo cada bloque contra el Excel.");
      setExpanded(true);
    }catch(e){setError(msg(e))}
  }
  async function save(){
    if(!complete||!sourceReady||busy)return;
    setBusy(true);setError("");setMessage("");
    try{
      const result=await request<{id:string;revision:number;state:string}>(
        "/javiera/v195/irl-blocks",{
        method:"POST",body:JSON.stringify({
          source_sha256:data!.source_sha256,image_hashes:data!.image_hashes,
          reason,blocks:blocks.map(b=>({...b,text:b.text.trim()})),
        }),
      });
      setRevisionId(result.id);
      setData({...data!,latest:{id:result.id,revision:result.revision,
        status:"draft",source_matches:true,blocks,preventive_verdict:"pending",
        author_is_current_user:true,can_publish:false,
        preventive_authorization_valid:false}});
      setMessage("Revisión "+result.revision+" guardada como borrador. No se ha aprobado.");
    }catch(e){setError(msg(e))}finally{setBusy(false)}
  }
  async function signoff(){
    if(!revisionId||!readyForPreventiveReview||comments.trim().length<40||
      !checklist.every(([key])=>checks[key])||busy)return;
    setBusy(true);setError("");
    try{
      await request("/javiera/admin/reviews/signoff",{
        method:"POST",body:JSON.stringify({
          resource_kind:"template",resource_id:revisionId,
          specialty:"prevencion",verdict:"approved",
          checklist:Object.fromEntries(checklist.map(([key])=>[key,true])),
          comments,regulatory_basis:basis,
        }),
      });
      await refresh();
      setMessage("Acta preventiva registrada. La publicación se habilita si el servidor confirma el acta.");
    }catch(e){setError(msg(e))}finally{setBusy(false)}
  }
  async function publish(){
    if(!canPublish||busy)return;
    setBusy(true);setError("");
    try{
      await request("/javiera/v195/irl-blocks/"+encodeURIComponent(revisionId)+"/publish",
        {method:"POST"});
      await refresh();setMessage("La revisión editorial fue publicada después del acta preventiva.");
    }catch(e){setError(msg(e))}finally{setBusy(false)}
  }
  return <section className="jvb-root" aria-label="Editor de cinco bloques originales">
    <header className="jvb-heading">
      <div><small>IRL · TEXTO EDITABLE Y CONTROL DE FUENTE</small>
        <h3><FileText size={18}/> Cinco bloques originales</h3>
        <p>Coteja cada transcripción junto a su imagen. GALANT conserva el PNG exacto
          hasta que otro revisor autorizado apruebe una versión editorial.</p></div>
      <button type="button" onClick={()=>setExpanded(value=>!value)}>
        {expanded?"Ocultar editor":"Abrir editor de bloques"}
      </button>
    </header>
    <div className="jvb-bar">
      <span className="jvb-pill">{completedCount}/5 cotejados</span>
      <span>Abre cada bloque para comparar su fotografía con el texto editable.</span>
      <span>{!data?"Consultando aprobación del Excel fuente":
        data.source_layout_status==="approved"?
        "Excel fuente aprobado": "Bloqueo: Excel original aún sin aprobación"}</span>
      <span>{data?.approved_source_matches?"Existe versión editorial aprobada para esta fuente":
        "Se imprime el material gráfico original mientras falte aprobación"}</span>
      <span>{revisionId?"Revisión "+(data?.latest.revision||"borrador"):"Cambios locales sin guardar"}</span>
      <span role="status">{data?.latest.preventive_verdict==="approved"&&
          !data.latest.preventive_authorization_valid?
        "Acta sin autorización vigente: requiere designar revisor":data?.latest.status==="approved"?
        "Versión editorial publicada":data?.latest.preventive_verdict==="approved"?
        "Acta preventiva aprobada":data?.latest.preventive_verdict==="rejected"?
        "Acta preventiva rechazada":revisionId?"Pendiente de acta preventiva":
        "Sin revisión lista para aprobar"}</span>
    </div>
    {error&&<p className="jvb-error" role="alert">{error}</p>}
    {message&&<p className="jvb-info" role="status">{message}</p>}
    {!five&&<p className="jvb-error">Importa el Excel original con sus cinco imágenes para habilitar el editor.</p>}
    {loading&&<p role="status">Consultando revisiones editoriales…</p>}
    {expanded&&five&&!loading&&<div className="jvb-content">
      <div className="jvb-tools">
        <label className="jvb-upload"><Upload size={15}/> Importar borrador JSON
          <input aria-label="Importar transcripción JSON de cinco bloques" type="file"
            accept=".json,application/json"
            onChange={e=>{const file=e.target.files?.[0];
              if(file)void importDraft(file);e.target.value="";}}/>
        </label>
        <span>Para iniciar, importa el JSON generado desde el editor HTML de cotejo o escribe cada bloque.</span>
      </div>
      {source.images.map((image,index)=>{
        const item=blocks.find(b=>b.id===index+1);
        const notFound=missingOriginalNumbers(item,index+1);
        return <details className="jvb-block" key={image.sha256} open={index===0}>
          <summary className="jvb-block-title">
            <strong>{index+1}. {data?.titles[index]||image.title}</strong>
            <span className={item?.reviewed?"jvb-state-reviewed":"jvb-state-pending"}>
              {item?.reviewed?"Cotejo visual marcado":"Pendiente de cotejo"}
            </span>
          </summary>
          <div className="jvb-split">
            <div><label>Imagen original · fila {image.anchor_row}</label>
              <img src={image.data_uri} alt={image.title}/></div>
            <div><label htmlFor={"jvb-text-"+index}>Texto editable para impresión HTML</label>
              <textarea id={"jvb-text-"+index} rows={13} value={item?.text||""}
                onChange={event=>edit(index+1,{text:event.target.value})}/>
              {notFound.length>0&&<p className="jvb-missing" role="status">
                Faltan apartados originales: {notFound.map(v=>String(v).padStart(2,"0")).join(", ")}.
                Escribe cada número al inicio de la línea, por ejemplo «{String(notFound[0]).padStart(2,"0")}.-».
                Puedes guardar un borrador, pero no aprobarlo todavía.
              </p>}
              <label className="jvb-check"><input type="checkbox"
                checked={!!item?.reviewed} disabled={!item||item.text.trim().length<30||notFound.length>0}
                onChange={e=>edit(index+1,{reviewed:e.target.checked})}/>
                Cotejé cada línea y casilla con la imagen original</label></div>
          </div>
        </details>
      })}
      <div className="jvb-bottom">
        <label>Motivo de la revisión
          <textarea rows={2} maxLength={800} value={reason}
            onChange={event=>setReason(event.target.value)}/>
        </label>
        <button type="button" className="jvb-primary" disabled={!complete||busy||
          reason.trim().length<12||!sourceReady}
          onClick={()=>void save()}><Save size={15}/> Guardar nueva revisión en borrador</button>
      </div>
      {revisionId&&<section className="jvb-signoff">
        <div><strong>Acta preventiva independiente y publicación</strong>
          <p>Recurso de revisión: <code>{revisionId}</code>. El autor no puede
            firmar su propia transcripción. Requiere designación de revisor de prevención.</p></div>
        <div className="jvb-actionline">
          <button type="button" onClick={()=>void refresh()} disabled={busy}>
            Actualizar estado de aprobación
          </button>
          <button type="button" onClick={()=>setShowReview(v=>!v)}>
            {showReview?"Ocultar control de firma":"Revisión y publicación"}
          </button>
        </div>
        {data?.latest.author_is_current_user&&<p className="jvb-subtle">
          Eres el autor: otra persona designada en prevención debe registrar la aprobación.
        </p>}
        {data?.latest.preventive_verdict==="rejected"&&<p className="jvb-error">
          Rechazada. Corrige el contenido y guarda una nueva revisión.
        </p>}
        {showReview&&<div>
          {data?.source_layout_status!=="approved"&&<p className="jvb-error">
            Falta aprobación independiente del formato Excel IRL. Puedes
            guardar y revisar los borradores, pero no publicarlos todavía.
          </p>}
          {checklist.map(([key,label])=><label className="jvb-check" key={key}>
            <input type="checkbox" checked={!!checks[key]}
              onChange={e=>setChecks(prev=>({...prev,[key]:e.target.checked}))}/>{label}
          </label>)}
          <label>Fundamento de la decisión y comprobación del cotejo
            <textarea rows={3} value={comments} onChange={e=>setComments(e.target.value)}
              placeholder="Explica qué imágenes cotejaste y cómo verificaste el IRL."/>
          </label>
          <div className="jvb-actionline">
            <button type="button" disabled={!readyForPreventiveReview||comments.trim().length<40||
              !checklist.every(([key])=>checks[key])||busy||
              !!data?.latest.author_is_current_user||
              data?.latest.preventive_verdict!=="pending"}
              onClick={()=>void signoff()}><ShieldCheck size={16}/> Registrar acta preventiva</button>
            <button className="jvb-primary" type="button" disabled={!canPublish||busy}
              onClick={()=>void publish()}><CheckCircle2 size={15}/> Publicar revisión autorizada</button>
          </div>
          <p className="jvb-subtle">El revisor preventivo y el autor deben ser personas distintas.
            La aprobación requiere una designación vigente. Una vez registrada
            el acta, cualquier administrador puede publicar sin falsificar la firma técnica.</p>
        </div>}
      </section>}
    </div>}
  </section>;
}
