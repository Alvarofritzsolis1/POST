import {useCallback,useEffect,useState,type FormEvent} from "react"
import {CheckCircle2,FileText,LoaderCircle,RefreshCcw,UploadCloud} from "lucide-react"
import {api,type DocumentSummary} from "./api"
import {opsApi,type Contractor,type MonthlyRecord} from "./opsApi"
import {opsControlApi,type Requirement} from "./opsControlApi"
import "./monthly.css"

const types=[
  {value:"cotizaciones",label:"Pago de cotizaciones"},
  {value:"f30_1",label:"Formulario F30-1"},
  {value:"asistencia",label:"Registro de asistencia"},
  {value:"liquidaciones",label:"Liquidaciones de sueldo"},
  {value:"porteria",label:"Informe de portería"},
  {value:"declaracion_jurada",label:"Declaración jurada"},
  {value:"anticipos",label:"Listado de anticipos"},
  {value:"otros",label:"Otro documento"}
]
const statuses:Record<string,string>={
  pending:"Pendiente de revisión",approved:"Aprobado",observed:"Observado",
  rejected:"Rechazado",not_applicable:"No aplica",needs_classification:"Definir exigibilidad",
  not_yet_required:"No exigible todavía",overdue:"Vencido",
  schedule_not_configured:"Sin calendario configurado"
}
const nameOf=(kind:string)=>types.find(item=>item.value===kind)?.label||kind
const todayMonth=()=>{const now=new Date();return now.getFullYear()+"-"+String(now.getMonth()+1).padStart(2,"0")}
const errText=(error:unknown)=>error instanceof Error?error.message:"No fue posible completar la operación"

export default function MonthlyDocuments({contractor,readOnly}:{contractor:Contractor;readOnly:boolean}){
  const [period,setPeriod]=useState(todayMonth)
  const [rows,setRows]=useState<MonthlyRecord[]>([])
  const [requirements,setRequirements]=useState<Requirement[]>([])
  const [existing,setExisting]=useState<DocumentSummary[]>([])
  const [kind,setKind]=useState("cotizaciones")
  const [file,setFile]=useState<File|null>(null)
  const [existingId,setExistingId]=useState("")
  const [busy,setBusy]=useState(false)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState("")
  const [notice,setNotice]=useState("")
  const [notes,setNotes]=useState<Record<string,string>>({})
  const independent=contractor.nature==="independent"
  const withWorkers=contractor.nature==="with_workers"
  const required=types.filter(t=>t.value!=="otros").map(t=>t.value)

  const reload=useCallback(async()=>{
    const [monthly,uploads,matrix]=await Promise.all([
      opsApi.monthlyDocuments(contractor.id,period),api.list(),
      opsControlApi.matrix(contractor.site_id,period)
    ])
    setRows(monthly)
    setExisting(uploads)
    setRequirements(matrix.contractors.find(c=>c.association_id===contractor.id)?.requirements||[])
  },[contractor.id,contractor.site_id,period])

  useEffect(()=>{
    let active=true
    const refresh=async()=>{
      try{
        const [monthly,uploads,matrix]=await Promise.all([
          opsApi.monthlyDocuments(contractor.id,period),api.list(),
          opsControlApi.matrix(contractor.site_id,period)
        ])
        if(active){setRows(monthly);setExisting(uploads);setRequirements(matrix.contractors.find(c=>c.association_id===contractor.id)?.requirements||[]);setError("");setLoading(false)}
      }catch(err){if(active){setError(errText(err));setLoading(false)}}
    }
    setRows([]);setLoading(true);setError("");setNotice("")
    void refresh()
    const interval=window.setInterval(()=>void refresh(),15000)
    return()=>{active=false;window.clearInterval(interval)}
  },[contractor.id,contractor.site_id,period])

  async function uploadAndLink(event:FormEvent){
    event.preventDefault()
    if(readOnly||!file)return
    setBusy(true);setError("");setNotice("")
    try{
      const category=kind==="cotizaciones"?"cotizaciones":kind==="f30_1"?"f30_1":"auto"
      const uploaded=await api.upload(file,category)
      try{
        await opsApi.linkMonthly({association_id:contractor.id,period,kind,document_id:uploaded.id})
      }catch(error){
        setExistingId(uploaded.id)
        throw new Error("Archivo recibido en OCR (ID "+uploaded.id+"), pero no vinculado al mes: "+errText(error)+". Puedes vincularlo desde el selector.")
      }
      setFile(null)
      const element=document.getElementById("monthly-file") as HTMLInputElement|null
      if(element)element.value=""
      await reload()
      setNotice("PDF asociado a "+period+". Pendiente de revisión humana.")
    }catch(err){setError(errText(err))}
    finally{setBusy(false)}
  }
  async function linkExisting(){
    if(readOnly||!existingId)return
    setBusy(true);setError("");setNotice("")
    try{
      await opsApi.linkMonthly({association_id:contractor.id,period,kind,document_id:existingId})
      await reload();setExistingId("");setNotice("Documento existente vinculado al período.")
    }catch(err){setError(errText(err))}
    finally{setBusy(false)}
  }
  async function markNotApplicable(kindValue:string){
    if(readOnly)return
    setBusy(true);setError("");setNotice("")
    try{
      await opsApi.linkMonthly({association_id:contractor.id,period,kind:kindValue,not_applicable:true,notes:"Excepción registrada manualmente"})
      await reload();setNotice("Requisito marcado No aplica. Se registró en auditoría.")
    }catch(err){setError(errText(err))}
    finally{setBusy(false)}
  }
  async function review(row:MonthlyRecord,status:MonthlyRecord["review_status"]){
    if(readOnly)return
    setBusy(true);setError("");setNotice("")
    try{
      await opsApi.reviewMonthly(row.id,status,notes[row.id]??row.notes)
      await reload();setNotice("Revisión guardada y disponible para los demás usuarios.")
    }catch(err){setError(errText(err))}
    finally{setBusy(false)}
  }
  async function manualReview(documentKind:string,status:"approved"|"observed"|"pending"|"not_applicable"){
    if(readOnly)return
    let message=""
    if(status==="observed"||status==="not_applicable"){
      const entered=window.prompt("Justifica la revisión de "+nameOf(documentKind)+":")
      if(entered===null)return
      message=entered.trim()
      if(!message){setError("Indica un motivo para registrar este estado");return}
    }
    setBusy(true);setError("");setNotice("")
    try{
      await opsControlApi.reviews({association_id:contractor.id,period,kind:documentKind,status,notes:message})
      await reload();setNotice("Revisión guardada para todos los usuarios autorizados.")
    }catch(err){setError(errText(err))}
    finally{setBusy(false)}
  }
  const latest=(documentKind:string)=>rows.find(row=>row.kind===documentKind)
  const eligible=requirements.filter(r=>r.applicable===true)
  const approved=eligible.filter(r=>r.state==="approved").length
  return <section className="monthly-panel" aria-labelledby="monthly-title">
    <div className="monthly-header">
      <div><span className="eyebrow">CONTROL DOCUMENTAL COMPARTIDO</span><h3 id="monthly-title">Documentación mensual</h3>
        <p>Registros de {contractor.name} en esta obra. Los documentos quedan vinculados al mes de competencia, no al usuario que los cargó.</p></div>
      <div className="monthly-selector"><label htmlFor="monthly-period">Mes de competencia</label>
        <input id="monthly-period" type="month" min="2000-01" max="2099-12" value={period} onChange={e=>setPeriod(e.target.value)}/>
        <button type="button" className="secondary" disabled={loading||busy} onClick={()=>void reload().catch(err=>setError(errText(err)))} title="Actualizar documentos"><RefreshCcw size={16}/> Actualizar</button></div>
    </div>
    <div className="monthly-summary"><strong>{eligible.length?approved+" de "+eligible.length:"Sin evaluar"}</strong><span>requisitos exigibles aprobados en {period}; no aplica y no exigible no cuentan como incumplimiento</span></div>
    {!independent&&!withWorkers&&<p className="ops-help">Contratista sin clasificación documental completa: confirma su naturaleza y obligaciones antes de aprobar el período.</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="alert success" role="status"><CheckCircle2 size={16}/>{notice}</p>}
    {loading?<p><LoaderCircle size={16} className="spin"/> Cargando documentación mensual…</p>:<>
      <div className="table-wrap"><table className="ops-list-table monthly-table"><thead><tr><th>REQUISITO</th><th>ESTADO</th><th>DOCUMENTO</th><th>ACCIÓN</th></tr></thead><tbody>
        {required.map(item=>{const row=latest(item);const req=requirements.find(r=>r.kind===item);const state=req?.state||row?.review_status||"needs_classification";return <tr key={item}>
          <td><strong>{nameOf(item)}</strong><small style={{display:"block"}}>{req?.applicable===null?"Confirmar exigibilidad":req?.applicable===false?"No aplicable":"Requisito aplicable"}</small></td>
          <td><span className={"status "+(state==="approved"?"success":state==="observed"||state==="rejected"||state==="overdue"?"error":"waiting")}>{statuses[state]||state}</span></td>
          <td>{row?.document_id?<a href={api.pdf(row.document_id)} target="_blank" rel="noreferrer">{row.original_name||"Abrir archivo"}</a>:row?"Revisión manual sin archivo":"—"}</td>
          <td>{!readOnly&&req?.applicable===true?<div className="control-cell-actions">
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,"approved")}>Aprobar</button>
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,"observed")}>Observar</button>
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,"pending")}>Pendiente</button>
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,"not_applicable")}>No aplica</button>
          </div>:req?.applicable===null?"Configura la exigibilidad en Centro de control":"—"}</td>
        </tr>})}
      </tbody></table></div>
      {!readOnly&&<div className="monthly-forms">
        <form onSubmit={event=>void uploadAndLink(event)}>
          <h4><UploadCloud size={17}/> Subir documentación mensual</h4>
          <label>Tipo de documento<select value={kind} onChange={e=>setKind(e.target.value)}>{types.map(t=><option key={t.value} value={t.value}>{t.label}</option>)}</select></label>
          <label>Archivo PDF o imagen<input id="monthly-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" onChange={e=>setFile(e.target.files?.[0]||null)}/></label>
          <button className="primary" disabled={!file||busy} type="submit">{busy?"Guardando…":"Subir y asociar a "+period}</button>
        </form>
        <div>
          <h4><FileText size={17}/> Vincular archivo OCR existente</h4>
          <p>Los archivos anteriores no se asignan automáticamente: selecciona el comprobante correcto y el mes correspondiente.</p>
          <label>Documento<select value={existingId} onChange={e=>setExistingId(e.target.value)}>
            <option value="">Seleccionar archivo ya cargado</option>
            {existing.map(d=><option key={d.id} value={d.id}>{d.original_name} · {d.id.slice(0,8)}</option>)}
          </select></label>
          <button className="secondary" disabled={!existingId||busy} type="button" onClick={()=>void linkExisting()}>Vincular al tipo seleccionado</button>
        </div>
      </div>}
      <h4>Historial de archivos y revisión de {period}</h4>
      {rows.length===0?<p className="ops-help">Todavía no hay documentos vinculados a este mes. Los requisitos permanecen visibles para que puedas completarlos.</p>:
      <div className="table-wrap"><table className="ops-list-table monthly-table"><thead><tr><th>FECHA DE CARGA</th><th>TIPO</th><th>ARCHIVO</th><th>REVISIÓN MANUAL</th><th>OBSERVACIÓN</th></tr></thead><tbody>
        {rows.map(row=><tr key={row.id}>
          <td>{new Date(row.created_at).toLocaleDateString("es-CL")}</td>
          <td>{nameOf(row.kind)}</td>
          <td>{row.document_id?<a href={api.pdf(row.document_id)} target="_blank" rel="noreferrer">{row.original_name||"Abrir archivo"}</a>:"Revisión manual sin PDF"}<small className="monthly-ocr"> {row.ocr_status?"OCR: "+row.ocr_status:""}</small></td>
          <td>{readOnly?statuses[row.review_status]:<select aria-label={"Estado documental "+row.id} value={row.review_status} disabled={busy} onChange={e=>void review(row,e.target.value as MonthlyRecord["review_status"])}>
            <option value="pending">Pendiente</option><option value="approved">Aprobado</option><option value="observed">Observado</option><option value="rejected">Rechazado</option>
          </select>}</td>
          <td>{readOnly?row.notes:<input aria-label={"Observación "+row.id} maxLength={2000} placeholder="Motivo u observación" value={notes[row.id]??row.notes} onChange={e=>setNotes(current=>({...current,[row.id]:e.target.value}))}/>}
            {!readOnly&&<button type="button" className="secondary ops-small-button" disabled={busy} onClick={()=>void review(row,row.review_status)}>Guardar nota</button>}</td>
        </tr>)}
      </tbody></table></div>}
    </>}
  </section>
}
