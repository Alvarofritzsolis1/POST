import {useEffect,useMemo,useState} from "react";
import {ArrowRight,CheckCircle2,ClipboardList,FileSpreadsheet,Plus,Save,Search,ShieldCheck,Upload} from "lucide-react";
import {request} from "./api";
import {parseIRLClipboard,serializeIRLClipboard} from "./javiera-irl-clipboard";
import "./javiera-matrix-editor.css";

type Kind="IRL"|"PTS"|"PUESTOS"|"PERFILES"|"SUSTANCIAS";
type Matrix={id:string;kind:Kind;cargo:string;sections:string[];revision:number;status:string;source:string;author_id:string;source_row?:number};
type ReferenceCatalog={kind:Kind;rows:Matrix[];source_rows:number;columns:string[];variants:{cargo:string;source_rows:number[]}[];source_status:string};
type Impact={kind:Kind;cargo:string;new_pdf_formats:string[];affected_dossiers:number;
  count_is_partial:boolean;affected_by_origin:{historical_workflow:number;current_documentary_workflow:number};
  related_formats_for_review:string[];
  related_matrix_versions:{irl:number|null;pts:number|null};
  related_formats_are_advisory:boolean;
  current_approved_revision:number|null;latest_revision:number|null;
  pending_revisions:number[];historical_pdfs_unchanged:boolean;needs_explicit_review:boolean;message:string};
const kinds:Kind[]=["IRL","PTS","PERFILES","PUESTOS","SUSTANCIAS"];
const labels:Record<Kind,string>={IRL:"Riesgos laborales (IRL)",PTS:"Procedimientos seguros (PTS)",
  PERFILES:"Descripción de cargos",PUESTOS:"Matriz IRL optimizada",SUSTANCIAS:"Sustancias"};
type Preview={sha256:string;baseline_sha256:string;
  sheets_found:string[];sheets_missing:string[];irl_source_rows:number;
  pts_source_rows:number;formula_count:number;formula_count_partial:boolean;
  irl_embedded_images:number|null;irl_formula_count:number;
  formulas_by_sheet:Record<string,number>;
  formula_inventory:{sheet:string;cell:string;type:string;dependencies_a1_detected:string[];expression:string}[];
  formula_equivalence_verified:boolean;
  matrices:{kind:string;cargo:string;change:string;different_sections:number;current_revision:number|null}[];
  new:number;changed:number;unchanged:number;omissions:string[];warnings:string[];
  can_import:boolean;preview_only:boolean;message:string};
const names=["Tarea","Peligro","Riesgo","Medidas"];
const pattern=/^Tarea: ([\s\S]*?)\nPeligro: ([\s\S]*?)\nRiesgo: ([\s\S]*?)\nMedidas: ([\s\S]*)$/;
function splitSection(section:string):string[]|null{
  const match=section.match(pattern);return match?match.slice(1):null;
}
function withColumn(section:string,column:number,value:string){
  const parts=splitSection(section);
  if(!parts)return section;
  parts[column]=value;
  return names.map((name,index)=>name+": "+parts[index]).join("\n");
}
type ReviewFilter="all"|"approved"|"draft"|"incomplete"|"reference";
const hasMissingFields=(record:Matrix):boolean=>{
  if(!record.sections.length)return true;
  if(record.kind==="IRL")return record.sections.some(section=>{
    const fields=splitSection(section);
    return !fields||fields.some(field=>!field.trim());
  });
  if(record.kind==="PTS"&&record.sections.length!==17)return true;
  return record.sections.some(section=>!section.trim());
};
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);
function fingerprint(kind:Kind,cargo:string,sections:string[]){
  return JSON.stringify([kind,cargo,sections]);
}
export default function JavieraMatrixEditor(){
  const [rows,setRows]=useState<Matrix[]>([]);
  const [referenceRows,setReferenceRows]=useState<Matrix[]>([]);
  const [referenceColumns,setReferenceColumns]=useState<string[]>([]);
  const [referenceTotal,setReferenceTotal]=useState(0);
  const [referenceVariants,setReferenceVariants]=useState<{cargo:string;source_rows:number[]}[]>([]);
  const [referenceLoading,setReferenceLoading]=useState(false);
  const [kind,setKind]=useState<Kind>("IRL");
  const [search,setSearch]=useState("");
  const [reviewFilter,setReviewFilter]=useState<ReviewFilter>("all");
  const [selectedId,setSelectedId]=useState("");
  const [cargo,setCargo]=useState("");
  const [sections,setSections]=useState<string[]>([]);
  const [activeIRL,setActiveIRL]=useState(0);
  const [impact,setImpact]=useState<Impact|null>(null);
  const [impactFingerprint,setImpactFingerprint]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [soloPilot,setSoloPilot]=useState(false);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [importFile,setImportFile]=useState<File|null>(null);
  const [importPreview,setImportPreview]=useState<Preview|null>(null);
  const [importConfirmed,setImportConfirmed]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [bulkText,setBulkText]=useState("");
  const [bulkPreview,setBulkPreview]=useState<ReturnType<typeof parseIRLClipboard>|null>(null);
  const [bulkMode,setBulkMode]=useState<"replace"|"append">("replace");
  const [bulkUndo,setBulkUndo]=useState<string[]|null>(null);
  const allRows=useMemo(()=>[...rows,...referenceRows],[rows,referenceRows]);
  const current=allRows.find(x=>x.id===selectedId);
  const versions=useMemo(()=>allRows.filter(x=>x.kind===kind&&x.cargo===cargo)
    .sort((a,b)=>b.revision-a.revision),[allRows,kind,cargo]);
  const latest=useMemo(()=>{
    const seen=new Set<string>();
    return allRows.filter(row=>row.kind===kind).filter(row=>{
      // En Excel hay duplicados técnicos reales: conservar cada fila.
      const key=row.status==="reference"?"excel:"+row.id:"db:"+row.cargo;
      if(seen.has(key))return false;
      seen.add(key);return true;
    }).filter(row=>row.cargo.toLocaleLowerCase("es").includes(search.toLocaleLowerCase("es")))
      .filter(row=>reviewFilter==="all"||
        (reviewFilter==="incomplete"?hasMissingFields(row):
        reviewFilter==="reference"?row.status==="reference":row.status===reviewFilter));
  },[allRows,kind,search,reviewFilter]);
  const currentKindRows=useMemo(()=>rows.filter(row=>row.kind===kind),[rows,kind]);
  const reviewStats=useMemo(()=>({
    approved:currentKindRows.filter(row=>row.status==="approved").length,
    draft:currentKindRows.filter(row=>row.status==="draft"&&!hasMissingFields(row)).length,
    incomplete:allRows.filter(row=>row.kind===kind&&hasMissingFields(row)).length,
    reference:referenceRows.length,
  }),[currentKindRows,allRows,referenceRows,kind]);
  const pendingReview=useMemo(()=>currentKindRows.filter(row=>row.status==="draft"&&!hasMissingFields(row)),
    [currentKindRows]);
  const variant=referenceVariants.find(item=>item.cargo===cargo);
  const variantRows=referenceRows.filter(row=>variant?.source_rows.includes(row.source_row||-1));
  const variantIdentical=variantRows.length>1&&variantRows.every(row=>
    JSON.stringify(row.sections)===JSON.stringify(variantRows[0].sections));
  const missingIRL=useMemo(()=>kind==="IRL"?sections.flatMap((section,index)=>{
    const fields=splitSection(section);
    const missing=fields?fields.flatMap((value,i)=>!value.trim()?
      [["Actividad","Peligro","Consecuencia","Medidas preventivas"][i]]:[]):
      ["Estructura de las cuatro columnas"];
    return missing.length?[{index,fields:missing}]:[];
  }):[],[kind,sections]);
  const changed=!!current && (sections.length!==current.sections.length ||
    sections.some((s,i)=>s!==current.sections[i]));
  const approved=versions.find(r=>r.status==="approved");
  const changes=approved?Math.max(approved.sections.length,sections.length)===0?0:
    Array.from({length:Math.max(approved.sections.length,sections.length)},(_,i)=>
      approved.sections[i]!==sections[i]?1:0).filter(Boolean).length:sections.length;
  async function reload(pick?:string){
    const data=await request<Matrix[]>("/javiera/admin/matrices");
    setRows(data);
    if(pick){const record=data.find(row=>row.id===pick);if(record)selectRecord(record);}
  }
  useEffect(()=>{
    Promise.all([request<Matrix[]>("/javiera/admin/matrices"),
      request<{solo_pilot:boolean}>("/javiera/admin/excel/status").catch(()=>({solo_pilot:false}))])
      .then(([result,status])=>{setRows(result);setSoloPilot(status.solo_pilot);})
      .catch(e=>setError(errorText(e))).finally(()=>setLoading(false));
  },[]);
  useEffect(()=>{
    let active=true;
    setReferenceLoading(true);
    setReferenceRows([]);
    setReferenceColumns([]);
    void request<ReferenceCatalog>("/javiera/v194/reference-matrices?kind="+kind)
      .then(result=>{
        if(!active)return;
        setReferenceRows(result.rows);
        setReferenceColumns(result.columns);
        setReferenceTotal(result.source_rows);
        setReferenceVariants(result.variants);
        // Presentar contenido real del Excel automáticamente, sin
        // cargar archivos ni crear matrices aprobadas por accidente.
        if(result.rows.length>0&&!selectedId)selectRecord(result.rows[0]);
      })
      .catch(e=>{if(active)setError(errorText(e));})
      .finally(()=>{if(active)setReferenceLoading(false);});
    return()=>{active=false;};
  },[kind]);
  function invalidate(){setImpact(null);setImpactFingerprint("");setConfirmed(false);}
  function resetPaste(){setBulkText("");setBulkPreview(null);setBulkUndo(null);}
  function checkPaste(){
    try{setBulkPreview(parseIRLClipboard(bulkText));setError("");}
    catch(e){setBulkPreview(null);setError(errorText(e));}
  }
  function applyPaste(){
    if(!bulkPreview||kind!=="IRL")return;
    const merged=bulkMode==="replace"?bulkPreview.sections:[...sections,...bulkPreview.sections];
    if(merged.length>1500){setError("El resultado supera 1.500 labores.");return;}
    setBulkUndo([...sections]);setSections(merged);setActiveIRL(0);invalidate();
    setMessage(bulkPreview.sections.length+" labores cargadas en el editor, sin guardar ni aprobar. "+
      bulkPreview.duplicates+" duplicados idénticos omitidos en el pegado.");
    setBulkPreview(null);setBulkText("");setError("");
  }
  async function copySections(){
    if(kind!=="IRL")return;
    const tsv=serializeIRLClipboard(sections.map(section=>
      splitSection(section)||["","","",section]));
    try{await navigator.clipboard.writeText(tsv);setMessage("Matriz copiada al portapapeles.");}
    catch{setError("No se pudo copiar: revisa el permiso del portapapeles.");}
  }
  function selectRecord(row:Matrix){
    setKind(row.kind);setCargo(row.cargo);setSections([...row.sections]);setSelectedId(row.id);setActiveIRL(0);
    resetPaste();
    invalidate();setError("");setMessage("");
  }
  function newRecord(){
    setCargo("");setSelectedId("");setActiveIRL(0);setReviewFilter("all");resetPaste();
    setSections(kind==="PTS"?Array(17).fill(""):kind==="IRL"?
      ["Tarea: \nPeligro: \nRiesgo: \nMedidas: "]:[""]);invalidate();
    setMessage("Cargo nuevo: el primer guardado será una revisión en borrador.");
  }
  function selectKind(value:Kind){
    // Seleccionar de nuevo la misma categoría no debe borrar el cargo ni
    // sus riesgos. React no repite el efecto dependiente de `kind` si
    // su valor no cambia; antes esto dejaba una fila IRL vacía.
    if(value===kind)return;
    setKind(value);setSelectedId("");setCargo("");setActiveIRL(0);setReviewFilter("all");resetPaste();
    setSections(value==="PTS"?Array(17).fill(""):value==="IRL"?
      ["Tarea: \nPeligro: \nRiesgo: \nMedidas: "]:[""]);invalidate();
  }
  function edit(index:number,value:string){
    setSections(prev=>prev.map((section,i)=>i===index?value:section));invalidate();
  }
  async function previewImpact(){
    if(cargo.trim().length<2){setError("Indica el cargo antes de revisar el impacto.");return;}
    setBusy(true);setError("");
    const shot=fingerprint(kind,cargo,sections);
    try{
      const item=await request<Impact>("/javiera/v192/matrix-impact?kind="+
        encodeURIComponent(kind)+"&cargo="+encodeURIComponent(cargo));
      setImpact(item);setImpactFingerprint(shot);setConfirmed(false);
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function save(){
    if(!impact||!confirmed||impactFingerprint!==fingerprint(kind,cargo,sections)){
      setError("Revisa el impacto actualizado y confirma antes de guardar.");return;
    }
    if(kind==="PTS"&&(sections.length!==17||sections.some(s=>!s.trim()))){
      setError("El PTS debe conservar exactamente sus 17 apartados completos.");return;
    }
    if(sections.some(s=>!s.trim())){setError("Completa o elimina las filas vacías antes de guardar.");return;}
    setBusy(true);setError("");setMessage("");
    try{
      const result=await request<{id:string;revision:number;status:string}>("/javiera/admin/matrices",{
        method:"POST",body:JSON.stringify({kind,cargo,sections,source:"Editor visual GALANT 19.4.1"})
      });
      await reload(result.id);
      invalidate();
      setMessage("Revisión "+result.revision+" guardada como borrador. La matriz aprobada sigue vigente hasta revisión.");
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function enable(){
    if(!current||current.status!=="draft")return;
    if(!confirmed || !impact || impactFingerprint!==fingerprint(kind,cargo,sections)){
      setError("Confirma el impacto antes de habilitar la revisión.");return;
    }
    setBusy(true);setError("");
    try{
      const url="/javiera/admin/matrices/"+current.id+(soloPilot?"/enable-print":"/approve");
      await request(url,{method:"POST",...(soloPilot?
        {body:JSON.stringify({confirmed_content:true})}:{})});
      await reload(current.id);invalidate();
      setMessage(soloPilot?"Matriz habilitada para vista previa PDF. No constituye revisión profesional.":"Revisión aprobada por revisor autorizado.");
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function reviewFile(file:File){
    setImportPreview(null);setImportConfirmed(false);setImportFile(null);setError("");
    if(!file.name.toLowerCase().endsWith(".xlsx")){
      setError("Debes seleccionar un archivo Excel .xlsx.");return;
    }
    setBusy(true);
    try{
      const form=new FormData();form.append("file",file);
      const result=await request<Preview>("/javiera/v192/workbook-preview",{
        method:"POST",body:form,
      });
      setImportPreview(result);setImportFile(file);
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function applyWorkbook(){
    if(!importPreview?.can_import||!importFile||!importConfirmed)return;
    setBusy(true);setError("");
    try{
      const form=new FormData();
      form.append("file",importFile);
      form.append("sha256",importPreview.sha256);
      form.append("baseline_sha256",importPreview.baseline_sha256);
      form.append("confirmed","true");
      const result=await request<{drafts:Record<string,number>;created:number;unchanged:number;status:string}>(
        "/javiera/v192/workbook-commit",{method:"POST",body:form});
      setMessage("Importación verificada: "+result.created+" revisiones nuevas en borrador y "+
        result.unchanged+" sin cambios. Ninguna matriz aprobada o PDF histórico fue reemplazado.");
      await reload();
      setImportPreview(null);setImportFile(null);setImportConfirmed(false);
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  function appendRow(){
    if(kind==="PTS"||sections.length>=1500)return;
    setActiveIRL(sections.length);
    setSections(prev=>[...prev,kind==="IRL"?
      "Tarea: \nPeligro: \nRiesgo: \nMedidas: ":""]);invalidate();
  }
  return <section className="jmx-root">
    <header className="jmx-top"><div><small>PROYECTO JAVIERA · 19.5.0-rc1 · correcciones preventivas en borrador</small>
      <h2><ClipboardList size={23}/> Matrices y cargos</h2>
      <p>Revisa riesgos, controles y procedimientos por cargo, sin editar Excel. Cada cambio crea una revisión separada.</p>
    </div><button type="button" onClick={newRecord}><Plus size={16}/> Nuevo cargo</button></header>
    {error&&<p className="jmx-error" role="alert">{error}</p>}
    {message&&<p className="jmx-success" role="status"><CheckCircle2 size={17}/>{message}</p>}
    <section className="jmx-command-center" aria-label="Centro de control de matrices">
      <div className="jmx-command-title"><div>
        <h3>Centro de control y aprobaciones</h3>
        <p>Estados reales del tipo seleccionado. Las referencias del Excel no equivalen a aprobación.</p>
      </div><label>Mostrar
        <select aria-label="Filtrar por estado" value={reviewFilter}
          onChange={e=>setReviewFilter(e.target.value as ReviewFilter)}>
          <option value="all">Todas</option>
          <option value="approved">Aprobadas</option>
          <option value="draft">Borradores</option>
          <option value="incomplete">Con campos faltantes</option>
          <option value="reference">Referencias Excel</option>
        </select></label></div>
      <div className="jmx-command-stats">
        <button type="button" data-status="approved" onClick={()=>setReviewFilter("approved")}>
          <span>Aprobadas</span><strong>{reviewStats.approved}</strong></button>
        <button type="button" data-status="draft" onClick={()=>setReviewFilter("draft")}>
          <span>Listas para revisar</span><strong>{reviewStats.draft}</strong></button>
        <button type="button" data-status="incomplete" onClick={()=>setReviewFilter("incomplete")}>
          <span>Con campos faltantes</span><strong>{reviewStats.incomplete}</strong></button>
        <button type="button" data-status="reference" onClick={()=>setReviewFilter("reference")}>
          <span>Referencias Excel sin aprobar</span><strong>{reviewStats.reference}</strong></button>
      </div>
      {pendingReview.length>0?<div className="jmx-pending">
        <strong>Revisiones pendientes de decisión</strong>
        <div>{pendingReview.slice(0,8).map(row=><button key={row.id} type="button"
          onClick={()=>{selectRecord(row);document.getElementById("jmx-editor-start")?.scrollIntoView({block:"start"});}}>
          {row.cargo} · revisión {row.revision} · Ver y comprobar impacto
        </button>)}</div>
        {pendingReview.length>8&&<small>Se muestran 8 de {pendingReview.length}; filtra borradores para consultar el resto.</small>}
      </div>:<p className="jmx-command-empty">No hay borradores completos esperando revisión en esta categoría.
        Los errores deben corregirse antes de solicitar aprobación.</p>}
    </section>
    <section className="jmx-import" aria-label="Importar matrices desde Excel">
      <div><h3><Upload size={18}/> Importar Excel con comparación previa</h3>
        <p>Las cinco matrices se consultan precargadas desde el Excel original.
          Sube otro archivo solo si necesitas comparar diferencias; nunca se modifica
          automáticamente una matriz aprobada ni un documento histórico.</p></div>
      <label className="jmx-upload">Seleccionar archivo .xlsx
        <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          disabled={busy} onChange={e=>{
            const file=e.target.files?.[0];if(file)void reviewFile(file);e.target.value="";
          }}/>
      </label>
      {importPreview&&<div className="jmx-import-result">
        <div className="jmx-summary"><span>IRL: {importPreview.irl_source_rows} filas</span>
          <span>PTS: {importPreview.pts_source_rows} filas</span>
          <span>Fórmulas localizadas: {importPreview.formula_count}
            {importPreview.formula_count_partial?" (parcial)":""}</span>
          <span>Fórmulas hoja IRL: {importPreview.irl_formula_count}</span>
          <span>Imágenes IRL: {importPreview.irl_embedded_images===null?"sin verificar":
            importPreview.irl_embedded_images}</span></div>
        <p className="jmx-help-note">El inventario confirma qué fórmulas existen en el Excel, pero
          no acredita todavía equivalencia de cálculo con Excel.</p>
        <details><summary>Inventario de fórmulas por hoja y celda</summary>
          <div className="jmx-changes">
            <p>{Object.entries(importPreview.formulas_by_sheet).map(([sheet,count])=>
              sheet+": "+count).join(" · ")}</p>
            <div className="jmx-formula-list">
              {importPreview.formula_inventory.slice(0,60).map((item,i)=><p key={i}>
                <strong>{item.sheet}!{item.cell}</strong> · {item.type} ·
                {" "}Referencias detectadas: {item.dependencies_a1_detected.join(", ")||"Sin referencias A1 directas"}
              </p>)}
            </div>
            {importPreview.formula_inventory.length>60&&<p>Se muestran 60 fórmulas de
              {" "}{importPreview.formula_inventory.length} inventariadas.</p>}
          </div>
        </details>
        <p><strong>Comparación:</strong> {importPreview.new} cargos nuevos, {importPreview.changed} modificados,
          {" "}{importPreview.unchanged} sin cambios.</p>
        {importPreview.warnings.length>0&&<div className="jmx-warning">
          <strong>Observaciones que requieren revisión</strong>
          <ul>{importPreview.warnings.map((warning,i)=><li key={i}>{warning}</li>)}</ul>
        </div>}
        <details><summary>Ver cambios detectados por cargo</summary>
          <div className="jmx-changes">{importPreview.matrices.map((entry,i)=>
            <p key={i}><b>{entry.kind} · {entry.cargo}</b> — {entry.change==="new"?"Nuevo":
              entry.change==="changed"?"Modificado":"Sin cambios"} ·
              {" "}{entry.different_sections} secciones distintas</p>)}</div>
        </details>
        {importPreview.can_import?<><label className="jmx-confirm">
          <input type="checkbox" checked={importConfirmed} onChange={e=>setImportConfirmed(e.target.checked)}/>
          He revisado las diferencias y entiendo que se crearán borradores, incluso para matrices sin cambios.
        </label><button type="button" className="jmx-save" disabled={busy||!importConfirmed}
          onClick={()=>void applyWorkbook()}>Confirmar importación en borrador</button></>:
          <p className="jmx-error">Importación bloqueada: falta información o se omitieron matrices.
            Corrige el Excel para evitar perder registros.</p>}
      </div>}
    </section>
    <div className="jmx-grid">
      <aside className="jmx-aside">
        <label htmlFor="jmx-kind">Tipo de matriz</label>
        <select id="jmx-kind" value={kind} onChange={e=>selectKind(e.target.value as Kind)}>
          {kinds.map(k=><option key={k} value={k}>{labels[k]}</option>)}
        </select>
        <label htmlFor="jmx-search"><Search size={14}/> Buscar cargo</label>
        <input id="jmx-search" type="search" value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="Ej. carpintero, pintor"/>
        {(loading||referenceLoading)?<p>Cargando registros originales del Excel…</p>:<div className="jmx-items">
          <small>{latest.length} entradas mostradas · {referenceTotal} referencias Excel</small>
          {latest.map(row=><button key={row.id} type="button" className={row.id===selectedId?"chosen":""}
            onClick={()=>selectRecord(row)}><span>{row.cargo}<small>{
              row.status==="reference"?
                "Excel original · fila "+row.source_row+" · sin aprobar":
                row.kind+" · revisión "+row.revision+" · "+
                  (row.status==="approved"?"Aprobada":"Borrador")
            }</small></span><ArrowRight size={14}/></button>)}
          {!latest.length&&<p>No hay resultados para este filtro; selecciona «Todas» para ver el catálogo completo.</p>}
        </div>}
      </aside>
      <div className="jmx-editor" id="jmx-editor-start">
        <div className="jmx-controls">
          <label>Cargo / puesto
            <input value={cargo} onChange={e=>{setCargo(e.target.value);setSelectedId("");invalidate();}}
              maxLength={160} placeholder="Cargo según matriz original"/>
          </label>
          <label>Revisión o archivo original
            <select value={selectedId} onChange={e=>{
              const row=allRows.find(x=>x.id===e.target.value);if(row)selectRecord(row);
            }} disabled={!versions.length}>
              {!versions.length&&<option value="">Nueva</option>}
              {versions.map(row=><option key={row.id} value={row.id}>
                {row.status==="reference"?
                  "Excel original · fila "+row.source_row+" (sin aprobar)":
                  "Revisión "+row.revision+" · "+(row.status==="approved"?"Aprobada":"Borrador")}
              </option>)}
            </select>
          </label>
        </div>
        {current?.status==="reference"&&<div className="jmx-warning">
          <strong>Matriz precargada automáticamente desde el Excel</strong>
          <p>{current.source}. Todos sus apartados se muestran para consulta y edición.
          Es una referencia técnica, no una matriz aprobada. Para imprimirla,
          crea una revisión en borrador y solicita validación preventiva.</p>
        </div>}
        {variant&&!variantIdentical&&<div className="jmx-warning">
          <strong>El Excel contiene registros duplicados para este cargo.</strong>
          Conservamos las filas {referenceVariants.filter(item=>item.cargo===cargo)
            .flatMap(item=>item.source_rows).join(", ")}.
          Elige la variante correcta antes de solicitar aprobación.
        </div>}
        {variantIdentical&&<p className="jmx-success">Coincidencias originales idénticas: se pueden consultar sin elegir manualmente una variante. Su aprobación continúa pendiente.</p>}
        <div className="jmx-summary">
          <span><FileSpreadsheet size={15}/> {sections.length} apartados / registros</span>
          <span>{approved?"Aprobada v"+approved.revision:"Sin revisión aprobada"}</span>
          <span>{changes} apartados distintos de la aprobada</span>
        </div>
        {kind==="IRL"&&<section className="jmx-completeness" aria-label="Revisión de campos del IRL">
          {missingIRL.length>0?<><strong>{missingIRL.length} tareas incompletas · faltan datos antes de aprobación</strong>
            <p>Corrige los campos indicados. La revisión preventiva sigue siendo obligatoria.</p>
            <div>{missingIRL.slice(0,12).map(item=><button type="button" key={item.index}
              onClick={()=>{setActiveIRL(item.index);
                document.querySelector(".jmx-irl-easy-editor")?.scrollIntoView({block:"start"});}}>
              Tarea {item.index+1}: {item.fields.join(", ")}
            </button>)}</div>
            {missingIRL.length>12&&<small>Mostrando 12 de {missingIRL.length} tareas con campos faltantes.</small>}
          </>:<><strong>Campos estructurales completos en esta vista</strong>
            <p>Esto no significa que la matriz esté aprobada: revisa coherencia, sustancias, HDS y firmas autorizadas.</p></>}
        </section>}
        {kind==="IRL"&&<section className="jmx-bulk" aria-label="Pegar matriz de riesgos desde Excel">
          <div className="jmx-bulk-heading"><div><strong>Copiar y pegar matriz desde Excel</strong>
            <p>Pega cuatro columnas: actividad, peligro, consecuencia y medida. Revisa antes de aplicar; no se guarda automáticamente.</p></div>
            <button type="button" onClick={()=>void copySections()}>Copiar matriz</button></div>
          <textarea rows={3} value={bulkText} onChange={e=>{setBulkText(e.target.value);setBulkPreview(null);}}
            placeholder="Actividad\tPeligro\tConsecuencia\tMedida preventiva" aria-label="Datos tabulados copiados desde Excel" />
          <div className="jmx-bulk-actions">
            <label>Acción <select value={bulkMode} onChange={e=>setBulkMode(e.target.value as "replace"|"append")}>
              <option value="replace">Reemplazar filas del editor</option><option value="append">Agregar al final</option>
            </select></label>
            <button type="button" disabled={!bulkText.trim()} onClick={checkPaste}>Previsualizar pegado</button>
            {bulkUndo&&<button type="button" onClick={()=>{setSections(bulkUndo);setBulkUndo(null);invalidate();setMessage("Se deshizo el último pegado.");}}>Deshacer pegado</button>}
          </div>
          {bulkPreview&&<div className="jmx-bulk-preview" role="status">
            <strong>{bulkPreview.sections.length} labores válidas</strong> · {bulkPreview.duplicates} duplicados idénticos omitidos.
            <p>Ejemplos: {bulkPreview.sections.slice(0,2).map(s=>splitSection(s)?.[0]).join(" · ")}</p>
            <button type="button" onClick={applyPaste}>Aplicar al editor (borrador local)</button>
          </div>}
        </section>}
        {kind==="IRL"?<section className="jmx-irl-easy-editor" aria-label="Edición guiada de riesgos">
          <header className="jmx-irl-heading">
            <h3>Editar labores y riesgos, paso a paso</h3>
            <p>Selecciona una tarea. Sus cuatro campos permanecen unidos al mismo registro
              y puedes editar sin desplazarte horizontalmente.</p>
          </header>
          <div className="jmx-irl-layout">
            <nav aria-label="Labores IRL" className="jmx-irl-task-list">
              {sections.map((section,index)=>{
                const fields=splitSection(section);
                const incomplete=!fields||fields.some(field=>!field.trim());
                return <button type="button" key={index} onClick={()=>setActiveIRL(index)}
                  className={activeIRL===index?"jmx-irl-active":""}
                  aria-current={activeIRL===index?"step":undefined}>
                  <span>{index+1}.</span>
                  <span>{fields?.[0]?.trim()||"Tarea pendiente"}</span>
                  {incomplete&&<em aria-label="Campos incompletos">!</em>}
                </button>;
              })}
            </nav>
            <div className="jmx-irl-fields">
              {sections.length>0&&(()=>{
                const index=Math.min(activeIRL,sections.length-1);
                const section=sections[index];
                const fields=splitSection(section);
                return <div key={index}>
                  <div className="jmx-irl-field-head">
                    <strong>Tarea {index+1} de {sections.length}</strong>
                    <span>{fields&&fields.every(field=>field.trim())?"Campos completos":"Revisión pendiente"}</span>
                  </div>
                  {fields?names.map((name,col)=><label key={name}>
                    <span>{name}{col===3?" preventivas":""}</span>
                    <textarea rows={col===3?5:3} value={fields[col]}
                      aria-label={name+" de tarea "+(index+1)}
                      onChange={event=>edit(index,withColumn(section,col,event.target.value))}/>
                  </label>):<label>
                    <span>Contenido original sin cuatro campos: debe estructurarse</span>
                    <textarea rows={8} value={section} onChange={event=>edit(index,event.target.value)}/>
                  </label>}
                  <div className="jmx-irl-navigation">
                    <button type="button" disabled={index===0}
                      onClick={()=>setActiveIRL(index-1)}>Anterior</button>
                    <button type="button" disabled={index>=sections.length-1}
                      onClick={()=>setActiveIRL(index+1)}>Siguiente tarea</button>
                  </div>
                </div>;
              })()}
            </div>
          </div>
        </section>:<div className="jmx-rows">
          {sections.map((section,index)=><label key={index}>
            <span>{referenceColumns[index]||((kind==="PTS"?"Apartado técnico ":"Campo ")+(index+1))}
              {approved && approved.sections[index]!==section?" · Modificado":""}</span>
            <textarea value={section} rows={3} onChange={e=>edit(index,e.target.value)}/>
          </label>)}</div>}
        {kind!=="PTS"&&<button className="jmx-add" type="button" onClick={appendRow}
          disabled={sections.length>=1500}><Plus size={15}/> Agregar fila (máx. 1.500 por cargo)</button>}
        <div className="jmx-impact">
          <h3>Antes de activar los cambios</h3>
          <p>El borrador no reemplaza la matriz aprobada ni modifica PDF históricos.
            Revisa qué documentos utilizarán la nueva versión después de habilitarla.</p>
          <button type="button" onClick={()=>void previewImpact()} disabled={busy||cargo.trim().length<2}>
            <ShieldCheck size={16}/> Consultar repercusión</button>
          {impact && impactFingerprint===fingerprint(kind,cargo,sections)&&<div className="jmx-impact-detail">
            <p><strong>Documentos por revisar:</strong> {impact.new_pdf_formats.join(", ").toUpperCase()}</p>
            <p><strong>Expedientes con ese cargo:</strong> {impact.affected_dossiers}
              {impact.count_is_partial?" (conteo parcial)":""}</p>
            <p>Proyecto Javiera actual: {impact.affected_by_origin.current_documentary_workflow}
              {" · "}Históricos: {impact.affected_by_origin.historical_workflow}</p>
            <p><strong>Última revisión aprobada:</strong> {impact.current_approved_revision||"Ninguna"}</p>
            <p><strong>Coherencia preventiva por revisar:</strong> {impact.related_formats_for_review.join(", ").toUpperCase()}
              {" "}(referencias relacionadas, no se actualizan automáticamente)</p>
            <p><strong>Versiones aprobadas relacionadas:</strong> IRL {impact.related_matrix_versions.irl||"Sin versión"},
              {" "}PTS {impact.related_matrix_versions.pts||"Sin versión"}</p>
            <p>Los archivos ya emitidos permanecen intactos. La nueva revisión no se activa al guardarla.</p>
            <label className="jmx-confirm"><input type="checkbox" checked={confirmed}
              onChange={e=>setConfirmed(e.target.checked)}/>
              Compruebo el impacto y el contenido preventivo antes de continuar.</label>
          </div>}
          <div className="jmx-actions">
            <button className="jmx-save" type="button" onClick={()=>void save()}
              disabled={busy||!confirmed||!impact||sections.length===0||
                impactFingerprint!==fingerprint(kind,cargo,sections)}>
              <Save size={16}/> Guardar nueva revisión en borrador</button>
            {current?.status==="draft"&&!changed&&<button type="button" disabled={busy||!confirmed}
              onClick={()=>void enable()}><ShieldCheck size={16}/>
              {soloPilot?"Habilitar vista previa PDF":"Solicitar aprobación profesional"}</button>}
          </div>
        </div>
      </div>
    </div>
  </section>;
}
