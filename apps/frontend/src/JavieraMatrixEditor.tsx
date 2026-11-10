import {useEffect,useMemo,useState} from "react";
import {ArrowRight,CheckCircle2,ClipboardList,FileSpreadsheet,Plus,Save,Search,ShieldCheck} from "lucide-react";
import {request} from "./api";
import "./javiera-matrix-editor.css";

type Kind="IRL"|"PTS"|"PUESTOS"|"PERFILES"|"SUSTANCIAS";
type Matrix={id:string;kind:Kind;cargo:string;sections:string[];revision:number;status:string;source:string;author_id:string};
type Impact={kind:Kind;cargo:string;new_pdf_formats:string[];affected_dossiers:number;
  count_is_partial:boolean;current_approved_revision:number|null;latest_revision:number|null;
  pending_revisions:number[];historical_pdfs_unchanged:boolean;needs_explicit_review:boolean;message:string};
const kinds:Kind[]=["IRL","PTS","PERFILES","PUESTOS","SUSTANCIAS"];
const labels:Record<Kind,string>={IRL:"Riesgos laborales (IRL)",PTS:"Procedimientos seguros (PTS)",
  PERFILES:"Descripción de cargos",PUESTOS:"Matriz IRL optimizada",SUSTANCIAS:"Sustancias"};
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
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);
function fingerprint(kind:Kind,cargo:string,sections:string[]){
  return JSON.stringify([kind,cargo,sections]);
}
export default function JavieraMatrixEditor(){
  const [rows,setRows]=useState<Matrix[]>([]);
  const [kind,setKind]=useState<Kind>("IRL");
  const [search,setSearch]=useState("");
  const [selectedId,setSelectedId]=useState("");
  const [cargo,setCargo]=useState("");
  const [sections,setSections]=useState<string[]>([]);
  const [impact,setImpact]=useState<Impact|null>(null);
  const [impactFingerprint,setImpactFingerprint]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [soloPilot,setSoloPilot]=useState(false);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const current=rows.find(x=>x.id===selectedId);
  const versions=useMemo(()=>rows.filter(x=>x.kind===kind&&x.cargo===cargo)
    .sort((a,b)=>b.revision-a.revision),[rows,kind,cargo]);
  const latest=useMemo(()=>{
    const seen=new Set<string>();
    return rows.filter(row=>row.kind===kind).filter(row=>{
      if(seen.has(row.cargo))return false;
      seen.add(row.cargo);return true;
    }).filter(row=>row.cargo.toLocaleLowerCase("es").includes(search.toLocaleLowerCase("es")));
  },[rows,kind,search]);
  const changed=!!current && (sections.length!==current.sections.length ||
    sections.some((s,i)=>s!==current.sections[i]));
  const approved=versions.find(r=>r.status==="approved");
  const changes=approved?Math.max(approved.sections.length,sections.length)===0?0:
    Array.from({length:Math.max(approved.sections.length,sections.length)},(_,i)=>
      approved.sections[i]!==sections[i]?1:0).reduce((a,b)=>a+b,0):sections.length;
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
  function invalidate(){setImpact(null);setImpactFingerprint("");setConfirmed(false);}
  function selectRecord(row:Matrix){
    setKind(row.kind);setCargo(row.cargo);setSections([...row.sections]);setSelectedId(row.id);
    invalidate();setError("");setMessage("");
  }
  function newRecord(){
    setCargo("");setSelectedId("");
    setSections(Array(kind==="PTS"?17:1).fill(""));invalidate();
    setMessage("Cargo nuevo: el primer guardado será una revisión en borrador.");
  }
  function selectKind(value:Kind){
    setKind(value);setSelectedId("");setCargo("");
    setSections(Array(value==="PTS"?17:1).fill(""));invalidate();
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
        method:"POST",body:JSON.stringify({kind,cargo,sections,source:"Editor visual GALANT 19.2"})
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
  function appendRow(){
    if(kind==="PTS"||sections.length>=35)return;
    setSections(prev=>[...prev,kind==="IRL"?
      "Tarea: \nPeligro: \nRiesgo: \nMedidas: ":""]);invalidate();
  }
  return <section className="jmx-root">
    <header className="jmx-top"><div><small>PROYECTO JAVIERA · 19.2</small>
      <h2><ClipboardList size={23}/> Matrices y cargos</h2>
      <p>Revisa riesgos, controles y procedimientos por cargo, sin editar Excel. Cada cambio crea una revisión separada.</p>
    </div><button type="button" onClick={newRecord}><Plus size={16}/> Nuevo cargo</button></header>
    {error&&<p className="jmx-error" role="alert">{error}</p>}
    {message&&<p className="jmx-success" role="status"><CheckCircle2 size={17}/>{message}</p>}
    <div className="jmx-grid">
      <aside className="jmx-aside">
        <label htmlFor="jmx-kind">Tipo de matriz</label>
        <select id="jmx-kind" value={kind} onChange={e=>selectKind(e.target.value as Kind)}>
          {kinds.map(k=><option key={k} value={k}>{labels[k]}</option>)}
        </select>
        <label htmlFor="jmx-search"><Search size={14}/> Buscar cargo</label>
        <input id="jmx-search" type="search" value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="Ej. carpintero, pintor"/>
        {loading?<p>Cargando matrices…</p>:<div className="jmx-items">
          <small>{latest.length} cargos encontrados</small>
          {latest.map(row=><button key={row.id} type="button" className={row.cargo===cargo?"chosen":""}
            onClick={()=>selectRecord(row)}><span>{row.cargo}<small>{row.kind} · Revisión {row.revision}
              {" · "+(row.status==="approved"?"Aprobada":"Borrador")}</small></span><ArrowRight size={14}/></button>)}
          {!latest.length&&<p>Sin cargos en esta categoría. Puedes agregar uno sin afectar otras matrices.</p>}
        </div>}
      </aside>
      <div className="jmx-editor">
        <div className="jmx-controls">
          <label>Cargo / puesto
            <input value={cargo} onChange={e=>{setCargo(e.target.value);setSelectedId("");invalidate();}}
              maxLength={160} placeholder="Cargo según matriz original"/>
          </label>
          <label>Revisión
            <select value={selectedId} onChange={e=>{
              const row=rows.find(x=>x.id===e.target.value);if(row)selectRecord(row);
            }} disabled={!versions.length}>
              {!versions.length&&<option value="">Nueva</option>}
              {versions.map(row=><option key={row.id} value={row.id}>
                Revisión {row.revision} · {row.status==="approved"?"Aprobada":"Borrador"}
              </option>)}
            </select>
          </label>
        </div>
        <div className="jmx-summary">
          <span><FileSpreadsheet size={15}/> {sections.length} apartados / registros</span>
          <span>{approved?"Aprobada v"+approved.revision:"Sin revisión aprobada"}</span>
          <span>{changes} apartados distintos de la aprobada</span>
        </div>
        {kind==="IRL"?<div className="jmx-table-scroll">
          <table><thead><tr><th>N°</th><th>Tarea</th><th>Peligro</th><th>Riesgo</th><th>Medidas preventivas</th></tr></thead>
            <tbody>{sections.map((section,index)=>{
              const parsed=splitSection(section);
              return <tr key={index}><th scope="row">{index+1}</th>
                {parsed?parsed.map((value,col)=><td key={col}><textarea rows={4}
                  aria-label={names[col]+" fila "+(index+1)} value={value}
                  onChange={e=>edit(index,withColumn(section,col,e.target.value))}/></td>):
                <td colSpan={4}><label>Contenido original sin estructura de cuatro campos
                  <textarea rows={5} value={section}
                    onChange={e=>edit(index,e.target.value)}/></label></td>}
              </tr>;
            })}</tbody></table></div>:<div className="jmx-rows">
          {sections.map((section,index)=><label key={index}>
            <span>{kind==="PTS"?"Apartado técnico":"Campo"} {index+1}
              {approved && approved.sections[index]!==section?" · Modificado":""}</span>
            <textarea value={section} rows={3} onChange={e=>edit(index,e.target.value)}/>
          </label>)}</div>}
        {kind!=="PTS"&&<button className="jmx-add" type="button" onClick={appendRow}
          disabled={sections.length>=35}><Plus size={15}/> Agregar fila (máx. 35 por cargo)</button>}
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
            <p><strong>Última revisión aprobada:</strong> {impact.current_approved_revision||"Ninguna"}</p>
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
