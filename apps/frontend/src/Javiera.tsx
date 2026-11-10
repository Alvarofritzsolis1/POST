import {useEffect, useMemo, useRef, useState} from "react";
import {ArrowLeft, CheckCircle2, ClipboardList, Download, FileText, FolderOpen, Settings2, ShieldCheck, Upload, AlertCircle} from "lucide-react";
import {request} from "./api";
import {opsApi} from "./opsApi";
import "./javiera.css";
import JavieraExcelAdmin from "./JavieraExcelAdmin";
import JavieraV17 from "./JavieraV17";
import JavieraNativeEditor from "./JavieraNativeEditor";
import JavieraMatrixEditor from "./JavieraMatrixEditor";

type Source = {sites: {id:string;name:string}[];contractors:{id:string;site_id:string;name:string;rut:string|null;nature:string}[];workers:{id:string;name:string;rut:string|null;active:boolean}[]};
type Catalog = {code:string;area:string;title:string;required_fields:string[];published_version:number};
type Status = {code:string;area:string;title:string;status:string;reason:string;missing_fields:string[];blocking_errors:string[];completion_percent:number;can_preview:boolean;can_issue:boolean;has_history:boolean;template_version:number};
type Template = {code:string;title:string;area:string;body:string;fields:string[];rule:Record<string,unknown>;layout:Record<string,unknown>;published_version:number;revisions:{revision:number;state:string;author_id:string;reason:string;contents:{body:string;title:string;area:string;fields:string[];rule?:Record<string,unknown>;layout?:Record<string,unknown>}}[]};
type Matrix = {id:string;kind:string;cargo:string;sections:string[];revision:number;status:string;source:string;author_id:string};
type Dossier = {id:string;revision:number;data:Record<string,unknown>;site_id:string;employer_id:string;worker_id:string|null;parent_id:string|null;relationship:string;issues:{id:string;code:string;at:string;sha256:string;version:number}[];historical:{id:string;code:string;state:string;comment:string}[]};
const emptySource:Source={sites:[],contractors:[],workers:[]};
const emptyContract={start:"",end:"",new_end:"",salary:"",hours:"",transfer_date:"",declaration_reason:"",regulation_version:""};
const emptyEvent={date:"",epp_items:"",pts_version:""};
const statusText:Record<string,string>={
  POR_DETERMINAR:"Por determinar", NO_APLICA:"No aplica", FALTAN_DATOS:"Faltan datos",
  PENDIENTE_REVISION:"Requiere revisión", PREVISUALIZABLE:"Vista previa disponible",
  LISTO_PARA_EMITIR:"Listo para PDF", EXISTENTE_POR_VERIFICAR:"Documento anterior",
  ERROR_TEMPORAL:"Validación no disponible", EMITIDO:"Emitido"
};
const eventOptions=[
  ["ingreso","Ingreso o incorporación"],["reingreso","Reingreso"],["actualizacion","Actualización"],
  ["traslado","Traslado de obra"],["prorroga","Prórroga"],["declaracion","Declaración jurada"],
  ["reglamento","Recepción de reglamento"],["entrega_epp","Entrega real de EPP"],
  ["recepcion_pts","Recepción de PTS"],["induccion","Inducción realizada"],["cambio_cargo","Cambio de cargo"]
];
const validField=(key:string)=>key.replaceAll(".","_");
const errorMessage=(e:unknown)=>e instanceof Error?e.message:String(e);
async function pdfRequest(url:string,body:unknown){
  const csrf=document.cookie.split("; ").find(c=>c.startsWith("galant_post_csrf="))?.split("=")[1]||"";
  const response=await fetch("/api/v1/javiera"+url,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
    credentials:"include",cache:"no-store",body:JSON.stringify(body)});
  if(!response.ok){const x=await response.json().catch(()=>({detail:"PDF no disponible"}));throw new Error(typeof x.detail==="string"?x.detail:"El documento aún no está habilitado");}
  return response.blob();
}
function previewBlob(blob:Blob){
  const url=URL.createObjectURL(blob);
  window.open(url,"_blank","noopener,noreferrer");
  window.setTimeout(()=>URL.revokeObjectURL(url),60000);
}

function currentEditableTemplate(template:Template|null):Template|null{
  if(!template)return null;
  const latest=template.revisions.find(r=>
    r.revision>template.published_version &&
    ["draft","pilot_print"].includes(r.state));
  if(!latest)return template;
  return {...template,...latest.contents,
    rule:latest.contents.rule||template.rule,
    layout:latest.contents.layout||template.layout};
}
function Setup({onBack}:{onBack:()=>void}){
  const [templates,setTemplates]=useState<Template[]>([]);
  const [selected,setSelected]=useState("labor_contract");
  const [draft,setDraft]=useState<Template|null>(null);
  const [reason,setReason]=useState("");
  const [newField,setNewField]=useState("");
  const [tab,setTab]=useState<"documentos"|"matrices"|"legacy_matrices"|"excel"|"reviews"|"texto_legacy">("documentos");
  const [matrices,setMatrices]=useState<Matrix[]>([]);
  const [matrixKind,setMatrixKind]=useState<"PTS"|"IRL">("PTS");
  const [soloPilot,setSoloPilot]=useState(false);
  const [selectedMatrixId,setSelectedMatrixId]=useState("");
  const [matrixConfirmed,setMatrixConfirmed]=useState(false);
  const latestMatrices=useMemo(()=>{
    const seen=new Set<string>();
    return matrices.filter(m=>{
      const key=m.kind+":"+m.cargo;
      if(seen.has(key))return false;
      seen.add(key);return true;
    });
  },[matrices]);
  const [cargo,setCargo]=useState("");
  const [sections,setSections]=useState<string[]>(Array(17).fill(""));
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const [importReport,setImportReport]=useState("");
  const [importing,setImporting]=useState(false);
  async function importWorkbook(file:File){
    if(!file.name.toLowerCase().endsWith(".xlsx")){setError("Selecciona un archivo .xlsx");return;}
    setImporting(true);setError("");setImportReport("");
    const csrf=document.cookie.split("; ").find(c=>c.startsWith("galant_post_csrf="))?.split("=")[1]||"";
    const form=new FormData();form.append("file",file);
    try{
      const response=await fetch("/api/v1/javiera/admin/import-workbook",{
        method:"POST",body:form,credentials:"include",headers:{"X-CSRF-Token":csrf}});
      if(!response.ok){const detail=await response.json().catch(()=>({detail:"Error de importación"}));throw new Error(typeof detail.detail==="string"?detail.detail:"El servidor rechazó las matrices");}
      const result=await response.json() as {drafts:Record<string,number>;omissions:string[]};
      setImportReport(Object.entries(result.drafts).map(([key,n])=>key+": "+n).join(" · ")+
        (result.omissions.length?" · Observaciones: "+result.omissions.slice(0,4).join("; "):""));
      setMatrices(await request<Matrix[]>("/javiera/admin/matrices"));
      setNotice("Matrices importadas como borradores; requieren aprobación.");
    }catch(e){setError(errorMessage(e));}finally{setImporting(false);}
  }
  async function refresh(){
    const [t,m]=await Promise.all([request<Template[]>("/javiera/admin/templates"),
      request<Matrix[]>("/javiera/admin/matrices")]);
    setTemplates(t);setMatrices(m);setDraft(currentEditableTemplate(t.find(x=>x.code===selected)||t[0]||null));
  }
  useEffect(()=>{
    void refresh().catch(e=>setError(errorMessage(e)));
    void request<{solo_pilot:boolean}>("/javiera/admin/excel/status")
      .then(r=>setSoloPilot(r.solo_pilot)).catch(()=>setSoloPilot(false));
  },[]);
  function pick(code:string){setSelected(code);setDraft(currentEditableTemplate(templates.find(t=>t.code===code)||null));setReason("");}
  async function save(){
    if(!draft)return;
    setError("");setNotice("");
    try{
      await request("/javiera/admin/templates/"+draft.code,{method:"PUT",body:JSON.stringify({
        title:draft.title,area:draft.area,body:draft.body,fields:draft.fields,
        rule:draft.rule,layout:draft.layout,reason})});
      await refresh();setNotice(soloPilot?"Borrador guardado. Revisa el formato antes de habilitarlo para PDF.":"Borrador registrado; requiere revisión independiente.");
    }catch(e){setError(errorMessage(e));}
  }
  async function approve(code:string,revision:number){
    try{
      if(soloPilot){
        await request("/javiera/v19/templates/"+code+"/enable-preview",{
          method:"POST",body:JSON.stringify({revision,confirmed_content:true})});
        await refresh();
        setNotice("Texto habilitado para vista previa A4; no equivale a aprobación profesional ni a firma física.");
      }else{
        await request("/javiera/admin/templates/"+code+"/approve/"+revision,{method:"POST"});
        await refresh();setNotice("Versión aprobada y publicada.");
      }
    }catch(e){setError(errorMessage(e));}
  }
  async function saveMatrix(){
    try{await request("/javiera/admin/matrices",{method:"POST",body:JSON.stringify({
      kind:matrixKind,cargo,sections:sections.map(s=>s.trim()),source:"Configuración JAVIERA v18"})});
      const m=await request<Matrix[]>("/javiera/admin/matrices");setMatrices(m);
      setSelectedMatrixId(m.find(x=>x.kind===matrixKind&&x.cargo===cargo.trim().toUpperCase())?.id||"");
      setMatrixConfirmed(false);
      setNotice(soloPilot?"Matriz guardada. Comprueba sus secciones y habilita su impresión.":"Matriz en borrador; requiere revisión independiente.");setError("");
    }catch(e){setError(errorMessage(e));}
  }
  async function approveMatrix(id:string){
    try{
      if(soloPilot){
        if(!matrixConfirmed||selectedMatrixId!==id){setError("Selecciona la matriz y confirma que revisaste su contenido.");return;}
        await request("/javiera/admin/matrices/"+id+"/enable-print",{
          method:"POST",body:JSON.stringify({confirmed_content:true})});
      }else await request("/javiera/admin/matrices/"+id+"/approve",{method:"POST"});
      setMatrices(await request<Matrix[]>("/javiera/admin/matrices"));setMatrixConfirmed(false);
      setNotice(soloPilot?"Matriz habilitada para PDF, sin registrar una firma física.":"Matriz aprobada.");setError("");
    }catch(e){setError(errorMessage(e));}
  }
  return <main className="jv-admin">
    <header className="jv-heading"><button type="button" onClick={onBack} className="jv-back"><ArrowLeft size={18}/> Volver a GALANT</button>
      <div><small>GALANT · CONTROL DE VERSIONES</small><h1>Configuración de automatización</h1>
        <p>Plantillas de PDF para imprimir y obtener firmas en papel. Los cambios conservan historial y auditoría.</p></div>
      <span className="jv-mark">Proyecto JAVIERA · Visual 19.2</span></header>
    <div className="jv-tabs"><button className={tab==="documentos"?"active":""} aria-pressed={tab==="documentos"} onClick={()=>setTab("documentos")}>Plantillas y cláusulas</button>
      <button className={tab==="matrices"?"active":""} aria-pressed={tab==="matrices"} onClick={()=>setTab("matrices")}>Matrices y cargos</button>
      <button className={tab==="excel"?"active":""} aria-pressed={tab==="excel"} onClick={()=>setTab("excel")}>Diseños Excel originales</button>
      <button className={tab==="reviews"?"active":""} aria-pressed={tab==="reviews"} onClick={()=>setTab("reviews")}>Habilitar PDF / revisiones</button>
      <button className={tab==="texto_legacy"?"active":""} aria-pressed={tab==="texto_legacy"}
        onClick={()=>setTab("texto_legacy")}>Texto tradicional (respaldo)</button></div>
    {error&&<p role="alert" className="jv-error">{error}</p>}{notice&&<p role="status" className="jv-success">{notice}</p>}
    {tab==="documentos"&&<JavieraNativeEditor onBack={onBack} onOpenMatrices={()=>setTab("matrices")}/>}
     {tab==="matrices"&&<JavieraMatrixEditor/>}
    {tab==="texto_legacy"&&<div className="jv-admin-layout">
      <nav className="jv-template-list" aria-label="Plantillas documentales">{templates.map(t=>
        <button key={t.code} className={selected===t.code?"chosen":""} onClick={()=>pick(t.code)}>
          <FileText size={16}/><span>{t.title}<small>{t.published_version?"Publicada v"+t.published_version:"Pendiente de aprobación"}</small></span>
        </button>)}</nav>
      {draft&&<section className="jv-editor">
        <h2>Editar el texto del documento</h2>
        <p>Selecciona el formato a la izquierda, modifica su texto original y guarda un borrador.
           Puedes usar variables como <code>{"{{worker.name}}"}</code>.
           Después habilita la vista previa. Ningún cambio reescribe PDFs históricos.</p>
        <label>Título <input value={draft.title} onChange={e=>setDraft({...draft,title:e.target.value})}/></label>
        <label>Eventos aplicables (selección múltiple; vacío = regla original)
          <select multiple size={7} value={Array.isArray(draft.rule.events)?draft.rule.events as string[]:[]}
            onChange={e=>setDraft({...draft,rule:{...draft.rule,events:Array.from(e.currentTarget.selectedOptions,x=>x.value)}})}>
            {eventOptions.map(([v,l])=><option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>Vínculos permitidos (vacío = regla original)
          <select multiple size={2} value={Array.isArray(draft.rule.employment_types)?draft.rule.employment_types as string[]:[]}
            onChange={e=>setDraft({...draft,rule:{...draft.rule,employment_types:Array.from(e.currentTarget.selectedOptions,x=>x.value)}})}>
            <option value="dependiente">Dependiente</option><option value="independiente">Independiente</option>
          </select>
        </label>
        <label>Área documental <select value={draft.area} onChange={e=>setDraft({...draft,area:e.target.value})}>
          <option>Zona Subcontratos</option><option>Prevención de Riesgos</option></select></label>
        <details className="jv-layout-editor"><summary>Diseño del PDF · A4</summary>
          <label>Encabezado <input value={String(draft.layout.header??"DOCUMENTACIÓN LABORAL Y PREVENTIVA")}
            onChange={e=>setDraft({...draft,layout:{...draft.layout,header:e.target.value}})}/></label>
          <label>Pie de página <input value={String(draft.layout.footer??"Documento para firma manuscrita")}
            onChange={e=>setDraft({...draft,layout:{...draft.layout,footer:e.target.value}})}/></label>
          <div className="jv-paired">
            <label>Tamaño de letra (9 a 12) <input type="number" min="9" max="12"
              value={String(draft.layout.font_size??10)}
              onChange={e=>setDraft({...draft,layout:{...draft.layout,font_size:Number(e.target.value)}})}/></label>
            <label>Margen lateral (30 a 75 pt) <input type="number" min="30" max="75"
              value={String(draft.layout.margin??45)}
              onChange={e=>setDraft({...draft,layout:{...draft.layout,margin:Number(e.target.value)}})}/></label>
          </div>
        </details>
        <label>Contenido completo del documento <textarea rows={17} spellCheck value={draft.body}
          placeholder="Redacte aquí el contenido aprobado; inserte variables como {{worker.name}}"
          onChange={e=>setDraft({...draft,body:e.target.value})}/></label>
        <div className="jv-vars"><h3>Campos y variables requeridas</h3><p>Inserta variables en el documento. Cada token debe figurar como campo requerido.</p>
          <div className="jv-chips">{draft.fields.map(f=><button key={f} title="Quitar campo" onClick={()=>setDraft({...draft,fields:draft.fields.filter(x=>x!==f)})}>{f} ×</button>)}</div>
          <div className="jv-inline"><input aria-label="Nueva variable" placeholder="extra.campo_adicional" value={newField}
            onChange={e=>setNewField(e.target.value)}/><button onClick={()=>{if(newField&&!draft.fields.includes(newField))setDraft({...draft,fields:[...draft.fields,newField]});setNewField("");}}>Agregar campo</button></div>
        </div>
        <label>Motivo de cambio <input value={reason} onChange={e=>setReason(e.target.value)} placeholder="Ej. Corrección de párrafo o matriz"/></label>
        <button className="jv-primary" disabled={reason.trim().length<6||draft.body.trim().length<20} onClick={()=>void save()}>Guardar borrador</button>
      </section>}
      <aside className="jv-versions"><h3>Historial y habilitación</h3>
        <p>{soloPilot?"En el piloto, el administrador habilita únicamente la vista previa A4 del texto que revisó. No hay firma ni aprobación profesional automática.":"La publicación formal requiere una persona revisora autorizada distinta del autor."}</p>
        {(templates.find(t=>t.code===selected)?.revisions||[]).map(v=><div className="jv-version" key={v.revision}>
          <b>Revisión {v.revision}</b>
          <small>{v.state==="draft"?"Borrador sin habilitar":v.state==="pilot_print"?"Vista previa A4 habilitada":v.state==="published"?"Publicada profesionalmente":v.state}</small>
          <p>{v.reason}</p>
          {v.state==="draft"&&<button onClick={()=>void approve(selected,v.revision)}>
            {soloPilot?"Habilitar vista previa A4":"Solicitar aprobación profesional"}
          </button>}
          <details><summary>Comparar contenido</summary><pre>{v.contents.body}</pre></details>
        </div>)}
        {!templates.find(t=>t.code===selected)?.revisions.length&&<p>Sin revisiones registradas.</p>}
      </aside>
    </div>}
    {(tab==="excel"||tab==="reviews")&&<JavieraExcelAdmin tab={tab} onChangeTab={setTab}/>}
    {tab==="legacy_matrices"&&<section className="jv-import">
      <h2>Importar matrices del Excel JAVIERA</h2>
      <p>Selecciona el Excel corregido desde tu computador. Se procesan las matrices y no se suben datos laborales al repositorio GitHub.</p>
      <label className="jv-upload"><Upload size={16}/> {importing?"Importando…":"Seleccionar Excel .xlsx"}
        <input disabled={importing} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={e=>{const file=e.target.files?.[0];if(file)void importWorkbook(file);e.target.value="";}}/>
      </label>
      {importReport&&<p className="jv-success" role="status">{importReport}</p>}
    </section>}
    {tab==="legacy_matrices"&&<div className="jv-admin-layout">
      <nav className="jv-template-list" aria-label="Matrices existentes">
        {latestMatrices.map(m=><button key={m.id} onClick={()=>{setMatrixKind(m.kind as "PTS"|"IRL");setCargo(m.cargo);setSections(m.sections);setSelectedMatrixId(m.id);setMatrixConfirmed(false);}}>
          <ClipboardList size={16}/><span>{m.cargo}<small>{m.kind} · v{m.revision} · {m.status}</small></span></button>)}
      </nav>
      <section className="jv-editor"><h2>Editor de matrices</h2><p>PTS exige las 17 secciones del Excel. Cada cambio crea una nueva revisión.</p>
        <label>Tipo <select value={matrixKind} onChange={e=>{const kind=e.target.value as "PTS"|"IRL";setMatrixKind(kind);setSections(Array(kind==="PTS"?17:4).fill(""));}}>
          <option>PTS</option><option>IRL</option></select></label>
        <label>Cargo <input value={cargo} onChange={e=>setCargo(e.target.value)} placeholder="Cargo canónico"/></label>
        {sections.map((s,i)=><label key={i}>Sección {i+1}<textarea rows={3} value={s}
          onChange={e=>setSections(old=>old.map((x,j)=>j===i?e.target.value:x))}/></label>)}
        <button className="jv-primary" disabled={!cargo.trim()} onClick={()=>void saveMatrix()}>Guardar revisión de matriz</button>
      </section>
      <aside className="jv-versions"><h3>Revisión preventiva</h3>
        {latestMatrices.filter(m=>m.status==="draft").map(m=><div key={m.id} className="jv-version"><b>{m.kind} · {m.cargo}</b>
          <p>Versión {m.revision} · pendiente de habilitar.</p>
          {soloPilot&&selectedMatrixId===m.id&&<label>
            <input type="checkbox" checked={matrixConfirmed} onChange={e=>setMatrixConfirmed(e.target.checked)}/>
            He revisado todas las secciones de esta matriz para su impresión.
          </label>}
          <button disabled={soloPilot&&(selectedMatrixId!==m.id||!matrixConfirmed)}
            onClick={()=>void approveMatrix(m.id)}>{soloPilot?"Habilitar para PDF":"Aprobar"}</button></div>)}
        {!latestMatrices.some(m=>m.status==="draft")&&<p>Sin matrices pendientes.</p>}
      </aside>
    </div>}
  </main>;
}

export default function Javiera({configuration=false,onBack,onConfig}:{configuration?:boolean;onBack?:()=>void;onConfig?:()=>void}){
  return configuration?<Setup onBack={onBack||(()=>window.history.back())}/>:<JavieraV17 onConfig={onConfig}/>;
}
