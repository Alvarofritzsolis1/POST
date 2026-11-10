import {useEffect,useMemo,useState} from "react";
import {AlertTriangle,ClipboardList,FileSpreadsheet,Search,ShieldCheck} from "lucide-react";
import {request} from "./api";
import "./javiera-irl-structure.css";

type Role={cargo:string;has_approved_irl:boolean;has_approved_pts:boolean;has_draft:boolean;source_excel_available?:boolean;reference_count?:number};
type IRLRow={id:string;ordinal:number;labor:string;peligro:string;riesgo:string;medidas:string;original:string;structured:boolean};
type Detail={cargo:string;irl:{approved:boolean;revision:number|null;records:IRLRow[];has_unstructured:boolean;reference_only?:boolean};
  warnings:string[];can_preview_irl:boolean;reference_total?:number;source_excel_available?:boolean;reference_incomplete_excel_rows?:number[];reference_audit?:ReferenceAudit};
type AuditKind="PERFILES"|"PUESTOS"|"SUSTANCIAS";
type AuditSource={source_sheet:string;source_row:number;source_cargo:string;sections:string[];reference_only:boolean};
type AuditLink={match_count:number;source_entries:AuditSource[];missing:boolean;ambiguous:boolean;suggested_aliases_pending_review:string[]};
type ReferenceAudit={risk_count:number;incomplete_excel_rows:number[];duplicate_source_numbers:string[];
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
type Props={onEditMatrices?:()=>void};

export default function JavieraIRLStructure({onEditMatrices}:Props){
  const [roles,setRoles]=useState<Role[]>([]);
  const [cargo,setCargo]=useState("");
  const [query,setQuery]=useState("");
  const [detail,setDetail]=useState<Detail|null>(null);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [roleLoading,setRoleLoading]=useState(false);

  useEffect(()=>{
    let active=true;
    void request<{roles:Role[];partial:boolean}>("/javiera/v194/roles")
      .then(payload=>{
        if(!active)return;
        setRoles(payload.roles);
        setCargo(previous=>previous||payload.roles.find(r=>r.has_approved_irl)?.cargo||"");
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

  const filtered=useMemo(()=>roles.filter(r=>r.cargo.toLocaleLowerCase("es")
    .includes(query.trim().toLocaleLowerCase("es"))),[roles,query]);
  const rows=detail?.irl.records||[];
  const unstructured=rows.some(r=>!r.structured);
  const current=detail?.cargo===cargo&&!roleLoading?detail:null;
  return <div className="jir-root">
    <div className="jir-intro">
      <div><div className="jir-kicker"><ClipboardList size={16}/> Estructura IRL · revisión integral</div>
        <h4>Formato original, datos vinculados y matriz de riesgos</h4>
        <p>Esta hoja muestra la estructura fija del IRL y los riesgos de la matriz aprobada del cargo.
          No debes escribir HTML ni pegar la matriz en el documento.</p>
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

    <div className="jir-scroll">
      <article className="jir-page" aria-label="Estructura IRL en tamaño de hoja A4">
        <div className="jir-print-label">VISTA ESTRUCTURAL · DOCUMENTO A4 (NO APTO PARA IMPRESIÓN)</div>
        <div className="jir-doc-head"><span>DOCUMENTACIÓN LABORAL Y PREVENTIVA</span>
          <h3>INFORMACIÓN DE RIESGOS LABORALES (IRL)</h3>
        </div>
        <table className="jir-identity"><tbody>
          <tr><th>Empresa</th><td>Dato del expediente</td><th>RUT empresa</th><td>Dato del expediente</td></tr>
          <tr><th>Trabajador/a</th><td>Dato del expediente</td><th>RUT trabajador/a</th><td>Dato del expediente</td></tr>
          <tr><th>Obra</th><td>Dato del expediente</td><th>Cargo</th><td>{cargo||"Selecciona un cargo"}</td></tr>
          <tr><th>Fecha</th><td>Dato del expediente</td><th>Versión / referencia</th>
            <td>{current?.irl.approved?"IRL revisión "+current.irl.revision:current?.source_excel_available?"Excel de referencia — no aprobado":"Pendiente de aprobación"}</td></tr>
        </tbody></table>
        <h4>INFORMACIÓN DE RIESGOS LABORALES DEL CARGO</h4>
        <p className="jir-doc-note">Tareas, peligros, riesgos y medidas de control registradas
          en la matriz preventiva vigente del cargo.</p>
        <table className="jir-risk-table"><thead><tr>
          <th>N.º</th><th>Labor o tarea</th><th>Peligro</th><th>Riesgo</th><th>Medidas preventivas</th>
        </tr></thead><tbody>
          {rows.length>0?rows.map(row=><tr key={row.id}>
            <td>{row.ordinal}</td>
            {row.structured?<><td>{row.labor}</td><td>{row.peligro}</td>
              <td>{row.riesgo}</td><td>{row.medidas}</td></>:
              <td colSpan={4}><strong>Registro original pendiente de estructurar:</strong>
                <span className="jir-original">{row.original}</span></td>}
          </tr>):<tr><td colSpan={5} className="jir-empty">
            {roleLoading?"Consultando matriz...":!cargo?"Selecciona un cargo para cargar los riesgos reales.":
              "Este cargo no tiene matriz IRL aprobada con contenido disponible. No se generarán riesgos ficticios."}
          </td></tr>}
        </tbody></table>
        <section className="jir-signatures">
          <h4>FIRMAS</h4>
          <div><div>Firma trabajador/a</div><div>Firma responsable</div></div>
        </section>
      </article>
    </div>
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
              <strong>{linked.missing?"Sin vinculación":linked.ambiguous?"Revisar duplicidad":"Referencia disponible"}</strong>
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
        <summary>Contenido del IRL original todavía no migrado: cinco bloques gráficos</summary>
        <ol>{current.reference_audit.original_visual_blocks.map(block=>
          <li key={block.title}>{block.title} · pendiente de transcripción y validación HTML</li>)}</ol>
        <p>No se puede certificar todavía que la vista estructural o el PDF reproduzcan
          la totalidad de las páginas del Excel original.</p>
      </details>
      {current.reference_audit.warnings.length>0&&<details className="jir-audit-alerts">
        <summary>Observaciones de integridad ({current.reference_audit.warnings.length})</summary>
        <ul>{current.reference_audit.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>
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
        guardado. Las celdas «Dato del expediente» son referencias visuales: no se imprimen de esta forma.
        Para cambiar un riesgo o una medida preventiva, usa «Matrices y cargos» y aprueba una revisión.</p>
    </div>
  </div>;
}
