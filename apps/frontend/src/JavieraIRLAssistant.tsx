import {useEffect,useMemo,useState} from "react";
import {AlertTriangle,CheckCircle2,ClipboardList,Search,ShieldCheck} from "lucide-react";
import {request} from "./api";
import "./javiera-irl-assistant.css";

type Role={cargo:string;has_approved_irl:boolean;has_approved_pts:boolean;has_draft:boolean;source_excel_available?:boolean;reference_count?:number};
type RecordIRL={id:string;ordinal:number;labor:string;peligro:string;riesgo:string;
  medidas:string;original:string;structured:boolean};
type RoleDetail={
  cargo:string;
  irl:{approved:boolean;revision:number|null;matrix_id:string|null;
    records:RecordIRL[];has_unstructured:boolean};
  pts:{approved:boolean;revision:number|null;sections_complete:boolean;section_count:number;
    sections:string[];source_columns:string[];headings:string[]};
  additional_matrices:Record<string,{revision:number|null;available:boolean;sections:string[]}>;
  can_preview_irl:boolean;warnings:string[];reference_total?:number;source_excel_available?:boolean;
};
type Props={cargo:string;documentKind:"irl"|"pts";onCargoChange:(cargo:string)=>void;
  manualLabor:string;onManualLaborChange:(labor:string)=>void;
  reviewedLaborIds:string;onReviewedLaborIdsChange:(ids:string)=>void};

export default function JavieraIRLAssistant({
  cargo,documentKind,onCargoChange,manualLabor,onManualLaborChange,reviewedLaborIds,onReviewedLaborIdsChange,
}:Props){
  const [query,setQuery]=useState("");
  const [matches,setMatches]=useState<Role[]>([]);
  const [detail,setDetail]=useState<RoleDetail|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{
    let active=true;
    const id=window.setTimeout(()=>{
      void request<{roles:Role[]}>("/javiera/v194/roles?query="+encodeURIComponent(query))
        .then(result=>{if(active)setMatches(result.roles);})
        .catch(e=>{if(active)setError(e instanceof Error?e.message:String(e));});
    },250);
    return()=>{active=false;window.clearTimeout(id);};
  },[query]);
  useEffect(()=>{
    if(!cargo.trim()){setDetail(null);return;}
    let active=true;
    setLoading(true);
    const id=window.setTimeout(()=>{
      void request<RoleDetail>("/javiera/v194/role?cargo="+encodeURIComponent(cargo.trim()))
        .then(result=>{if(active){setDetail(result);setError("");}})
        .catch(e=>{if(active){setDetail(null);setError(e instanceof Error?e.message:String(e));}})
        .finally(()=>{if(active)setLoading(false);});
    },300);
    return()=>{active=false;window.clearTimeout(id);};
  },[cargo]);
  const reviewed=useMemo(()=>new Set(reviewedLaborIds.split(",").filter(Boolean)),[reviewedLaborIds]);
  const tasks=detail?.irl.records||[];
  function toggleLabor(id:string){
    const next=new Set(reviewed);
    if(next.has(id))next.delete(id);else next.add(id);
    onReviewedLaborIdsChange([...next].join(","));
  }
  return <section className="jia-root" aria-label="Asistente de labores y riesgos IRL">
    <div className="jia-heading"><ClipboardList size={19}/>
      <div><h4>{documentKind==="pts"?"Labores y procedimiento PTS del cargo":"Labores y matriz IRL del cargo"}</h4>
        <p>Selecciona un cargo existente y revisa sus tareas, peligros y controles reales.</p></div>
    </div>
    <label className="jia-label" htmlFor="jia-role-search"><Search size={15}/> Buscar cargos de matrices</label>
    <input id="jia-role-search" type="search" value={query} onChange={e=>setQuery(e.target.value)}
      placeholder="Buscar pintor, carpintero, soldador…"/>
    <div className="jia-roles" role="group" aria-label="Cargos disponibles">
      {matches.slice(0,20).map(entry=><button key={entry.cargo} type="button"
        className={entry.cargo===cargo?"selected":""}
        onClick={()=>{onCargoChange(entry.cargo);setQuery("");onReviewedLaborIdsChange("");}}>
        {entry.cargo}
        {entry.has_approved_irl?<small>IRL aprobada</small>:entry.source_excel_available?<small>Excel original · {entry.reference_count} riesgos</small>:<small>Sin IRL aprobada</small>}
      </button>)}
      {matches.length===0&&query&&<p>No hay coincidencias aprobadas. Puedes escribir el cargo manualmente en Datos compartidos.</p>}
    </div>
    {cargo.trim()&&<div className="jia-selection">
      <strong>Cargo del expediente: {cargo}</strong>
      {loading?<span>Cargando matriz…</span>:detail&&<>
        <div className="jia-tags">
          <span>{detail.irl.approved?"IRL aprobada · revisión "+detail.irl.revision:"IRL sin aprobación"}</span>
          <span>{detail.pts.approved?"PTS aprobado · revisión "+detail.pts.revision:"PTS pendiente"}</span>
          <span>{tasks.length} registros IRL del cargo</span>
        </div>
        {detail.warnings.map((warning,i)=><p className="jia-warning" key={i}>
          <AlertTriangle size={15}/> {warning}</p>)}
        {tasks.length>0&&<>
          <p>Revisa las labores del Excel original. Las matrices que aún no tienen aprobación de Prevención son solo referencias y no se imprimen. El PDF conserva por
            seguridad todos los riesgos de la matriz aprobada hasta que exista una
            selección preventiva validada; marcar una labor no modifica la matriz.</p>
          <div className="jia-table-wrap"><table>
            <thead><tr><th>Revisada</th><th>Labor / tarea</th><th>Peligro</th><th>Riesgo</th><th>Medida preventiva</th></tr></thead>
            <tbody>{tasks.map(task=><tr key={task.id}>
              <td><input type="checkbox" aria-label={"Revisar labor "+task.ordinal}
                checked={reviewed.has(task.id)}
                onChange={()=>toggleLabor(task.id)}/></td>
              {task.structured?<><td>{task.labor}</td><td>{task.peligro}</td>
                <td>{task.riesgo}</td><td>{task.medidas}</td></>:
                <td colSpan={4}><AlertTriangle size={14}/> Contenido original sin los cuatro campos:
                  <pre>{task.original}</pre></td>}
            </tr>)}</tbody></table></div>
          <p className="jia-summary"><ShieldCheck size={15}/> {tasks.filter(t=>reviewed.has(t.id)).length}
            {" de "}{tasks.length} labores revisadas; la revisión no equivale a aprobación preventiva.</p>
        </>}
        {detail.pts.sections.length>0&&<details className="jia-related">
          <summary>Ver {detail.pts.sections.length} apartados del PTS aprobado
            {" "}(columnas de origen D:T)</summary>
          <ol>{detail.pts.sections.map((section,i)=><li key={i}>
            <strong>{detail.pts.headings[i]||"Apartado sin encabezado"}</strong>
            <small> · Columna {detail.pts.source_columns[i]||"?"}</small>
            <p>{section}</p>
          </li>)}</ol>
          <p>Los encabezados se contrastaron con la hoja MATRIZ PTS del Excel corregido.
            La aprobación profesional del procedimiento sigue siendo obligatoria.</p>
        </details>}
        <details className="jia-related"><summary>Ver matrices relacionadas del cargo</summary>
          {Object.entries(detail.additional_matrices).map(([kind,data])=>
            <div key={kind}><strong>{kind}</strong>
              <span>{data.available?"Revisión "+data.revision:"Sin revisión aprobada"}</span>
              {data.available&&<ul>{data.sections.map((section,i)=><li key={i}>{section}</li>)}</ul>}
            </div>)}
        </details>
      </>}
    </div>}
    <label className="jia-label" htmlFor="jia-manual-labor">Nueva labor no registrada (opcional)</label>
    <textarea id="jia-manual-labor" rows={2} maxLength={1000}
      value={manualLabor} onChange={e=>onManualLaborChange(e.target.value)}
      placeholder="Describe la labor real que falta en las matrices"/>
    {manualLabor.trim()?<p className="jia-warning"><AlertTriangle size={15}/>
      Labor nueva detectada. Se conservará al guardar el borrador y requiere revisión preventiva.
      El IRL y PTS no se podrán imprimir hasta vincularla a una matriz aprobada.</p>
      :detail?.can_preview_irl?<p className="jia-ready"><CheckCircle2 size={15}/>
      Matriz IRL estructurada disponible. Completa la identificación y la fecha del documento para obtener el PDF A4.</p>:null}
    {error&&<p className="jia-warning" role="alert">{error}</p>}
  </section>;
}
