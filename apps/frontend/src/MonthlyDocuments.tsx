import {useCallback,useEffect,useState} from "react"
import {CheckCircle2,LoaderCircle,RefreshCcw} from "lucide-react"
import {api} from "./api"
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
  submitted:"Entregado · pendiente de revisión",missing:"No entregado",incomplete:"Entregado incompleto",exempt:"Exento",no_movements:"Sin movimientos",schedule_not_configured:"Sin calendario configurado",not_required:"No exigible",inactive:"No exigible: contratista inactivo"
}
const nameOf=(kind:string)=>types.find(item=>item.value===kind)?.label||kind
const todayMonth=()=>new Intl.DateTimeFormat("sv-SE",{timeZone:"America/Santiago",year:"numeric",month:"2-digit"}).format(new Date())
const errText=(error:unknown)=>error instanceof Error?error.message:"No fue posible completar la operación"

export default function MonthlyDocuments({contractor,readOnly,initialPeriod}:{contractor:Contractor;readOnly:boolean;initialPeriod?:string}){
  const [period,setPeriod]=useState(()=>initialPeriod||todayMonth())
  const [rows,setRows]=useState<MonthlyRecord[]>([])
  const [requirements,setRequirements]=useState<Requirement[]>([])
  const [busy,setBusy]=useState(false)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState("")
  const [notice,setNotice]=useState("")
  const independent=contractor.classification==="CI"
  const withWorkers=contractor.classification==="CT"
  const inactivePeriod=contractor.contract_status!=="active" && period>=todayMonth()
  const required=requirements.length?requirements:types.filter(t=>t.value!=="otros").map(t=>({kind:t.value} as Requirement))

  const reload=useCallback(async()=>{
    const [monthly,matrix]=await Promise.all([
      opsApi.monthlyDocuments(contractor.id,period),
      opsControlApi.matrix(contractor.site_id,period)
    ])
    setRows(monthly)
    setRequirements(matrix.contractors.find(c=>c.association_id===contractor.id)?.requirements||[])
  },[contractor.id,contractor.site_id,period])

  useEffect(()=>{
    let active=true
    const refresh=async()=>{
      try{
        const [monthly,matrix]=await Promise.all([
          opsApi.monthlyDocuments(contractor.id,period),
          opsControlApi.matrix(contractor.site_id,period)
        ])
        if(active){setRows(monthly);setRequirements(matrix.contractors.find(c=>c.association_id===contractor.id)?.requirements||[]);setError("");setLoading(false)}
      }catch(err){if(active){setError(errText(err));setLoading(false)}}
    }
    setRows([]);setLoading(true);setError("");setNotice("")
    void refresh()
    const interval=window.setInterval(()=>void refresh(),15000)
    return()=>{active=false;window.clearInterval(interval)}
  },[contractor.id,contractor.site_id,period])

  async function manualReview(documentKind:string,subject:string,status:"approved"|"observed"|"pending"|"not_applicable"){
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
      await opsControlApi.reviews({association_id:contractor.id,period,kind:documentKind,subject,status,notes:message})
      await reload();setNotice("Revisión guardada para todos los usuarios autorizados.")
    }catch(err){setError(errText(err))}
    finally{setBusy(false)}
  }
  const latest=(documentKind:string)=>rows.find(row=>row.kind===documentKind)
  const eligible=requirements.filter(r=>r.applicable===true&&!['not_yet_required','schedule_not_configured'].includes(r.state))
  const total=eligible.reduce((n,r)=>n+(r.required_count??1),0)
  const approved=eligible.reduce((n,r)=>n+(r.approved_count??(r.state==="approved"?1:0)),0)
  return <section className="monthly-panel" aria-labelledby="monthly-title">
    <div className="monthly-header">
      <div><span className="eyebrow">CONTROL DOCUMENTAL COMPARTIDO</span><h3 id="monthly-title">Documentación mensual</h3>
        <p>Registros de {contractor.name} en esta obra. Las entregas informadas y revisiones se registran manualmente por mes de competencia.</p></div>
      <div className="monthly-selector"><label htmlFor="monthly-period">Mes de competencia</label>
        <input id="monthly-period" type="month" min="2000-01" max="2099-12" value={period} onChange={e=>setPeriod(e.target.value)}/>
        <button type="button" className="secondary" disabled={loading||busy} onClick={()=>void reload().catch(err=>setError(errText(err)))} title="Actualizar documentos"><RefreshCcw size={16}/> Actualizar</button></div>
    </div>
    {inactivePeriod&&<p className="ops-inactive-banner" role="status">Contratista inactivo: no se generan nuevas obligaciones documentales para este período. La documentación histórica permanece disponible para consulta.</p>}
    <div className="monthly-summary"><strong>{inactivePeriod?"No exigible":total?approved+" de "+total:"Sin obligaciones aplicables"}</strong><span>requisitos exigibles aprobados en {period}; no aplica y no exigible no cuentan como incumplimiento</span></div>
    {!independent&&!withWorkers&&contractor.classification!=="CE"&&<p className="ops-help">Contratista sin clasificación documental completa: confirma su naturaleza y obligaciones antes de aprobar el período.</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="alert success" role="status"><CheckCircle2 size={16}/>{notice}</p>}
    {loading?<p><LoaderCircle size={16} className="spin"/> Cargando documentación mensual…</p>:<>
      <div className="table-wrap"><table className="ops-list-table monthly-table"><thead><tr><th>REQUISITO</th><th>ESTADO</th><th>DOCUMENTO</th><th>ACCIÓN</th></tr></thead><tbody>
        {required.map(req=>{const item=req.kind;const row=latest(item);const state=req?.state||row?.review_status||"needs_classification";return <tr key={item+"|"+(req.subject||"contractor")}>
          <td><strong>{req.name||nameOf(item)}</strong><small style={{display:"block"}}>{req?.applicable===null?"Confirmar exigibilidad":req?.applicable===false?"No aplicable":"Requisito aplicable"}</small></td>
          <td><span className={"status "+(state==="approved"?"success":state==="observed"||state==="rejected"||state==="overdue"?"error":state==="pending"?"review":state==="not_yet_required"||state==="not_applicable"||state==="inactive"?"neutral":"waiting")}>{statuses[state]||state}</span></td>
          <td>{row?.document_id?<a href={api.pdf(row.document_id)} target="_blank" rel="noreferrer">{row.original_name||"Abrir archivo"}</a>:req.source?"Revisión manual sin archivo":"—"}</td>
          <td>{!readOnly&&req.worker_level?<a href={"/admin/configuracion/contratistas/"+encodeURIComponent(contractor.id)+"?tab=documentos"}>Revisar por trabajador</a>:!readOnly&&req?.applicable===true?<div className="control-cell-actions">
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","approved")}>Aprobar</button>
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","observed")}>Observar</button>
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","pending")}>Pendiente</button>
            <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","not_applicable")}>No aplica</button>
          </div>:req?.applicable===null?"Configura la exigibilidad en Centro de control":"—"}</td>
        </tr>})}
      </tbody></table></div>
      <h4>Registros y respaldos existentes de {period}</h4>
      {rows.length===0?<p className="ops-help">Todavía no hay documentos vinculados a este mes. Los requisitos permanecen visibles para que puedas completarlos.</p>:
      <div className="table-wrap"><table className="ops-list-table monthly-table"><thead><tr><th>FECHA DE REGISTRO</th><th>TIPO</th><th>ARCHIVO</th><th>REVISIÓN MANUAL</th><th>OBSERVACIÓN</th></tr></thead><tbody>
        {rows.map(row=><tr key={row.id}>
          <td>{new Date(row.created_at).toLocaleDateString("es-CL")}</td>
          <td>{nameOf(row.kind)}</td>
          <td>{row.document_id?<a href={api.pdf(row.document_id)} target="_blank" rel="noreferrer">{row.original_name||"Abrir archivo"}</a>:"Revisión manual sin PDF"}<small className="monthly-ocr"> {row.ocr_status?"OCR: "+row.ocr_status:""}</small></td>
          <td>{statuses[row.review_status]||row.review_status}</td>
          <td>{row.notes||"—"}</td>
        </tr>)}
      </tbody></table></div>}
    </>}
  </section>
}
