import {useCallback, useEffect, useState} from "react";
import {ArrowLeft, CheckCircle2, FileCheck2, FileSpreadsheet, FileUp,
  Loader2, Printer, ShieldCheck, AlertTriangle, Eye, SlidersHorizontal} from "lucide-react";
import {request} from "./api";
import JavieraV166 from "./JavieraV166";
import "./javiera-v17.css";

type Template={
  code:string;title:string;sheet:string;specialty:"laboral"|"prevencion";
  state:"not_imported"|"draft"|"missing_storage"|"engine_unavailable"|"published";
  message:string;ready:boolean;imported:boolean;latest_revision:number|null;
  approved_revision:number|null;layout_id:string|null;can_preview:boolean;
};
type Library={documents:Template[];total:number;imported:number;published:number;
  awaiting_review:number;engine_available:boolean;requires_human_approval:boolean};
type UploadResult={status:"already_imported"|"imported_as_draft";created:number;matched:number;
  message:string;library:Library};
type PdfAudit={layout_id:string;code:string;sheet:string;revision:number;pages:number;
  formula_count:number;merged_ranges:number;configured_print_area:string;
  passed:boolean;message:string;requires_human_approval:boolean;out_of_bounds:{page:number;side:string}[]};
const endpoint="/api/v1/javiera/v17";
function problem(error:unknown){
  if(!(error instanceof Error))return String(error);
  return error.message;
}
function label(state:Template["state"]){
  return state==="published"?"Aprobada":state==="draft"?"Pendiente de revisión":
    state==="missing_storage"?"Archivo no disponible":
    state==="engine_unavailable"?"Motor PDF pendiente":"Lista para importar";
}
function tabLabel(specialty:Template["specialty"]){return specialty==="laboral"?"Subcontratos":"Prevención de riesgos";}

export default function JavieraV17({onConfig}:{onConfig?:()=>void}){
  const [mode,setMode]=useState<"library"|"documents">("library");
  const [data,setData]=useState<Library|null>(null);
  const [loading,setLoading]=useState(true);
  const [uploading,setUploading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [audits,setAudits]=useState<Record<string,PdfAudit>>({});
  const [checking,setChecking]=useState("");
  const [selectedArea,setSelectedArea]=useState<"all"|"laboral"|"prevencion">("all");
  const load=useCallback(async()=>{
    try{
      const result=await request<Library>("/javiera/v17/library");
      setData(result);setError("");
    }catch(err){setError(problem(err));}
    finally{setLoading(false);}
  },[]);
  useEffect(()=>{void load();},[load]);
  async function importPreparedWorkbook(file:File){
    if(!file.name.toLowerCase().endsWith(".xlsx")){
      setError("Selecciona el Excel original o la copia editable en formato .xlsx.");return;
    }
    setUploading(true);setError("");setNotice("");
    try{
      const form=new FormData();form.append("file",file);
      const csrf=document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
      const resp=await fetch(endpoint+"/library/import",{method:"POST",credentials:"include",
        headers:{"X-CSRF-Token":csrf},body:form});
      if(!resp.ok){
        const body=await resp.json().catch(()=>({detail:"La importación no pudo completarse."}));
        const detail=body.detail;
        if(typeof detail==="object"&&detail!==null&&"missing_sheets" in detail){
          const sheets=(detail as {missing_sheets?:string[]}).missing_sheets||[];
          throw new Error("Faltan hojas del Excel: "+sheets.join(", "));
        }
        throw new Error(typeof detail==="string"?detail:"No se pudo validar el Excel.");
      }
      const outcome=await resp.json() as UploadResult;
      setData(outcome.library);
      setNotice(outcome.message+" Abre la vista previa y solicita la revisión de un responsable.");
    }catch(err){setError(problem(err));}
    finally{setUploading(false);}
  }
  async function checkTemplate(item:Template){
    if(!item.layout_id)return;
    setChecking(item.code);setError("");
    try{
      const result=await request<PdfAudit>("/javiera/v18/layouts/"+item.layout_id+"/check",{
        method:"POST",body:JSON.stringify({})
      });
      setAudits(old=>({...old,[item.code]:result}));
    }catch(e){setError("Error al revisar "+item.title+": "+problem(e));}
    finally{setChecking("");}
  }
  const entries=(data?.documents||[]).filter(x=>selectedArea==="all"||x.specialty===selectedArea);
  if(mode==="documents")return <div className="j17-shell">
    <button className="j17-back" onClick={()=>{setMode("library");void load();}}>
      <ArrowLeft size={16}/> Biblioteca de plantillas</button>
    <JavieraV166 onConfig={()=>{setMode("library");void load();}}/>
  </div>;
  return <main className="j17-shell">
    <header className="j17-hero">
      <div><span>GALANT 18 · PROYECTO JAVIERA</span>
        <h2>Biblioteca documental inteligente</h2>
        <p>Las diez plantillas de tu Excel en un único lugar. Se cargan una sola vez;
          luego completas datos y generas PDF sin reescribir documentos.</p>
      </div><FileSpreadsheet size={35} aria-hidden="true"/>
    </header>
    {error&&<p className="j17-error" role="alert"><AlertTriangle size={18}/>{error}</p>}
    {notice&&<p className="j17-ok" role="status"><CheckCircle2 size={18}/>{notice}</p>}
    {loading?<div className="j17-loading"><Loader2 size={20}/> Consultando biblioteca privada…</div>:
      <section className="j17-upload" aria-label="Importación de plantillas">
        <div><h3>1. Importar el Excel preparado</h3>
          <p>Selecciona <b>GALANT_JAVIERA_18_10_PLANTILLAS_CORREGIDAS.xlsx</b> o una versión
            corregida. GALANT reconocerá las diez hojas y preparará sus borradores automáticamente.</p>
          <small>Las plantillas se guardan exclusivamente en el servidor privado de tu organización.
            No se incorporan trabajadores ni contratistas a otros módulos.</small>
        </div>
        <label className={"j17-file "+(uploading?"busy":"")}>
          <FileUp size={18}/> {uploading?"Importando y vinculando…":"Cargar 10 plantillas"}
          <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={uploading}
            onChange={e=>{const file=e.target.files?.[0];if(file)void importPreparedWorkbook(file);e.target.value="";}}/>
        </label>
      </section>}
    {data&&<>
      <section className="j17-summary" aria-label="Estado de la biblioteca">
        <div><small>Hojas reconocidas</small><strong>{data.total}/10</strong></div>
        <div><small>Plantillas importadas</small><strong>{data.imported}/10</strong></div>
        <div><small>Aprobadas para emisión</small><strong>{data.published}/10</strong></div>
        <div><small>Pendientes de revisar</small><strong>{data.awaiting_review}</strong></div>
      </section>
      {!data.engine_available&&<p className="j17-error"><AlertTriangle size={17}/>
        El motor de PDF LibreOffice no está disponible en el servidor. Debe configurarse antes de imprimir.</p>}
      <section className="j17-board">
        <div className="j17-board-head"><div><h3>2. Revisar las plantillas detectadas</h3>
          <p>No necesitas transcribir su contenido. Puedes editar el Excel original y volverlo a importar si encuentras algo que corregir.</p></div>
          <div className="j17-filter" role="group" aria-label="Filtrar documentos">
            {(["all","laboral","prevencion"] as const).map(item=>
              <button type="button" key={item} className={selectedArea===item?"active":""}
                onClick={()=>setSelectedArea(item)}>{item==="all"?"Todos":tabLabel(item)}</button>)}
          </div>
        </div>
        <div className="j17-grid">
          {entries.map(item=><article className="j17-document" key={item.code}>
            <div className="j17-doc-top">
              <FileCheck2 size={20} color="currentColor"/>
              <div><h4>{item.title}</h4><small>Hoja: {item.sheet} · {tabLabel(item.specialty)}</small></div>
            </div>
            <div className={"j17-status "+item.state}>
              {item.ready?<CheckCircle2 size={15}/>:<AlertTriangle size={15}/>}
              {label(item.state)} {item.latest_revision?"· v"+item.latest_revision:""}
            </div>
            <p>{item.message}</p>
            <div className="j17-doc-actions">
              {item.can_preview&&item.layout_id&&
                <a href={"/api/v1/javiera/admin/excel/layouts/"+item.layout_id+"/preview"}
                  target="_blank" rel="noreferrer"><Eye size={15}/> Vista previa PDF</a>}
              {item.layout_id&&item.imported&&<button className="j17-outline" type="button"
                disabled={checking===item.code} onClick={()=>void checkTemplate(item)}>
                {checking===item.code?"Comprobando PDF…":"Validar fórmulas y PDF"}</button>}
              {audits[item.code]&&<p role="status" className={audits[item.code].passed?"j17-check-ok":"j17-check-error"}>
                {audits[item.code].passed?"PDF de prueba correcto":"Revisión fallida"} ·
                {audits[item.code].pages} página(s) ·
                {audits[item.code].formula_count} fórmulas ·
                área {audits[item.code].configured_print_area}
              </p>}
              {!item.imported&&<span className="j17-muted">Incluida al importar el Excel</span>}
            </div>
          </article>)}
        </div>
      </section>
      <section className="j17-finish">
        <div><h3>3. Revisar, aprobar y utilizar</h3>
          <p>El responsable laboral o de prevención revisa la versión una vez y registra su aprobación.
            Los documentos emitidos después utilizan automáticamente esa versión, sin volver a editarla.</p>
          <p className="j17-small">La carga no equivale a aprobación. Generar un PDF tampoco acredita
            firma, recepción, entrega de EPP o realización de una inducción.</p>
        </div>
        <div className="j17-final-actions">
          {onConfig&&<button type="button" className="j17-outline" onClick={onConfig}>
            <SlidersHorizontal size={16}/> Revisar o modificar plantillas</button>}
          <button type="button" className="j17-primary" onClick={()=>setMode("documents")}>
            <Printer size={16}/> Preparar documentos</button>
        </div>
      </section>
    </>}
  </main>;
}
