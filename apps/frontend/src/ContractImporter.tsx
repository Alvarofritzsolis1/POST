import {useState,type FormEvent} from "react"
import {AlertCircle,CheckCircle2,FileSpreadsheet,LoaderCircle,UploadCloud} from "lucide-react"
import {opsControlApi,type ContractImportPreview,type ContractImportRow} from "./opsControlApi"

const dateFields=new Set(["start_date","end_date","amendment_date"])
const fields:Array<{key:keyof ContractImportRow;label:string}>=[
  {key:"contractor_rut",label:"RUT empresa"},
  {key:"worker_rut",label:"RUT trabajador"},
  {key:"kind",label:"Registro"},
  {key:"contract_type",label:"Tipo de contrato"},
  {key:"start_date",label:"Inicio"},
  {key:"end_date",label:"Término"},
  {key:"amendment_date",label:"Fecha anexo"},
  {key:"reference",label:"Folio / referencia"},
  {key:"status",label:"Estado"},
  {key:"notes",label:"Observaciones"}
]
const errorText=(error:unknown)=>error instanceof Error?error.message:"Ocurrió un error"
export default function ContractImporter({siteId,onImported}:{siteId:string;onImported:()=>void}){
  const [file,setFile]=useState<File|null>(null)
  const [preview,setPreview]=useState<ContractImportPreview|null>(null)
  const [rows,setRows]=useState<ContractImportRow[]>([])
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState("")
  const [notice,setNotice]=useState("")
  const [page,setPage]=useState(0)
  const size=30
  const totalPages=Math.max(1,Math.ceil(rows.length/size))
  function edit(index:number,key:keyof ContractImportRow,value:string){
    setRows(list=>list.map((r,i)=>i===index?{...r,[key]:value,errors:[]}:r))
  }
  async function upload(event:FormEvent){
    event.preventDefault()
    if(!file)return
    setBusy(true);setError("");setNotice("")
    try{
      const result=await opsControlApi.previewContracts(file,siteId)
      setPreview(result);setRows(result.rows);setPage(0)
      setNotice("Vista previa preparada. Corrige las filas y confirma antes de importar.")
    }catch(err){setError(errorText(err))}
    finally{setBusy(false)}
  }
  async function commit(){
    if(!preview||!rows.length)return
    if(!window.confirm("¿Importar "+rows.length+" registros al historial de esta obra? No sobrescribirá contratos conflictivos."))return
    setBusy(true);setError("");setNotice("")
    try{
      const result=await opsControlApi.commitContracts(siteId,rows,preview.preview_token)
      setNotice("Importados "+result.created+" contratos, "+result.amendments+" anexos y "+result.unchanged+" registros existentes sin cambios.")
      setPreview(null);setRows([]);setFile(null);onImported()
    }catch(err){setError(errorText(err))}
    finally{setBusy(false)}
  }
  return <section className="control-card contract-importer">
    <h3>Importación histórica de contratos y anexos</h3>
    <p>Importa datos desde Excel o CSV sin volver a escribir empresas y trabajadores. Primero deben existir en la obra: el sistema relaciona cada contrato mediante RUT y valida los anexos por referencia.</p>
    <a className="secondary control-download" href={opsControlApi.contractTemplate()}><FileSpreadsheet size={16}/> Descargar plantilla de contratos</a>
    <form className="control-form-inline" onSubmit={event=>void upload(event)}>
      <label>Archivo Excel o CSV
        <input type="file" accept=".xlsx,.csv" onChange={event=>{setFile(event.target.files?.[0]??null);setPreview(null)}}/>
      </label>
      <button className="secondary" type="submit" disabled={!file||busy}><UploadCloud size={16}/> Previsualizar</button>
    </form>
    {error&&<p role="alert" className="form-error"><AlertCircle size={16}/>{error}</p>}
    {notice&&<p role="status" className="alert success"><CheckCircle2 size={16}/>{notice}</p>}
    {preview&&<div className="contract-import-preview">
      <p><strong>{preview.summary.total} filas</strong> · {preview.summary.contracts} contratos · {preview.summary.amendments} anexos · {preview.summary.errors} filas con problemas detectados inicialmente.</p>
      <p>Las correcciones de columnas se validarán nuevamente en el servidor antes de guardar. Una importación con conflictos se cancela completa.</p>
      <div className="table-wrap"><table className="control-table">
        <thead><tr><th>Fila</th>{fields.map(f=><th key={f.key}>{f.label}</th>)}<th>Diagnóstico</th></tr></thead>
        <tbody>{rows.slice(page*size,page*size+size).map((r,i)=>{
          const absolute=page*size+i
          return <tr key={r.row_id}><td>{r.row_id}</td>
            {fields.map(f=><td key={f.key}>
              {f.key==="kind"?<select value={r.kind} onChange={e=>edit(absolute,f.key,e.target.value)}><option value="contract">Contrato</option><option value="amendment">Anexo</option></select>:
               f.key==="contract_type"?<select value={r.contract_type||""} onChange={e=>edit(absolute,f.key,e.target.value)}>
                 <option value="">Sin clasificar</option><option value="fixed_term">Plazo fijo</option>
                 <option value="indefinite">Indefinido</option><option value="project">Por obra</option>
                 <option value="services">Prestación de servicios</option></select>:
               f.key==="status"?<select value={r.status||"active"} onChange={e=>edit(absolute,f.key,e.target.value)}>
                 <option value="active">Vigente</option><option value="ended">Terminado</option><option value="suspended">Suspendido</option></select>:
               <input aria-label={f.label+" fila "+r.row_id} type={dateFields.has(f.key)?"date":"text"}
                 value={String(r[f.key]??"")} onChange={e=>edit(absolute,f.key,e.target.value)}/>}
            </td>)}
            <td>{r.errors.length?<span className="form-error">{r.errors.join("; ")}</span>:"Por validar"}</td></tr>
        })}</tbody></table></div>
      <div className="control-bulk">
        <span>Página {page+1} de {totalPages}</span>
        <button className="secondary" disabled={page===0} onClick={()=>setPage(p=>p-1)} type="button">Anterior</button>
        <button className="secondary" disabled={page+1>=totalPages} onClick={()=>setPage(p=>p+1)} type="button">Siguiente</button>
        <button className="primary" disabled={busy} onClick={()=>void commit()} type="button">
          {busy?<LoaderCircle size={16} className="spin"/>:<CheckCircle2 size={16}/>} Confirmar importación</button>
      </div>
    </div>}
  </section>
}
