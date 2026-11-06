import {useEffect, useMemo, useRef, useState} from "react";
import {ArrowLeft, CheckCircle2, ClipboardList, Download, FileText, FolderOpen, Settings2, ShieldCheck, Upload, AlertCircle} from "lucide-react";
import {request} from "./api";
import {opsApi} from "./opsApi";
import "./javiera.css";
import JavieraExcelAdmin from "./JavieraExcelAdmin";

type Source = {sites: {id:string;name:string}[];contractors:{id:string;site_id:string;name:string;rut:string|null;nature:string}[];workers:{id:string;name:string;rut:string|null;active:boolean}[]};
type Catalog = {code:string;area:string;title:string;required_fields:string[];published_version:number};
type Status = {code:string;area:string;title:string;status:string;reason:string;missing_fields:string[];blocking_errors:string[];completion_percent:number;can_preview:boolean;can_issue:boolean;has_history:boolean;template_version:number};
type Template = {code:string;title:string;area:string;body:string;fields:string[];rule:Record<string,unknown>;layout:Record<string,unknown>;published_version:number;revisions:{revision:number;state:string;author_id:string;reason:string;contents:{body:string;title:string;area:string;fields:string[]}}[]};
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

function Setup({onBack}:{onBack:()=>void}){
  const [templates,setTemplates]=useState<Template[]>([]);
  const [selected,setSelected]=useState("labor_contract");
  const [draft,setDraft]=useState<Template|null>(null);
  const [reason,setReason]=useState("");
  const [newField,setNewField]=useState("");
  const [tab,setTab]=useState<"documentos"|"matrices"|"excel"|"reviews">("documentos");
  const [matrices,setMatrices]=useState<Matrix[]>([]);
  const [matrixKind,setMatrixKind]=useState<"PTS"|"IRL">("PTS");
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
    setTemplates(t);setMatrices(m);setDraft(t.find(x=>x.code===selected)||t[0]||null);
  }
  useEffect(()=>{void refresh().catch(e=>setError(errorMessage(e)));},[]);
  function pick(code:string){setSelected(code);setDraft(templates.find(t=>t.code===code)||null);setReason("");}
  async function save(){
    if(!draft)return;
    setError("");setNotice("");
    try{
      await request("/javiera/admin/templates/"+draft.code,{method:"PUT",body:JSON.stringify({
        title:draft.title,area:draft.area,body:draft.body,fields:draft.fields,
        rule:draft.rule,layout:draft.layout,reason})});
      await refresh();setNotice("Borrador registrado. Otro administrador debe revisar y aprobar.");
    }catch(e){setError(errorMessage(e));}
  }
  async function approve(code:string,revision:number){
    try{await request("/javiera/admin/templates/"+code+"/approve/"+revision,{method:"POST"});
      await refresh();setNotice("Versión aprobada y publicada.");}catch(e){setError(errorMessage(e));}
  }
  async function saveMatrix(){
    try{await request("/javiera/admin/matrices",{method:"POST",body:JSON.stringify({
      kind:matrixKind,cargo,sections:sections.map(s=>s.trim()),source:"Configuración JAVIERA v16"})});
      const m=await request<Matrix[]>("/javiera/admin/matrices");setMatrices(m);
      setNotice("Matriz en borrador; requiere revisión independiente.");setError("");
    }catch(e){setError(errorMessage(e));}
  }
  async function approveMatrix(id:string){
    try{await request("/javiera/admin/matrices/"+id+"/approve",{method:"POST"});
      setMatrices(await request<Matrix[]>("/javiera/admin/matrices"));setNotice("Matriz aprobada.");setError("");
    }catch(e){setError(errorMessage(e));}
  }
  return <main className="jv-admin">
    <header className="jv-heading"><button type="button" onClick={onBack} className="jv-back"><ArrowLeft size={18}/> Volver a GALANT</button>
      <div><small>GALANT · CONTROL DE VERSIONES</small><h1>Configuración de automatización</h1>
        <p>Todo el contenido documental es editable; la aprobación y la auditoría no pueden desactivarse.</p></div>
      <span className="jv-mark">Proyecto JAVIERA · v16</span></header>
    <div className="jv-tabs"><button className={tab==="documentos"?"active":""} aria-pressed={tab==="documentos"} onClick={()=>setTab("documentos")}>Plantillas y cláusulas</button>
      <button className={tab==="matrices"?"active":""} aria-pressed={tab==="matrices"} onClick={()=>setTab("matrices")}>Matrices PTS / IRL</button>
      <button className={tab==="excel"?"active":""} aria-pressed={tab==="excel"} onClick={()=>setTab("excel")}>Diseños Excel originales</button>
      <button className={tab==="reviews"?"active":""} aria-pressed={tab==="reviews"} onClick={()=>setTab("reviews")}>Revisiones y aprobaciones</button></div>
    {error&&<p role="alert" className="jv-error">{error}</p>}{notice&&<p role="status" className="jv-success">{notice}</p>}
    {tab==="documentos"&&<div className="jv-admin-layout">
      <nav className="jv-template-list" aria-label="Plantillas documentales">{templates.map(t=>
        <button key={t.code} className={selected===t.code?"chosen":""} onClick={()=>pick(t.code)}>
          <FileText size={16}/><span>{t.title}<small>{t.published_version?"Publicada v"+t.published_version:"Pendiente de aprobación"}</small></span>
        </button>)}</nav>
      {draft&&<section className="jv-editor">
        <h2>Editor de contenido</h2><p>Las modificaciones se guardan como revisiones nuevas. Nunca cambian PDFs emitidos.</p>
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
          <label>Encabezado <input value={String(draft.layout.header??"GALANT · PROYECTO JAVIERA")}
            onChange={e=>setDraft({...draft,layout:{...draft.layout,header:e.target.value}})}/></label>
          <label>Pie de página <input value={String(draft.layout.footer??"Documento generado por GALANT")}
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
      <aside className="jv-versions"><h3>Versiones y aprobaciones</h3><p>Para publicar se requiere un administrador distinto del autor.</p>
        {(templates.find(t=>t.code===selected)?.revisions||[]).map(v=><div className="jv-version" key={v.revision}>
          <b>Revisión {v.revision}</b><small>{v.state}</small><p>{v.reason}</p>
          {v.state==="draft"&&<button onClick={()=>void approve(selected,v.revision)}>Aprobar publicación</button>}
          <details><summary>Comparar contenido</summary><pre>{v.contents.body}</pre></details>
        </div>)}
        {!templates.find(t=>t.code===selected)?.revisions.length&&<p>Sin revisiones registradas.</p>}
      </aside>
    </div>}
    {(tab==="excel"||tab==="reviews")&&<JavieraExcelAdmin tab={tab}/>}
    {tab==="matrices"&&<section className="jv-import">
      <h2>Importar matrices del Excel JAVIERA</h2>
      <p>Selecciona el Excel corregido desde tu computador. Se procesan las matrices y no se suben datos laborales al repositorio GitHub.</p>
      <label className="jv-upload"><Upload size={16}/> {importing?"Importando…":"Seleccionar Excel .xlsx"}
        <input disabled={importing} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={e=>{const file=e.target.files?.[0];if(file)void importWorkbook(file);e.target.value="";}}/>
      </label>
      {importReport&&<p className="jv-success" role="status">{importReport}</p>}
    </section>}
    {tab==="matrices"&&<div className="jv-admin-layout">
      <nav className="jv-template-list" aria-label="Matrices existentes">
        {matrices.map(m=><button key={m.id} onClick={()=>{setMatrixKind(m.kind as "PTS"|"IRL");setCargo(m.cargo);setSections(m.sections);}}>
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
        {matrices.filter(m=>m.status==="draft").map(m=><div key={m.id} className="jv-version"><b>{m.kind} · {m.cargo}</b>
          <p>Versión {m.revision}, pendiente de validación.</p><button onClick={()=>void approveMatrix(m.id)}>Aprobar</button></div>)}
        {!matrices.some(m=>m.status==="draft")&&<p>Sin matrices pendientes.</p>}
      </aside>
    </div>}
  </main>;
}

export default function Javiera({configuration=false,onBack,onConfig}:{configuration?:boolean;onBack?:()=>void;onConfig?:()=>void}){
  const [mode,setMode]=useState<"contractor"|"subcontractor"|null>(null);
  const [source,setSource]=useState<Source>(emptySource);
  const [catalog,setCatalog]=useState<Catalog[]>([]);
  const [siteId,setSiteId]=useState("");
  const [companyId,setCompanyId]=useState("");
  const [parentId,setParentId]=useState("");
  const [workerId,setWorkerId]=useState("");
  const [role,setRole]=useState("");
  const [extra,setExtra]=useState<Record<string,string>>({});
  const [employmentType,setEmploymentType]=useState("");
  const [eventType,setEventType]=useState("ingreso");
  const [contract,setContract]=useState(emptyContract);
  const [event,setEvent]=useState(emptyEvent);
  const [dossierId,setDossierId]=useState("");
  const [dossierRevision,setDossierRevision]=useState(0);
  const [saved,setSaved]=useState<Dossier|null>(null);
  const [response,setResponse]=useState<{key:string;documents:Status[]}|null>(null);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false);
  const [filter,setFilter]=useState("todos");
  const [savedFingerprint,setSavedFingerprint]=useState("");
  const [existingDossiers,setExistingDossiers]=useState<{id:string;site_id:string;employer_id:string;worker_id:string|null;relationship:string;revision:number}[]>([]);
  const [newContractor,setNewContractor]=useState({name:"",rut:""});
  const [newWorker,setNewWorker]=useState({name:"",rut:""});
  const [showCreate,setShowCreate]=useState<"contractor"|"worker"|null>(null);
  const [reviewComments,setReviewComments]=useState<Record<string,string>>({});
  const [reissueReasons,setReissueReasons]=useState<Record<string,string>>({});
  const [batchReport,setBatchReport]=useState<{code:string;ok:boolean;id?:string;reason?:string}[]>([]);
  const revision=useRef(0);
  useEffect(()=>{
    if(configuration)return;
    void request<Catalog[]>("/javiera/catalog").then(setCatalog).catch(e=>setError(errorMessage(e)));
  },[configuration]);
  useEffect(()=>{
    if(configuration)return;
    let alive=true;
    request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId)+"&contractor_id="+encodeURIComponent(companyId))
      .then(x=>{if(alive)setSource(x);}).catch(e=>{if(alive)setError(errorMessage(e));});
    return ()=>{alive=false;};
  },[configuration,siteId,companyId]);
  const employer=source.contractors.find(x=>x.id===companyId);
  const worker=source.workers.find(x=>x.id===workerId);
  const site=source.sites.find(x=>x.id===siteId);
  const data=useMemo(()=>({
    employer:{name:employer?.name||"",rut:employer?.rut||""},worker:{name:worker?.name||"",rut:worker?.rut||""},
    site:{name:site?.name||""},role,event_type:eventType,employment_type:employmentType,contract,event,extra
  }),[employer?.name,employer?.rut,worker?.name,worker?.rut,site?.name,role,eventType,employmentType,contract,event,extra]);
  const fingerprint=JSON.stringify(data);
  const unsaved=!dossierId||savedFingerprint!==fingerprint;
  useEffect(()=>{
    if(configuration)return;
    const controller=new AbortController();
    revision.current+=1;const current=revision.current;
    setResponse(null);
    const timer=window.setTimeout(()=>{
      request<{documents:Status[];data_revision:number}>("/javiera/eligibility/evaluate",{
        method:"POST",body:JSON.stringify({data,dossier_id:dossierId||null,data_revision:current}),signal:controller.signal
      }).then(result=>{if(current===revision.current)setResponse({key:fingerprint,documents:result.documents});})
        .catch(e=>{if(!controller.signal.aborted)setError(errorMessage(e));});
    },350);
    return ()=>{window.clearTimeout(timer);controller.abort();};
  },[fingerprint,configuration,dossierId,saved?.issues.length,saved?.historical.length]);
  const cards:Status[]=response?.key===fingerprint?response.documents:catalog.map(x=>({
    code:x.code,area:x.area,title:x.title,status:"POR_DETERMINAR",reason:"Validando la información…",
    missing_fields:x.required_fields,blocking_errors:[],completion_percent:0,can_preview:false,can_issue:false,
    has_history:false,template_version:x.published_version
  }));
  const fieldInput=(field:string,label:string,value:string,change:(v:string)=>void,type="text")=>
    <label key={field} htmlFor={validField(field)}>{label}<input id={validField(field)} value={value}
      type={type} onChange={e=>change(e.target.value)}/></label>;
  useEffect(()=>{
    if(!mode||!companyId||!siteId)return;
    let alive=true;
    request<typeof existingDossiers>("/javiera/dossiers?site_id="+encodeURIComponent(siteId)+"&employer_id="+encodeURIComponent(companyId))
      .then(rows=>{if(alive)setExistingDossiers(rows);}).catch(e=>{if(alive)setError(errorMessage(e));});
    return()=>{alive=false;};
  },[mode,siteId,companyId,saved?.issues.length]);
  async function loadDossier(id:string){
    try{
      const row=await request<Dossier>("/javiera/dossiers/"+id);
      const src=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(row.site_id)+"&contractor_id="+encodeURIComponent(row.employer_id));
      const obj=row.data;
      const company=src.contractors.find(c=>c.id===row.employer_id);
      const worker=src.workers.find(w=>w.id===row.worker_id);
      const site=src.sites.find(z=>z.id===row.site_id);
      setSaved(row);setDossierId(row.id);setDossierRevision(row.revision);
      setSource(src);setSiteId(row.site_id);setCompanyId(row.employer_id);setWorkerId(row.worker_id||"");
      setParentId(row.parent_id||"");setMode(row.relationship==="subcontractor"?"subcontractor":"contractor");
      setRole(String(obj.role||""));setExtra(typeof obj.extra==="object"&&obj.extra?obj.extra as Record<string,string>:{});setEventType(String(obj.event_type||"ingreso"));
      setEmploymentType(String(obj.employment_type||""));
      setContract({...emptyContract,...(typeof obj.contract==="object"&&obj.contract?obj.contract as typeof emptyContract:{})});
      setEvent({...emptyEvent,...(typeof obj.event==="object"&&obj.event?obj.event as typeof emptyEvent:{})});
      setSavedFingerprint(JSON.stringify({...obj,employer:{name:company?.name||"",rut:company?.rut||""},
        worker:{name:worker?.name||"",rut:worker?.rut||""},site:{name:site?.name||""}}));
      setNotice("Expediente histórico recuperado; revisa los datos antes de emitir.");
    }catch(e){setError(errorMessage(e));}
  }
  async function createCompany(){
    if(!siteId||!newContractor.name.trim()){setError("Selecciona una obra e indica la empresa");return;}
    setBusy(true);setError("");
    try{
      const result=await opsApi.createContractor({site_id:siteId,name:newContractor.name,rut:newContractor.rut||null,
        historical_code:"",nature:"unclassified",frequency:"unclassified",contract_status:"active"});
      const src=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId));
      setSource(src);setCompanyId(result.contractor_id);setShowCreate(null);setNewContractor({name:"",rut:""});
      setNotice("Contratista registrado y vinculado a la obra.");
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function createWorker(){
    if(!siteId||!companyId||!newWorker.name.trim()){setError("Selecciona empleador e indica el trabajador");return;}
    setBusy(true);setError("");
    try{
      const result=await opsApi.createWorker({site_id:siteId,contractor_id:companyId,name:newWorker.name,rut:newWorker.rut||null});
      const src=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId)+"&contractor_id="+encodeURIComponent(companyId));
      setSource(src);setWorkerId(result.worker_id);setShowCreate(null);setNewWorker({name:"",rut:""});
      setNotice("Trabajador vinculado al empleador.");
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function refreshDossier(id:string){
    const result=await request<Dossier>("/javiera/dossiers/"+id);setSaved(result);
  }
  async function saveDossier(){
    if(!mode||!companyId||!siteId){setError("Selecciona obra y empleador antes de guardar.");return;}
    setBusy(true);setError("");setNotice("");
    try{
      const result=await request<{id:string;revision:number}>("/javiera/dossiers",{
        method:"POST",body:JSON.stringify({site_id:siteId,employer_id:companyId,
          worker_id:workerId||null,parent_id:mode==="subcontractor"?parentId:null,
          relationship:mode,data:{...data,...(dossierId?{_dossier_id:dossierId}:{})},
          expected_revision:dossierId?dossierRevision:null})});
      setDossierId(result.id);setDossierRevision(result.revision);setSavedFingerprint(fingerprint);
      await refreshDossier(result.id);
      setNotice("Ficha guardada. Los PDF se generan de forma individual tras validación.");
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function openPreview(code:string){
    if(unsaved){setError("Guarda los cambios antes de generar una vista previa.");return;}
    setBusy(true);setError("");
    try{previewBlob(await pdfRequest("/preview",{dossier_id:dossierId,code}));}
    catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function issue(code:string,reissue_reason?:string){
    if(unsaved){setError("Guarda los cambios antes de emitir el PDF.");return;}
    setBusy(true);setError("");
    try{
      const result=await request<{id:string;reused:boolean}>("/javiera/issue",{
        method:"POST",body:JSON.stringify({dossier_id:dossierId,code,reissue_reason})});
      await refreshDossier(dossierId);setNotice(result.reused?"PDF existente recuperado.":"PDF emitido, aún sin firma ni constancia de entrega.");
      window.open("/api/v1/javiera/issued/"+encodeURIComponent(result.id)+"/pdf","_blank","noopener,noreferrer");
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function issueReady(){
    if(unsaved||busy){setError("Guarda primero los cambios del expediente.");return;}
    const codes=cards.filter(c=>c.can_issue).map(c=>c.code);
    if(!codes.length){setError("No hay documentos aprobados listos para emisión.");return;}
    setBusy(true);setError("");setNotice("");setBatchReport([]);
    try{
      const result=await request<{issued:number;failed:number;results:{code:string;ok:boolean;id?:string;reason?:string}[]}>
        ("/javiera/issue/batch",{method:"POST",
          body:JSON.stringify({dossier_id:dossierId,codes})});
      setBatchReport(result.results);
      await refreshDossier(dossierId);
      setNotice("Lote terminado: "+result.issued+" emitidos o recuperados; "+result.failed+
        " documentos con observaciones. La emisión no implica firma ni entrega.");
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function reviewHistorical(id:string,verified:boolean){
    const reason=reviewComments[id]?.trim()||"";
    if(reason.length<6){setError("Indica el motivo y evidencia de la revisión del documento histórico.");return;}
    setBusy(true);setError("");
    try{
      await request("/javiera/admin/history/"+encodeURIComponent(id)+"/verify",{
        method:"POST",body:JSON.stringify({verified,reason})});
      if(dossierId)await refreshDossier(dossierId);
      setNotice(verified?"Documento histórico revisado; comprueba su aplicabilidad actual.":"Documento histórico observado.");
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  async function uploadHistorical(code:string,file:File){
    if(!dossierId){setError("Guarda el expediente antes de subir documentos anteriores.");return;}
    const csrf=document.cookie.split("; ").find(c=>c.startsWith("galant_post_csrf="))?.split("=")[1]||"";
    const form=new FormData();form.append("file",file);
    setBusy(true);setError("");
    try{const res=await fetch("/api/v1/javiera/dossiers/"+encodeURIComponent(dossierId)+"/history/"+encodeURIComponent(code),{
        method:"POST",body:form,credentials:"include",headers:{"X-CSRF-Token":csrf}});
      if(!res.ok)throw new Error("No se pudo cargar el PDF histórico");
      await refreshDossier(dossierId);setNotice("Documento histórico cargado; pendiente de verificación.");
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  function chooseSite(v:string){setSiteId(v);setCompanyId("");setWorkerId("");setParentId("");setDossierId("");setSaved(null);setSavedFingerprint("");}
  function chooseCompany(v:string){setCompanyId(v);setWorkerId("");setDossierId("");setSaved(null);setSavedFingerprint("");}
  if(configuration)return <Setup onBack={onBack||(()=>window.history.back())}/>;
  if(!mode)return <section className="jv-module">
    <div className="jv-hero"><small>AUTOMATIZACIÓN DOCUMENTAL · GALANT 16</small><h2>Proyecto JAVIERA</h2>
      <p>Una sola ficha para documentos laborales y prevención de riesgos. Los documentos aparecen conforme completas los datos.</p></div>
    <div className="jv-mode-cards">
      <button onClick={()=>setMode("contractor")}><FolderOpen size={28}/><strong>Contratistas</strong>
        <span>Expedientes de empresas y trabajadores vinculados a cada obra.</span></button>
      <button onClick={()=>setMode("subcontractor")}><ShieldCheck size={28}/><strong>Subcontratos</strong>
        <span>Empleador directo, contratista principal y documentos por trabajador.</span></button>
    </div>
    <p className="jv-note">La emisión no certifica por sí sola firma, recepción, capacitación ni entrega real de EPP.</p>
  </section>;
  const ready=cards.filter(c=>c.can_issue).length;
  const groups=["Zona Subcontratos","Prevención de Riesgos"];
  return <section className="jv-module">
    <div className="jv-hero" style={{display:"grid",gridTemplateColumns:"minmax(0, 1fr)",gridAutoFlow:"row",justifyItems:"start",alignContent:"start",rowGap:9}}>
      <div className="jv-hero-back-row" style={{display:"block",width:"100%",minHeight:31,margin:0}}><button type="button" className="jv-back" onClick={()=>{setMode(null);setDossierId("");setSaved(null);}}><ArrowLeft size={18}/> Proyecto JAVIERA</button></div>
      <small style={{display:"block",gridColumn:1}}>{mode==="contractor"?"CONTRATISTAS":"SUBCONTRATOS"} · EXPEDIENTE</small>
      <h2>Generación documental interactiva</h2><p>Selecciona registros existentes y completa solo los antecedentes del documento que necesitas.</p></div>
    {error&&<p role="alert" className="jv-error"><AlertCircle size={16}/>{error}</p>}
    {notice&&<p role="status" className="jv-success"><CheckCircle2 size={16}/>{notice}</p>}
    <div className="jv-workspace">
      <div className="jv-form">
        <div className="jv-section"><h3>1. Empresa y trabajador</h3>
          <label>Obra <select value={siteId} onChange={e=>chooseSite(e.target.value)}><option value="">Selecciona una obra</option>
            {source.sites.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label>
          <label>Empleador directo <select value={companyId} onChange={e=>chooseCompany(e.target.value)}>
            <option value="">Selecciona la empresa</option>{source.contractors.filter(c=>c.site_id===siteId).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <button type="button" className="jv-inline-action" onClick={()=>setShowCreate(showCreate==="contractor"?null:"contractor")}>+ Registrar contratista nuevo</button>
          {showCreate==="contractor"&&<div className="jv-new-form">
            <label>Nombre de empresa<input value={newContractor.name} onChange={e=>setNewContractor({...newContractor,name:e.target.value})}/></label>
            <label>RUT de empresa<input value={newContractor.rut} onChange={e=>setNewContractor({...newContractor,rut:e.target.value})}/></label>
            <button disabled={busy||!siteId} type="button" onClick={()=>void createCompany()}>Guardar empresa</button>
          </div>}
          {mode==="subcontractor"&&<label>Contratista principal <select value={parentId} onChange={e=>setParentId(e.target.value)}>
            <option value="">Selecciona el contratista principal</option>{source.contractors.filter(c=>c.id!==companyId&&c.site_id===siteId).map(c=>
              <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
          <label>Trabajador <select value={workerId} onChange={e=>{setWorkerId(e.target.value);setDossierId("");setSaved(null);}}>
            <option value="">Selecciona trabajador asignado a esta obra</option>
            {source.workers.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
          <button type="button" className="jv-inline-action" onClick={()=>setShowCreate(showCreate==="worker"?null:"worker")}>+ Registrar trabajador nuevo</button>
          {showCreate==="worker"&&<div className="jv-new-form">
            <label>Nombre del trabajador<input value={newWorker.name} onChange={e=>setNewWorker({...newWorker,name:e.target.value})}/></label>
            <label>RUT del trabajador<input value={newWorker.rut} onChange={e=>setNewWorker({...newWorker,rut:e.target.value})}/></label>
            <button disabled={busy||!companyId} type="button" onClick={()=>void createWorker()}>Guardar trabajador</button>
          </div>}
          <p className="jv-hint">{workerId?"Trabajador asignado en GALANT":"Selecciona o registra el trabajador sin duplicar su RUT."}</p>
          {existingDossiers.length>0&&<label>Expediente anterior
            <select value={dossierId} onChange={e=>{if(e.target.value)void loadDossier(e.target.value);}}>
              <option value="">Selecciona expediente para recuperar</option>
              {existingDossiers.filter(d=>d.relationship===mode&&(!workerId||d.worker_id===workerId)).map(d=>
                <option key={d.id} value={d.id}>Expediente {d.id.slice(0,8)} · revisión {d.revision}</option>)}
            </select></label>}
          <label>Vínculo laboral <select value={employmentType} onChange={e=>setEmploymentType(e.target.value)}>
            <option value="">Por determinar</option><option value="dependiente">Contrato laboral dependiente</option>
            <option value="independiente">Independiente (sin vínculo dependiente acreditado)</option></select></label>
          {fieldInput("role","Cargo o especialidad",role,setRole)}
          <label>Motivo del expediente <select value={eventType} onChange={e=>setEventType(e.target.value)}>
            {eventOptions.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        </div>
        <div className="jv-section"><h3>2. Datos contractuales</h3>
          <div className="jv-paired">
            {fieldInput("contract.start","Fecha de ingreso",contract.start,v=>setContract({...contract,start:v}),"date")}
            {fieldInput("contract.end","Término actual",contract.end,v=>setContract({...contract,end:v}),"date")}
            {fieldInput("contract.new_end","Nueva fecha de término",contract.new_end,v=>setContract({...contract,new_end:v}),"date")}
            {fieldInput("contract.transfer_date","Fecha de traslado",contract.transfer_date,v=>setContract({...contract,transfer_date:v}),"date")}
            {fieldInput("contract.salary","Sueldo base (CLP)",contract.salary,v=>setContract({...contract,salary:v}),"number")}
            {fieldInput("contract.hours","Horas semanales",contract.hours,v=>setContract({...contract,hours:v}),"number")}
          </div>
          {fieldInput("contract.declaration_reason","Motivo de declaración jurada",contract.declaration_reason,v=>setContract({...contract,declaration_reason:v}))}
          {fieldInput("contract.regulation_version","Versión del Reglamento Interno",contract.regulation_version,v=>setContract({...contract,regulation_version:v}))}
        </div>
        <div className="jv-section"><h3>3. Eventos y constancias</h3>
          <p>Una fecha rellenada no reemplaza la evidencia de una entrega, firma o inducción real.</p>
          {fieldInput("event.date","Fecha efectiva del evento",event.date,v=>setEvent({...event,date:v}),"date")}
          {fieldInput("event.epp_items","EPP entregados realmente",event.epp_items,v=>setEvent({...event,epp_items:v}))}
          {fieldInput("event.pts_version","Versión del PTS entregado",event.pts_version,v=>setEvent({...event,pts_version:v}))}
        </div>
        {catalog.some(c=>c.required_fields.some(f=>f.startsWith("extra.")))&&<div className="jv-section">
          <h3>4. Campos personalizados</h3><p>Estos campos se administran desde Configuración de automatización.</p>
          {Array.from(new Set(catalog.flatMap(c=>c.required_fields.filter(f=>f.startsWith("extra."))))).map(f=>
            fieldInput(f,f.slice(6).replaceAll("_"," "),extra[f.slice(6)]||"",
              value=>setExtra(old=>({...old,[f.slice(6)]:value}))))}
        </div>}
        <div className="jv-actions"><button type="button" className="jv-primary" disabled={busy||!siteId||!companyId}
          onClick={()=>void saveDossier()}>{busy?"Procesando…":dossierId?"Guardar nueva revisión":"Guardar expediente"}</button>
          {dossierId&&<span>Expediente {dossierId.slice(0,8)} · revisión {dossierRevision}{unsaved?" · cambios sin guardar":""}</span>}
        </div>
      </div>
      <aside className="jv-document-panel" aria-label="Documentos que puedes exportar a PDF">
        {unsaved&&<p className="jv-note" role="status">Guarda los cambios para habilitar la exportación de PDFs.</p>}
        <div className="jv-panel-head"><div><small>GENERACIÓN EN VIVO</small><h3>Documentos que puedes exportar a PDF</h3>
          <p>Actualización automática al completar datos</p></div><strong>{ready} listos</strong></div>
        <button type="button" className="jv-primary jv-batch" disabled={unsaved||busy||ready===0}
          onClick={()=>void issueReady()}>Generar documentos listos ({ready})</button>
        {batchReport.length>0&&<div className="jv-batch-report" role="status">
          {batchReport.map(item=><p key={item.code}>{item.ok?"✓":"!"} {catalog.find(c=>c.code===item.code)?.title||item.code}
            {item.ok&&item.id?<a target="_blank" rel="noreferrer"
              href={"/api/v1/javiera/issued/"+encodeURIComponent(item.id)+"/pdf"}>Abrir PDF</a>:
              <span>{item.reason||"Pendiente de revisión"}</span>}</p>)}
        </div>}
        <div className="jv-filters">{[["todos","Todos"],["listos","Listos"],["pendientes","Pendientes"],["historicos","Existentes"]].map(([v,l])=>
          <button key={v} className={filter===v?"active":""} onClick={()=>setFilter(v)}>{l}</button>)}</div>
        {groups.map(area=><div key={area} className="jv-doc-area">
          <h4>{area==="Zona Subcontratos"?<FolderOpen size={17}/>:<ShieldCheck size={17}/>} {area}</h4>
          {cards.filter(c=>c.area===area && (filter==="todos" || filter==="listos"&&c.can_issue ||
            filter==="pendientes"&&!c.can_issue&&!c.has_history ||
            filter==="historicos"&&c.has_history)).map(c=><article className="jv-doc-card" key={c.code}>
            <div className="jv-doc-title"><FileText size={17}/><b>{c.title}</b><span className={"jv-state jv-"+c.status.toLowerCase()}>{statusText[c.status]||c.status}</span></div>
            <div className="jv-progress"><span style={{width:String(c.completion_percent)+"%"}}/></div>
            {c.reason&&<p>{c.reason}</p>}
            {!!c.missing_fields.length&&<p>Faltan: {c.missing_fields.slice(0,3).join(", ")}{c.missing_fields.length>3?"…":""}</p>}
            {!!c.blocking_errors.length&&<p className="jv-text-danger">{c.blocking_errors.join("; ")}</p>}
            <div className="jv-card-actions">
              <button disabled={!c.can_preview||unsaved||busy} onClick={()=>void openPreview(c.code)}>Vista previa</button>
              <button disabled={!c.can_issue||unsaved||busy} onClick={()=>void issue(c.code)}><Download size={14}/> PDF</button>
              {c.status==="EXISTENTE_POR_VERIFICAR"&&c.can_preview&&<div className="jv-reissue">
                <label>Motivo de nueva emisión
                  <textarea rows={2} placeholder="Describe qué cambió y por qué es necesario emitir otra versión"
                    value={reissueReasons[c.code]||""}
                    onChange={e=>setReissueReasons(old=>({...old,[c.code]:e.target.value}))}/>
                </label>
                <button type="button" disabled={unsaved||busy||(reissueReasons[c.code]||"").trim().length<20}
                  onClick={()=>void issue(c.code,reissueReasons[c.code].trim())}>Emitir nueva versión justificada</button>
              </div>}
              {dossierId&&<label className="jv-upload"><Upload size={14}/> Anterior<input type="file" accept=".pdf,application/pdf"
                onChange={e=>{const f=e.target.files?.[0];if(f)void uploadHistorical(c.code,f);e.target.value="";}}/></label>}
              {saved?.historical.filter(x=>x.code===c.code).map(h=><div key={h.id} className="jv-history-review">
                <strong>PDF anterior: {h.state==="verified"?"verificado":h.state==="rejected"?"observado":"pendiente de revisar"}</strong>
                {h.state==="pending"&&<>
                  <input aria-label="Motivo de revisión" placeholder="Evidencia y motivo de revisión" value={reviewComments[h.id]||""}
                    onChange={e=>setReviewComments({...reviewComments,[h.id]:e.target.value})}/>
                  <button disabled={busy} onClick={()=>void reviewHistorical(h.id,true)}>Validar antecedente</button>
                  <button disabled={busy} onClick={()=>void reviewHistorical(h.id,false)}>Observar</button>
                </>}
              </div>)}
              {saved?.issues.filter(x=>x.code===c.code).map(issue=><a key={issue.id} href={"/api/v1/javiera/issued/"+encodeURIComponent(issue.id)+"/pdf"}
                target="_blank" rel="noreferrer">Emitido v{issue.version}</a>)}
            </div>
          </article>)}
        </div>)}
        <p className="jv-note">Documentos anteriores: existencia no equivale a vigencia. Su verificación es independiente.</p>
      </aside>
    </div>
  </section>;
}
