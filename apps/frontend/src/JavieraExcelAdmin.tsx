import {useEffect, useMemo, useState} from "react";
import {CheckCircle2, FileSpreadsheet, FileText, ShieldCheck, Upload} from "lucide-react";
import {request} from "./api";
import "./javiera-excel.css";

type Layout={
  id:string;code:string;sheet:string;revision:number;status:string;
  inventory:{cells:number;merged:number;formulas:number;page_breaks:number};
  cells_modified:number;author_id:string;reviewer_id:string|null;
};
type SourceCell={cell:string;row:number;value:string;formula:string|null;style:string|null;modified:boolean};
type CellPage={id:string;sheet:string;revision:number;status:string;start_row:number;max_rows:number;
  cells:SourceCell[];merged:string[];has_more:boolean};
type Reviewer={user_id:string;name:string;specialties:{specialty:string;active:boolean;designation:string}[]};
type Checklist={specialty:string;requirements:string[];legal_reference:string};
type Template={code:string;title:string;revisions:{revision:number;state:string;author_id:string;id:string}[]};
type Matrix={id:string;kind:string;cargo:string;revision:number;status:string;author_id:string};
type Resource={kind:"template"|"matrix"|"excel_layout";id:string;label:string;
  specialty:"laboral"|"prevencion";state:string;author_id:string;code?:string;revision?:number};
type ReviewResult={verdict:string;reviewer_id:string;comments:string;created_at:string}[];
const codeLabels:Record<string,string>={
  labor_contract:"Contrato de trabajo",transfer_addendum:"Anexo de traslado",
  sworn_declaration:"Declaración jurada",extension_addendum:"Anexo extensión de contrato",
  internal_rules_receipt:"Recepción reglamento",ppe_delivery:"Entrega EPP",
  irl:"IRL",pts:"Procedimiento trabajo seguro",pts_receipt:"Recepción PTS",
  induction:"Inducción de prevención"
};
const specialty=(code:string):"laboral"|"prevencion"=>
  ["labor_contract","transfer_addendum","sworn_declaration","extension_addendum"].includes(code)?"laboral":"prevencion";
const label=(key:string)=>key.replaceAll("_"," ").replaceAll("y ","y ");
const errorText=(e:unknown)=>e instanceof Error?e.message:String(e);
const csrf=()=>document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
async function upload(file:File,path:string){
  const body=new FormData();body.append("file",file);
  const response=await fetch("/api/v1/javiera"+path,{method:"POST",credentials:"include",
    headers:{"X-CSRF-Token":csrf()},body});
  if(!response.ok){
    const x=await response.json().catch(()=>({detail:"No se pudo importar"}));
    throw new Error(typeof x.detail==="string"?x.detail:"El archivo no cumple los requisitos");
  }
  return response.json() as Promise<unknown>;
}
async function showPDF(path:string){
  const response=await fetch("/api/v1/javiera"+path,{credentials:"include",cache:"no-store"});
  if(!response.ok)throw new Error("No se pudo generar la vista previa del Excel");
  const blob=await response.blob();
  const url=URL.createObjectURL(blob);
  window.open(url,"_blank","noopener,noreferrer");
  window.setTimeout(()=>URL.revokeObjectURL(url),60000);
}

function LayoutStudio(){
  const [layouts,setLayouts]=useState<Layout[]>([]);
  const [selected,setSelected]=useState("");
  const [source,setSource]=useState<CellPage|null>(null);
  const [start,setStart]=useState(1);
  const [cell,setCell]=useState("");
  const [content,setContent]=useState("");
  const [styleFrom,setStyleFrom]=useState("");
  const [height,setHeight]=useState("");
  const [reason,setReason]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [engine,setEngine]=useState<{available:boolean;engine:string}|null>(null);
  const [uploadReport,setUploadReport]=useState("");
  const current=layouts.find(x=>x.id===selected)||null;
  async function refresh(){
    const list=await request<Layout[]>("/javiera/admin/excel/layouts");
    setLayouts(list);
    setSelected(old=>list.some(x=>x.id===old)?old:(list[0]?.id||""));
  }
  useEffect(()=>{void Promise.all([refresh(),request<{available:boolean;engine:string}>("/javiera/admin/excel/status").then(setEngine)])
    .catch(e=>setError(errorText(e)));},[]);
  useEffect(()=>{
    if(!selected)return;
    let alive=true;
    request<CellPage>("/javiera/admin/excel/layouts/"+encodeURIComponent(selected)+"/cells?start_row="+start+"&max_rows=45")
      .then(v=>{if(alive)setSource(v);}).catch(e=>{if(alive)setError(errorText(e));});
    return()=>{alive=false;};
  },[selected,start]);
  async function importExcel(file:File){
    setBusy(true);setError("");setNotice("");
    try{
      const result=await upload(file,"/admin/excel/import") as {templates:{sheet:string;cells:number}[];missing:string[]};
      setUploadReport(result.templates.length+" hojas documentales importadas · "+result.templates.reduce((n,x)=>n+x.cells,0)+" celdas con contenido · "+
        (result.missing.length?result.missing.length+" hojas por revisar":"sin hojas pendientes"));
      setNotice("Las plantillas conservan estilos, celdas combinadas, imágenes y áreas de impresión. Deben revisarse y aprobarse.");
      await refresh();
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  function choose(row:SourceCell){
    setCell(row.cell);setContent(row.value||"");setStyleFrom("");setHeight("");
  }
  async function save(){
    if(!current||!cell)return;
    if(reason.trim().length<10){setError("Explica por qué cambias la celda (mínimo 10 caracteres).");return;}
    setBusy(true);setError("");setNotice("");
    try{
      const edit:{coordinate:string;text:string;style_from?:string;row_height?:number}={
        coordinate:cell,text:content
      };
      if(styleFrom)edit.style_from=styleFrom;
      if(height)edit.row_height=Number(height);
      const result=await request<{id:string;revision:number}>("/javiera/admin/excel/layouts/"+current.id+"/revise",{
        method:"POST",body:JSON.stringify({expected_revision:current.revision,edits:[edit],reason})});
      await refresh();setSelected(result.id);setNotice("Nueva versión guardada. Requiere revisión profesional.");
      setReason("");
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function approve(){
    if(!current)return;
    setBusy(true);setError("");
    try{
      await request("/javiera/admin/excel/layouts/"+current.id+"/approve",{method:"POST"});
      await refresh();setNotice("Plantilla publicada. Las emisiones anteriores permanecen intactas.");
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  return <section className="jvx">
    <header className="jvx-intro">
      <div><span className="jvx-kicker">IMPORTACIÓN CON FORMATO ORIGINAL</span><h2>Diseñador de documentos Excel</h2>
        <p>Conserva las hojas originales y su diseño para PDF. Corrige cualquier celda desde este panel y crea revisiones independientes.</p></div>
      <div className="jvx-engine">{engine?.available?<><CheckCircle2 size={15}/> Motor Excel listo</>:"Motor LibreOffice no instalado"}</div>
    </header>
    {error&&<p className="jv-error" role="alert">{error}</p>}{notice&&<p className="jv-success" role="status">{notice}</p>}
    <div className="jvx-upload">
      <FileSpreadsheet size={22}/>
      <div><b>Importar Excel corregido de JAVIERA</b><p>Los archivos quedan en almacenamiento privado del servidor. No se suben al repositorio público.</p></div>
      <label className="jvx-attach"><Upload size={16}/> {busy?"Procesando…":"Elegir archivo .xlsx"}
        <input type="file" accept=".xlsx" disabled={busy} onChange={e=>{const f=e.target.files?.[0];if(f)void importExcel(f);e.target.value="";}}/>
      </label>
    </div>
    {uploadReport&&<p className="jvx-report">{uploadReport}</p>}
    <div className="jvx-layout">
      <nav className="jvx-list" aria-label="Versiones de documentos importados">
        {layouts.map(x=><button key={x.id} className={selected===x.id?"active":""} onClick={()=>{setSelected(x.id);setStart(1);setCell("");}}>
          <FileText size={16}/><span>{codeLabels[x.code]||x.sheet}
          <small>{x.status==="approved"?"Publicado":x.status==="draft"?"Borrador":"Histórico"} · v{x.revision} · {x.cells_modified} correcciones</small></span></button>)}
        {!layouts.length&&<p>No hay diseños importados. Selecciona el Excel para comenzar.</p>}
      </nav>
      <section className="jvx-inspector">
        <div className="jvx-bar">
          <div><h3>{current?.sheet||"Selecciona documento"}</h3>
            {current&&<small>{current.inventory.cells} celdas · {current.inventory.merged} combinadas · {current.inventory.formulas} fórmulas</small>}</div>
          <div className="jvx-buttons">
            <button disabled={!current||busy||!engine?.available} onClick={()=>{if(current)void showPDF("/admin/excel/layouts/"+current.id+"/preview").catch(e=>setError(errorText(e)));}}>Vista previa PDF</button>
            {current?.status==="draft"&&<button disabled={busy} onClick={()=>void approve()}>Aprobar versión</button>}
          </div>
        </div>
        <div className="jvx-row-nav">
          <button disabled={start<=1} onClick={()=>setStart(x=>Math.max(1,x-45))}>Anterior</button>
          <span>Filas {start}–{start+44}</span>
          <button disabled={!source?.has_more} onClick={()=>setStart(x=>x+45)}>Siguiente</button>
        </div>
        <div className="jvx-cells">
          {(source?.cells||[]).map(x=><button key={x.cell} className={"jvx-cell "+(cell===x.cell?"active ":"")+(x.modified?"changed":"")} onClick={()=>choose(x)}>
            <span>{x.cell}</span><span>{x.value.slice(0,180)||"Fórmula o campo vacío"}</span>
            {x.formula&&<small>Fórmula del Excel</small>}</button>)}
          {!source?.cells.length&&<p>Sin contenido en este bloque de filas.</p>}
        </div>
      </section>
      <aside className="jvx-edit">
        <h3>Editor de celda</h3><p>Selecciona una celda a la izquierda. Puedes cambiar su texto y copiar el estilo de otra celda original.</p>
        {cell?<><strong>Celda {cell}</strong>
          <label>Contenido <textarea rows={10} value={content} onChange={e=>setContent(e.target.value)} /></label>
          <label>Copiar formato desde <input placeholder="Ej. A4" value={styleFrom} onChange={e=>setStyleFrom(e.target.value.toUpperCase())}/></label>
          <label>Alto de fila (10-120 pt) <input type="number" min="10" max="120" value={height} onChange={e=>setHeight(e.target.value)}/></label>
          <label>Motivo del ajuste <textarea rows={3} value={reason} onChange={e=>setReason(e.target.value)}/></label>
          <button className="jv-primary" disabled={busy||reason.trim().length<10||!current} onClick={()=>void save()}>
            Guardar nueva revisión</button></>:<p>Selecciona cualquier celda para modificar su contenido.</p>}
        <div className="jvx-legal-note"><ShieldCheck size={18}/><p>Los documentos laborales y preventivos requieren acta de revisión por el responsable designado antes de aprobarse para emisión.</p></div>
      </aside>
    </div>
  </section>;
}

function ReviewDesk(){
  const [reviewers,setReviewers]=useState<Reviewer[]>([]);
  const [checklists,setChecklists]=useState<Checklist[]>([]);
  const [resources,setResources]=useState<Resource[]>([]);
  const [selected,setSelected]=useState("");
  const [chosenReviewer,setChosenReviewer]=useState("");
  const [designation,setDesignation]=useState("");
  const [grantSpecialty,setGrantSpecialty]=useState<"laboral"|"prevencion">("laboral");
  const [check,setCheck]=useState<Record<string,boolean>>({});
  const [comments,setComments]=useState("");
  const [verdict,setVerdict]=useState<"approved"|"rejected">("approved");
  const [already,setAlready]=useState<ReviewResult>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const active=resources.find(x=>x.id===selected)||null;
  const criteria=checklists.find(x=>x.specialty===active?.specialty)||null;
  const name=(id:string)=>reviewers.find(r=>r.user_id===id)?.name||"Usuario registrado";
  async function refresh(){
    const [users,catalog,templates,matrices,layouts]=await Promise.all([
      request<Reviewer[]>("/javiera/admin/reviews/reviewers"),
      request<Checklist[]>("/javiera/admin/reviews/checklists"),
      request<Template[]>("/javiera/admin/templates"),
      request<Matrix[]>("/javiera/admin/matrices"),
      request<Layout[]>("/javiera/admin/excel/layouts")
    ]);
    setReviewers(users);setChecklists(catalog);
    const items:Resource[]=[];
    for(const t of templates)for(const v of t.revisions||[]){
      if(v.state==="draft" && v.id)items.push({kind:"template",id:v.id,
        label:(codeLabels[t.code]||t.title)+" · texto v"+v.revision,
        specialty:specialty(t.code),state:v.state,author_id:v.author_id,code:t.code,revision:v.revision});
    }
    for(const m of matrices.filter(x=>x.status==="draft"))items.push({
      kind:"matrix",id:m.id,label:m.kind+" · "+m.cargo+" · v"+m.revision,
      specialty:"prevencion",state:m.status,author_id:m.author_id});
    for(const x of layouts.filter(x=>x.status==="draft"))items.push({
      kind:"excel_layout",id:x.id,label:(codeLabels[x.code]||x.sheet)+" · diseño v"+x.revision,
      specialty:specialty(x.code),state:x.status,author_id:x.author_id,code:x.code,revision:x.revision});
    setResources(items);setSelected(id=>items.some(x=>x.id===id)?id:(items[0]?.id||""));
  }
  useEffect(()=>{void refresh().catch(e=>setError(errorText(e)));},[]);
  useEffect(()=>{
    if(!active)return;
    setAlready([]);setCheck({});
    void request<ReviewResult>("/javiera/admin/reviews/signoff/"+active.kind+"/"+active.id)
      .then(setAlready).catch(e=>setError(errorText(e)));
  },[selected,active?.kind]);
  async function grant(){
    setBusy(true);setError("");
    try{await request("/javiera/admin/reviews/reviewers",{method:"PUT",
      body:JSON.stringify({user_id:chosenReviewer,specialty:grantSpecialty,designation,active:true})});
      setNotice("Responsable designado. Debe revisar personalmente el contenido.");
      setReviewers(await request<Reviewer[]>("/javiera/admin/reviews/reviewers"));
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function signoff(){
    if(!active||!criteria)return;
    setBusy(true);setError("");
    try{
      await request("/javiera/admin/reviews/signoff",{method:"POST",body:JSON.stringify({
        resource_kind:active.kind,resource_id:active.id,specialty:active.specialty,
        verdict,checklist:Object.fromEntries(criteria.requirements.map(k=>[k,!!check[k]])),
        comments,regulatory_basis:criteria.legal_reference
      })});
      setAlready(await request<ReviewResult>("/javiera/admin/reviews/signoff/"+active.kind+"/"+active.id));
      setNotice("Acta de revisión registrada con el usuario responsable. Ahora puede solicitarse la publicación.");
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function publish(){
    if(!active)return;setBusy(true);setError("");
    const path=active.kind==="matrix"?"/javiera/admin/matrices/"+active.id+"/approve":
      active.kind==="excel_layout"?"/javiera/admin/excel/layouts/"+active.id+"/approve":
      "/javiera/admin/templates/"+active.code+"/approve/"+active.revision;
    try{await request(path,{method:"POST"});await refresh();
      setNotice("Versión aprobada y publicada; las emisiones históricas no se modificaron.");
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  return <section className="jvx">
    <header className="jvx-intro"><div><span className="jvx-kicker">TRAZABILIDAD PROFESIONAL</span><h2>Mesa de revisión laboral y preventiva</h2>
      <p>Dos responsables diferentes: quien redacta no puede aprobar. Solo una persona designada puede emitir actas de revisión de su especialidad.</p></div></header>
    {error&&<p role="alert" className="jv-error">{error}</p>}{notice&&<p role="status" className="jv-success">{notice}</p>}
    <div className="jvx-review-grid">
      <aside className="jvx-edit">
        <h3>Responsables autorizados</h3><p>La designación requiere otro administrador y una descripción de su función o acreditación.</p>
        {reviewers.map(x=><div className="jvx-reviewer" key={x.user_id}>
          <b>{x.name}</b><small>{x.specialties.filter(s=>s.active).map(s=>s.specialty).join(" · ")||"Sin especialidad autorizada"}</small>
        </div>)}
        <label>Designar a otro administrador
          <select value={chosenReviewer} onChange={e=>setChosenReviewer(e.target.value)}>
            <option value="">Seleccionar responsable</option>{reviewers.map(x=><option value={x.user_id} key={x.user_id}>{x.name}</option>)}
          </select></label>
        <label>Especialidad <select value={grantSpecialty} onChange={e=>setGrantSpecialty(e.target.value as "laboral"|"prevencion")}>
          <option value="laboral">Laboral / contratos</option><option value="prevencion">Prevención de riesgos</option></select></label>
        <label>Designación / respaldo <textarea rows={3} value={designation} onChange={e=>setDesignation(e.target.value)} /></label>
        <button disabled={busy||!chosenReviewer||designation.trim().length<12} onClick={()=>void grant()}>Registrar designación</button>
      </aside>
      <section className="jvx-review-main">
        <h3>Documentos y versiones pendientes</h3>
        <label>Seleccionar documento o matriz <select value={selected} onChange={e=>setSelected(e.target.value)}>
          <option value="">Seleccionar versión</option>{resources.map(x=><option value={x.id} key={x.id}>{x.label}</option>)}</select></label>
        {active&&criteria?<div className="jvx-review-form">
          <p><strong>Tipo:</strong> {active.specialty==="laboral"?"Revisión laboral":"Revisión de prevención"} · <strong>Autor:</strong> {name(active.author_id)}</p>
          <h4>Lista de comprobación obligatoria</h4>
          {criteria.requirements.map(k=><label className="jvx-check" key={k}>
            <input type="checkbox" checked={!!check[k]} onChange={e=>setCheck(old=>({...old,[k]:e.target.checked}))}/>
            <span>{label(k)}</span></label>)}
          <p className="jvx-source">Referencia normativa: {criteria.legal_reference}</p>
          <label>Conclusión <select value={verdict} onChange={e=>setVerdict(e.target.value as "approved"|"rejected")}>
            <option value="approved">Conforme, tras revisión real</option><option value="rejected">Observado / corregir</option>
          </select></label>
          <label>Fundamento, evidencias y observaciones <textarea rows={5} value={comments} onChange={e=>setComments(e.target.value)}
            placeholder="Detalla lo revisado, cómo se verificó, las modificaciones y por qué procede aprobar o rechazar"/></label>
          <div className="jvx-review-actions">
            <button className="jv-primary" disabled={busy||comments.trim().length<40||already.length>0||
              (verdict==="approved"&&!criteria.requirements.every(k=>check[k]))}
              onClick={()=>void signoff()}>Registrar acta responsable</button>
            <button disabled={busy||!already.some(r=>r.verdict==="approved")} onClick={()=>void publish()}>
              Publicar versión aprobada</button>
          </div>
          {already.map((r,i)=><div className="jvx-signoff" key={i}>
            <CheckCircle2 size={17}/> {r.verdict==="approved"?"Acta conforme":"Revisión observada"} · {name(r.reviewer_id)}
            <p>{r.comments}</p></div>)}
        </div>:<p>Selecciona una versión pendiente de revisión, o crea primero el borrador desde los otros editores.</p>}
      </section>
    </div>
  </section>;
}

export default function JavieraExcelAdmin({tab}:{tab:"excel"|"reviews"}){
  return tab==="excel"?<LayoutStudio/>:<ReviewDesk/>;
}
