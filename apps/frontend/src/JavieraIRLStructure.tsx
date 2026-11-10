import {useEffect,useMemo,useState} from "react";
import {AlertTriangle,ClipboardList,FileSpreadsheet,Search,ShieldCheck} from "lucide-react";
import {request} from "./api";
import "./javiera-irl-structure.css";

type Role={cargo:string;has_approved_irl:boolean;has_approved_pts:boolean;has_draft:boolean};
type IRLRow={id:string;ordinal:number;labor:string;peligro:string;riesgo:string;medidas:string;original:string;structured:boolean};
type Detail={cargo:string;irl:{approved:boolean;revision:number|null;records:IRLRow[];has_unstructured:boolean};
  warnings:string[];can_preview_irl:boolean};
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
    void request<{roles:Role[];partial:boolean}>("/javiera/v193/roles")
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
    void request<Detail>("/javiera/v193/role?cargo="+encodeURIComponent(cargo))
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
      <div><div className="jir-kicker"><ClipboardList size={16}/> Estructura del IRL · GALANT 19.3.1</div>
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
          {item.cargo}{item.has_approved_irl?" · IRL aprobada":" · sin IRL aprobada"}
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
        <div className="jir-print-label">ESTRUCTURA DEL DOCUMENTO · A4</div>
        <div className="jir-doc-head"><span>DOCUMENTACIÓN LABORAL Y PREVENTIVA</span>
          <h3>INFORMACIÓN DE RIESGOS LABORALES (IRL)</h3>
        </div>
        <table className="jir-identity"><tbody>
          <tr><th>Empresa</th><td>Dato del expediente</td><th>RUT empresa</th><td>Dato del expediente</td></tr>
          <tr><th>Trabajador/a</th><td>Dato del expediente</td><th>RUT trabajador/a</th><td>Dato del expediente</td></tr>
          <tr><th>Obra</th><td>Dato del expediente</td><th>Cargo</th><td>{cargo||"Selecciona un cargo"}</td></tr>
          <tr><th>Fecha</th><td>Dato del expediente</td><th>Versión / referencia</th>
            <td>{current?.irl.approved?"IRL revisión "+current.irl.revision:"Pendiente de aprobación"}</td></tr>
        </tbody></table>
        <h4>INFORMACIÓN DE RIESGOS LABORALES DEL CARGO</h4>
        <p className="jir-doc-note">Tareas, peligros, riesgos y medidas de control registradas
          en la matriz preventiva vigente del cargo.</p>
        <table className="jir-risk-table"><thead><tr>
          <th>N.º</th><th>Labor o tarea</th><th>Peligro</th><th>Riesgo</th><th>Medidas preventivas</th>
        </tr></thead><tbody>
          {current?.irl.approved&&rows.length>0?rows.map(row=><tr key={row.id}>
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
    <div className="jir-footer" role="status">
      {current?.irl.approved?<p className={unstructured?"jir-warning":"jir-status"}>
        {unstructured?<AlertTriangle size={16}/>:<ShieldCheck size={16}/>}
        {rows.length} registros del cargo «{cargo}» · revisión IRL {current.irl.revision}.
        {unstructured?" Existen filas incompletas; requieren revisión preventiva antes del PDF.":
          " Matriz aprobada vinculada; el PDF final se genera desde un expediente."}
      </p>:<p className="jir-warning"><AlertTriangle size={16}/>
        Esta es la estructura del formato, no un PDF emitible ni una aprobación preventiva.
        Para impresión real debes seleccionar un expediente con matriz aprobada.</p>}
      <p className="jir-explanation">El documento A4 definitivo y sus firmas se obtienen desde el expediente
        guardado. Las celdas «Dato del expediente» son referencias visuales: no se imprimen de esta forma.
        Para cambiar un riesgo o una medida preventiva, usa «Matrices y cargos» y aprueba una revisión.</p>
    </div>
  </div>;
}
