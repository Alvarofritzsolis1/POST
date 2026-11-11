import {useEffect,useMemo,useState} from "react";
import {AlertTriangle,ClipboardList,FileSpreadsheet,Search,ShieldCheck} from "lucide-react";
import {request} from "./api";
import {serializeIRLClipboard} from "./javiera-irl-clipboard";
import JavieraIRLVisualBlocks from "./JavieraIRLVisualBlocks";
import "./javiera-irl-structure.css";

type Role={cargo:string;has_approved_irl:boolean;has_approved_pts:boolean;has_draft:boolean;source_excel_available?:boolean;reference_count?:number};
type IRLRow={id:string;ordinal:number;labor:string;peligro:string;riesgo:string;medidas:string;original:string;structured:boolean;source_excel_rows?:number[]};
type CorrectiveDraft={type:"risk_row"|"chemical_inventory"|"none";
  source_preserved?:boolean;approval_status:string;
  proposal?:{excel_row?:number;status?:string;
    risk_suggestion?:string;controls_suggestion?:string;
    disclaimer?:string;technical_reference?:string;
    missing_evidence?:string[];fields?:string[];
    no_chemical_use_policy?:string;source_alias_not_accepted?:string};
  editor_draft_sections?:string[]};
type Detail={cargo:string;corrective_draft?:CorrectiveDraft;irl:{approved:boolean;revision:number|null;records:IRLRow[];has_unstructured:boolean;reference_only?:boolean};
  warnings:string[];can_preview_irl:boolean;reference_total?:number;reference_display_total?:number;source_excel_available?:boolean;reference_incomplete_excel_rows?:number[];reference_audit?:ReferenceAudit;
  additional_matrices:Record<AuditKind,{sections:string[];available:boolean;reference_only?:boolean;revision:number|null}>};
type AuditKind="PERFILES"|"PUESTOS"|"SUSTANCIAS";
type AuditSource={source_sheet:string;source_row:number;source_cargo:string;sections:string[];reference_only:boolean};
type AuditLink={match_count:number;source_entries:AuditSource[];resolved_source?:AuditSource|null;duplicate_identical?:boolean;missing:boolean;ambiguous:boolean;suggested_aliases_pending_review:string[]};
type ReferenceAudit={risk_count:number;display_risk_count?:number;collapsed_risk_groups?:{source_excel_rows:number[]}[];incomplete_excel_rows:number[];duplicate_source_numbers:string[];
  full_excel_parity_certified:boolean;original_visual_blocks:{title:string;status:string}[];
  linked:Record<AuditKind|"PTS",AuditLink>;warnings:string[]};
const AUX_LABELS:Record<AuditKind,string>={
  PERFILES:"Descripción y labores del cargo",PUESTOS:"Condiciones del puesto de trabajo",SUSTANCIAS:"Sustancias y HDS"
};
const AUX_COLUMNS:Record<AuditKind,string[]>={
  PERFILES:["Perfil técnico"],
  PUESTOS:["Espacio de trabajo","Condiciones ambientales","Orden y aseo","Máquinas y herramientas"],
  SUSTANCIAS:["Producto","Sinónimo","Fórmula","Aspecto","Olor","Modo de empleo",
    "Límites de exposición","Almacenamiento","Uso de EPP","Primeros auxilios",
    "Información de etiqueta DS 57","Información de HDS"]
};
type OriginalImage={title:string;order:number;anchor_row:number|null;data_uri:string;sha256:string};
type OriginalIRL={available:boolean;status:string;image_count:number;source_sha256?:string;all_five_images_present?:boolean;
  images:OriginalImage[];static:Record<string,string>;document_code?:string;source_version?:string;
  layout_revision?:number;message?:string};
const IRL_CONDITIONS=["a) Espacio de trabajo","b) Condiciones ambientales del puesto",
  "c) Condiciones de orden y aseo","d) Máquinas y herramientas de trabajo que se deberán emplear"];
const IRL_SUBSTANCE_FIELDS=["Nombre del producto","Sinónimo","Fórmula","Aspecto","Olor",
  "Modo de empleo","Límites de exposición","Forma de almacenamiento","Uso correcto de EPP",
  "Medidas sobre primeros auxilios","Información técnica de la etiqueta (DS 57 MINSAL)",
  "Otra información relevante contenida en la HDS"];
type Props={onEditMatrices?:()=>void};

export default function JavieraIRLStructure({onEditMatrices}:Props){
  const [roles,setRoles]=useState<Role[]>([]);
  const [cargo,setCargo]=useState("");
  const [query,setQuery]=useState("");
  const [detail,setDetail]=useState<Detail|null>(null);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [roleLoading,setRoleLoading]=useState(false);
  const [original,setOriginal]=useState<OriginalIRL|null>(null);
  const [originalError,setOriginalError]=useState("");
  const [sourceRefresh,setSourceRefresh]=useState(0);
  const [importingOriginal,setImportingOriginal]=useState(false);
  const [copyStatus,setCopyStatus]=useState("");

  useEffect(()=>{
    let active=true;
    void request<{roles:Role[];partial:boolean}>("/javiera/v194/roles")
      .then(payload=>{
        if(!active)return;
        setRoles(payload.roles);
        setCargo(previous=>previous||payload.roles.find(r=>r.has_approved_irl)?.cargo||payload.roles.find(r=>r.source_excel_available)?.cargo||"");
        setError("");
      })
      .catch(reason=>{if(active)setError(reason instanceof Error?reason.message:String(reason));})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[]);

  useEffect(()=>{
    if(!cargo){setDetail(null);return;}
    let active=true;
    setRoleLoading(true);
    setDetail(null);
    void request<Detail>("/javiera/v194/role?cargo="+encodeURIComponent(cargo))
      .then(value=>{if(active){setDetail(value);setError("");}})
      .catch(reason=>{if(active){setDetail(null);setError(reason instanceof Error?reason.message:String(reason));}})
      .finally(()=>{if(active)setRoleLoading(false);});
    return()=>{active=false;};
  },[cargo]);

  useEffect(()=>{
    let active=true;
    void request<OriginalIRL>("/javiera/v195/irl-original")
      .then(payload=>{if(active){setOriginal(payload);setOriginalError("");}})
      .catch(reason=>{if(active)setOriginalError(reason instanceof Error?reason.message:String(reason));});
    return()=>{active=false;};
  },[sourceRefresh]);

  async function importOriginal(file:File){
    if(!file.name.toLowerCase().endsWith(".xlsx")){
      setOriginalError("Selecciona el Excel original .xlsx.");return;
    }
    setImportingOriginal(true);setOriginalError("");
    try{
      const form=new FormData();form.append("file",file);
      await request("/javiera/admin/excel/import",{method:"POST",body:form});
      setSourceRefresh(value=>value+1);
    }catch(e){setOriginalError(e instanceof Error?e.message:String(e));}
    finally{setImportingOriginal(false);}
  }

  const filtered=useMemo(()=>roles.filter(r=>r.cargo.toLocaleLowerCase("es")
    .includes(query.trim().toLocaleLowerCase("es"))),[roles,query]);
  const current=detail?.cargo===cargo&&!roleLoading?detail:null;
  // No mostrar temporalmente riesgos de otro cargo durante una consulta.
  const rows=current?.irl.records||[];
  const unstructured=rows.some(r=>!r.structured);
  const reference=current?.reference_audit;
  const sectionFor=(kind:AuditKind)=>{
    const approvedOrReference=current?.additional_matrices?.[kind];
    if(approvedOrReference?.available && approvedOrReference.sections.length){
      return approvedOrReference.sections;
    }
    return reference?.linked[kind]?.resolved_source?.sections||[];
  };
  const profile=sectionFor("PERFILES")[0]||"Pendiente de validar el perfil de este cargo.";
  const workplace=sectionFor("PUESTOS");
  const substances=sectionFor("SUSTANCIAS");
  const staticValue=(coordinate:string)=>original?.static[coordinate]||"";
  const warningList=[...new Set([...(current?.warnings||[]),...(reference?.warnings||[])])];
  async function copyCorrectiveDraft(){
    if(!current?.corrective_draft?.proposal)return;
    const correction=current.corrective_draft;
    const proposal=correction.proposal;
    if(!proposal)return;
    let content="";
    if(correction.type==="risk_row"&&proposal.excel_row===40){
      content=serializeIRLClipboard(rows.map(row=>{
        const isTarget=row.source_excel_rows?.includes(40);
        return [row.labor,row.peligro,
          isTarget?proposal.risk_suggestion||"":row.riesgo,
          isTarget?proposal.controls_suggestion||"":row.medidas];
      }));
    }else if(correction.type==="chemical_inventory"){
      content=[
        "PAISAJISTA — FICHA DE LEVANTAMIENTO HDS (SIN APROBACIÓN)",
        ...(proposal.fields||[]).map(field=>field+"\tPENDIENTE DE EVIDENCIA"),
        "",
        ...(proposal.missing_evidence||[]).map(item=>"VERIFICAR: "+item),
      ].join("\n");
    }
    if(!content)return;
    try{
      await navigator.clipboard.writeText(content);
      setCopyStatus("Propuesta copiada para edición. NO aprobada: verificar en obra y firmar el acta.");
    }catch{setCopyStatus("El navegador no permitió copiar. Verifica permisos del portapapeles.")}
  }
  async function copyRiskMatrix(){
    if(!rows.length)return;
    const values=serializeIRLClipboard(rows.map(row=>
      [row.labor,row.peligro,row.riesgo,row.medidas]));
    try{await navigator.clipboard.writeText(values);
      setCopyStatus("Matriz copiada; puedes pegarla en Excel o en el editor de matrices.");
    }catch{setCopyStatus("El navegador no permitió copiar automáticamente.");}
  }
  return <div className="jir-root">
    <div className="jir-intro">
      <div><div className="jir-kicker"><ClipboardList size={16}/> Estructura IRL · revisión integral</div>
        <h4>Formato original, datos vinculados y matriz de riesgos</h4>
        <p>Vista completa del IRL original: encabezado, descripción del cargo, condiciones del puesto,
          riesgos, sustancias, fotografías insertadas, normas y firma. El contenido técnico depende del cargo
          y debe validarse antes de emisión definitiva.</p>
      </div>
      {onEditMatrices&&<button type="button" className="jir-matrices" onClick={onEditMatrices}>
        <FileSpreadsheet size={16}/> Abrir Matrices y cargos
      </button>}
    </div>

    <div className="jir-filter">
      <label htmlFor="jir-find-role"><Search size={15}/> Buscar cargo en las matrices</label>
      <input id="jir-find-role" value={query} onChange={event=>setQuery(event.target.value)}
        placeholder="Buscar carpintero, pintor, soldador..." type="search"/>
      <label htmlFor="jir-role">Cargo que deseas revisar</label>
      <select id="jir-role" value={cargo} onChange={event=>setCargo(event.target.value)}>
        <option value="">Seleccionar un cargo del catálogo</option>
        {filtered.map(item=><option value={item.cargo} key={item.cargo}>
          {item.cargo}{item.has_approved_irl?" · IRL aprobada":item.source_excel_available?" · Excel original (pendiente de validación)":" · sin IRL"}
        </option>)}
        {cargo&&!filtered.some(item=>item.cargo===cargo)&&
          <option value={cargo}>{cargo} · seleccionado</option>}
      </select>
      {loading?<small>Consultando cargos…</small>:!roles.length&&
        <p className="jir-warning"><AlertTriangle size={15}/>
          Aún no hay cargos importados en esta organización. El formato se muestra,
          pero no se inventarán tareas ni medidas preventivas.</p>}
      {error&&<p className="jir-warning" role="alert">{error}</p>}
    </div>

    <section className="jir-original-status" aria-label="Origen del formato IRL">
      {original?.available?<p className={original.all_five_images_present?"jir-status":"jir-warning"}>
        <ShieldCheck size={16}/> Excel original importado · revisión {original.layout_revision} ·
        {" "}{original.image_count} imágenes originales detectadas.
        {original.status!=="approved"?" Formato en revisión: no sustituye aprobación preventiva.":""}
      </p>:<div className="jir-import-original">
        <strong>Falta cargar el Excel original de la organización</strong>
        <p>Importa el archivo una sola vez. GALANT extraerá automáticamente las imágenes de la
          hoja IRL y las conservará en el documento de cada cargo sin pegarlas manualmente.</p>
        <label className="jir-import-action">
          {importingOriginal?"Importando formato…":"Seleccionar Excel original (.xlsx)"}
          <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={importingOriginal} onChange={event=>{
              const file=event.target.files?.[0];
              if(file)void importOriginal(file);
              event.target.value="";
            }}/>
        </label>
      </div>}
      {originalError&&<p className="jir-warning" role="alert">{originalError}</p>}
    </section>
    {original?.available&&original.images?.length===5&&<JavieraIRLVisualBlocks source={original}/>}
    {current?.reference_audit&&
      (current.reference_audit.incomplete_excel_rows.length>0||
       current.reference_audit.linked.SUSTANCIAS.missing)&&
      <section className="jir-critical-source" aria-label="Alertas preventivas de matriz original">
        <strong><AlertTriangle size={17}/> La referencia original de este cargo requiere correcciones</strong>
        {current.reference_audit.incomplete_excel_rows.length>0&&<p>
          Riesgos con consecuencia o medida preventiva faltante en filas Excel:
          {" "+current.reference_audit.incomplete_excel_rows.join(", ")}.
          No se completarán ni aprobarán automáticamente.
        </p>}
        {current.reference_audit.linked.SUSTANCIAS.missing&&<p>
          Sustancias y HDS sin vinculación exacta para {cargo}.
          {cargo==="PAISAJISTA"?
            " La fila «PAISAJISMO (REVISAR HDS)» incluye productos de pintura y no se vincula sin revisión preventiva.":
            " Verifica los productos y HDS reales antes de la aprobación."}
        </p>}
        {!current.irl.approved&&current.corrective_draft?.type==="risk_row"&&
          current.corrective_draft.proposal&&<div className="jir-suggested-correction">
            <h4>Propuesta de corrección · CARPINTERO fila 40</h4>
            <p><b>Consecuencias propuestas:</b> {current.corrective_draft.proposal.risk_suggestion}</p>
            <p><b>Medidas preventivas propuestas:</b> {current.corrective_draft.proposal.controls_suggestion}</p>
            <p className="jir-noapprove">{current.corrective_draft.proposal.disclaimer}</p>
            <button type="button" onClick={()=>void copyCorrectiveDraft()}>
              Copiar las 13 filas con la propuesta para el editor
            </button>
          </div>}
        {current.corrective_draft?.type==="chemical_inventory"&&
          current.corrective_draft.proposal&&<div className="jir-suggested-correction">
            <h4>Ficha HDS por verificar · PAISAJISTA</h4>
            <p>No se importan los productos de
              «{current.corrective_draft.proposal.source_alias_not_accepted}» como sustancias del cargo.</p>
            <p><b>Documentos necesarios:</b></p>
            <ul>{(current.corrective_draft.proposal.missing_evidence||[])
              .map(item=><li key={item}>{item}</li>)}</ul>
            <p>{current.corrective_draft.proposal.no_chemical_use_policy}</p>
            <button type="button" onClick={()=>void copyCorrectiveDraft()}>
              Copiar ficha de 12 campos HDS para levantar datos reales
            </button>
          </div>}
        {onEditMatrices&&<button type="button" onClick={onEditMatrices}>
          Revisar matrices y corregir faltantes
        </button>}
      </section>}
    <div className="jir-view-toolbar">
      <span><strong>{rows.length}</strong> labores en esta vista
        {current?.reference_total&&current.reference_total>rows.length?
          " · "+(current.reference_total-rows.length)+" filas repetidas agrupadas":""}
        {" · "}{current?.irl.approved?"Matriz aprobada": "Referencia pendiente de aprobación preventiva"}</span>
      <button type="button" onClick={()=>void copyRiskMatrix()} disabled={!rows.length}>Copiar matriz para Excel</button>
      {copyStatus&&<small role="status">{copyStatus}</small>}
    </div>
    <details className="jir-preview" open><summary>Mostrar / ocultar vista previa A4 completa</summary>
    <div className="jir-scroll">
      <article className="jir-page jir-original-document" aria-label="IRL original reconstruido en formato A4">
        <div className="jir-print-label">VISTA PREVIA DE FORMATO ORIGINAL · SIN FIRMAS</div>
        <table className="jir-original-masthead"><tbody>
          <tr><th rowSpan={2}>{staticValue("A2")||"DEPARTAMENTO DE PREVENCIÓN DE RIESGOS"}</th>
            <th>{staticValue("B2")||"INFORMACIÓN DE RIESGOS LABORALES"}</th>
            <th>Código: {staticValue("C3")||"DPR-IRL-03"}</th>
            <th>{original?.source_version||"VERSIÓN DEL FORMATO"}</th></tr>
          <tr><th>{staticValue("B3")||"IRL - D.S. N° 44"}</th>
            <th colSpan={2}>Página automática al imprimir</th></tr>
        </tbody></table>
        <h2>{staticValue("A4")||"INFORMACIÓN DE RIESGOS LABORALES (IRL) - DECRETO SUPREMO N° 44"}</h2>
        {staticValue("A5")&&<p className="jir-legal-intro">{staticValue("A5")}</p>}
        <div className="jir-person-fields">
          <p><strong>Trabajador:</strong> se completa automáticamente desde el expediente</p>
          <p><strong>RUT:</strong> desde expediente <strong>Obra:</strong> desde expediente</p>
          <p><strong>Fecha:</strong> fecha del documento <strong>Cargo:</strong> {cargo||"Seleccionar cargo"}</p>
          <p><strong>Empresa / RUT:</strong> se completan automáticamente desde el expediente</p>
          <p><strong>Especialidad evaluada de riesgos:</strong> {cargo||"Pendiente"}</p>
        </div>
        {staticValue("A13")&&<h3>{staticValue("A13")}</h3>}
        {staticValue("A14")&&<p className="jir-legal-quote">{staticValue("A14")}</p>}
        <h3>Descripción del cargo</h3>
        <p className="jir-excel-value">{profile}</p>
        <h3>1 - RIESGOS INHERENTES A LA ACTIVIDAD REALIZADA</h3>
        {IRL_CONDITIONS.map((field,i)=><section className="jir-condition" key={field}>
          <h4>{field}</h4>
          <p>{workplace[i]?.trim()||"Pendiente: debe asociarse y aprobarse el contenido del cargo."}</p>
        </section>)}
        <h3>2 - RIESGOS Y MEDIDAS PREVENTIVAS</h3>
        <table className="jir-risk-table"><thead><tr>
          <th>Actividad</th><th>Riesgos detectados</th>
          <th>Consecuencias potenciales</th><th>Medidas preventivas obligatorias</th>
        </tr></thead><tbody>
          {rows.length>0?rows.map(row=><tr key={row.id}>
            {row.structured?<><td>{row.labor}</td><td>{row.peligro}</td>
              <td>{row.riesgo}</td><td>{row.medidas}</td></>:
              <td colSpan={4}><strong>Registro original pendiente de estructurar, fila {row.ordinal}:</strong>
                <span className="jir-original">{row.original}</span></td>}
          </tr>):<tr><td colSpan={4} className="jir-empty">
            Selecciona un cargo y valida su matriz para mostrar los riesgos efectivos.
          </td></tr>}
        </tbody></table>
        <h3>3 - CARACTERÍSTICAS DE PRODUCTOS Y SUSTANCIAS A MANIPULAR</h3>
        <table className="jir-substances"><tbody>{IRL_SUBSTANCE_FIELDS.map((field,i)=><tr key={field}>
          <th>{String.fromCharCode(97+i)})</th><th>{field}</th>
          <td>{substances[i]?.trim()||"Pendiente de validación técnica / HDS"}</td>
        </tr>)}</tbody></table>
        <h3>4 - ANTECEDENTES GENERALES Y NORMAS GENERALES DE SEGURIDAD</h3>
        {original?.images.length?original.images.map(media=><figure key={media.sha256}
          className="jir-original-media">
          <img src={media.data_uri} alt={media.title}/>
          <figcaption>{media.title} · imagen original del Excel (fila {media.anchor_row})</figcaption>
        </figure>):<p className="jir-warning">
          Las cinco imágenes no están disponibles hasta importar el Excel original;
          no se completan con fotografías ni contenido inventado.</p>}
        {staticValue("A169")&&<div className="jir-legal-close">{staticValue("A169")}</div>}
        {staticValue("A172")&&<p className="jir-legal-declaration">{staticValue("A172")}</p>}
        <div className="jir-original-signature">
          <span>_________________________</span>
          <strong>FIRMA TRABAJADOR</strong>
          <small>Nombre y RUT: se rellenan desde el expediente</small>
        </div>
      </article>
    </div>
    </details>
    {current?.reference_audit&&<section className="jir-parity" aria-label="Auditoría de integridad de matrices IRL">
      <div className="jir-parity-head">
        <h4>Datos relacionados con este cargo</h4>
        <p>Consulta la información técnica sin escribir código. Estas referencias provienen del catálogo
          del Excel y no equivalen a una revisión preventiva aprobada. Para corregirlas, abre «Matrices y cargos».</p>
      </div>
      <div className="jir-aux-grid">
        {(["PERFILES","PUESTOS","SUSTANCIAS"] as const).map(kind=>{
          const linked=current.reference_audit!.linked[kind];
          return <details className="jir-aux" key={kind}>
            <summary><span>{AUX_LABELS[kind]}</span>
              <strong>{linked.missing?"Sin vinculación":linked.ambiguous?"Revisar variantes":linked.duplicate_identical?"Duplicado idéntico resuelto":"Referencia disponible"}</strong>
            </summary>
            {linked.suggested_aliases_pending_review.length>0&&
              <p className="jir-aux-alert">Posible equivalencia pendiente de validación:
                {" "+linked.suggested_aliases_pending_review.join(", ")}. No se vincula automáticamente.</p>}
            {linked.source_entries.length>0?linked.source_entries.map(entry=>
              <div key={entry.source_sheet+":"+entry.source_row} className="jir-aux-content">
                <small>Hoja {entry.source_sheet} · fila {entry.source_row} · cargo fuente «{entry.source_cargo}»</small>
                <dl>{entry.sections.map((value,i)=><div key={i}>
                  <dt>{AUX_COLUMNS[kind][i]||"Campo "+(i+1)}</dt>
                  <dd>{value.trim()||"Pendiente de completar y validar"}</dd>
                </div>)}</dl>
              </div>
            ):<p className="jir-aux-alert">No existe una matriz inequívoca para este cargo. Debe revisarse;
              no se completarán campos utilizando otro cargo.</p>}
          </details>;
        })}
      </div>
      <details className="jir-original-blocks">
        <summary>Texto de las cinco imágenes: conservar las fotos, transcripción editable pendiente</summary>
        <ol>{current.reference_audit.original_visual_blocks.map(block=>
          <li key={block.title}>{block.title} · foto preservada cuando la fuente está disponible; contenido textual por digitalizar</li>)}</ol>
        <p>Las imágenes originales se conservan como fotos. Su contenido todavía no puede editarse como texto HTML. Se requiere validación preventiva y cotejo página por página.</p>
      </details>
      {warningList.length>0&&<details className="jir-audit-alerts">
        <summary>Observaciones pendientes ({warningList.length}) · ver detalles</summary>
        <ul>{warningList.map((warning,index)=><li key={index}>{warning}</li>)}</ul>
      </details>}
    </section>}
    <div className="jir-footer" role="status">
      {current?.irl.approved?<p className={unstructured?"jir-warning":"jir-status"}>
        {unstructured?<AlertTriangle size={16}/>:<ShieldCheck size={16}/>}
        {rows.length} registros del cargo «{cargo}» · revisión IRL {current.irl.revision}.
        {unstructured?" Existen filas incompletas; requieren revisión preventiva antes del PDF.":
          " Matriz aprobada vinculada; el PDF final se genera desde un expediente."}
      </p>:<p className="jir-warning"><AlertTriangle size={16}/>
        {current?.source_excel_available
          ?"Se muestran "+rows.length+" registros del Excel para este cargo, sin aprobación preventiva. "+
            (unstructured?"La referencia contiene campos incompletos que deben corregirse. ":"")+
            "La consulta no equivale a habilitación para imprimir."
          :"Esta estructura es informativa. Para imprimir necesitas una matriz IRL aprobada."}
      </p>}
      <p className="jir-explanation">El documento A4 definitivo y sus firmas se obtienen desde el expediente
        guardado. Los textos «desde el expediente» son indicadores de plantilla: el PDF del trabajador toma los datos efectivos de su ficha.
        Para cambiar un riesgo o una medida preventiva, usa «Matrices y cargos» y aprueba una revisión.</p>
    </div>
  </div>;
}
