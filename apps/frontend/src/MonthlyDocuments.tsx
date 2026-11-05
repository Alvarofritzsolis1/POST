import {useCallback,useEffect,useState} from "react"
import {CheckCircle2,LoaderCircle,RefreshCcw} from "lucide-react"
import {api} from "./api"
import {opsApi,type Contractor,type MonthlyRecord} from "./opsApi"
import {opsControlApi,type Requirement} from "./opsControlApi"
import "./monthly.css"
import {summarizeRequirements,statusTone,statusLabel} from "./documentUX"

const types=[
  {value:"f30",label:"Formulario F30"},
  {value:"mutualidad",label:"Certificado de afiliación a mutualidad"},
  {value:"accidentabilidad",label:"Certificado de accidentabilidad"},
  {value:"siniestralidad",label:"Certificado de siniestralidad"},
  {value:"contrato_trabajo",label:"Contrato de trabajo"},
  {value:"anexos_contrato",label:"Anexos de contrato"},
  {value:"finiquito",label:"Finiquito"},
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

export default function MonthlyDocuments({contractor,readOnly,initialPeriod,onPeriodChange,onReviewed}:{contractor:Contractor;readOnly:boolean;initialPeriod?:string;onPeriodChange?:(period:string)=>void;onReviewed?:()=>void}){
  const [period,setPeriod]=useState(()=>initialPeriod||todayMonth())
  const [rows,setRows]=useState<MonthlyRecord[]>([])
  const [requirements,setRequirements]=useState<Requirement[]>([])
  const [busy,setBusy]=useState(false)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState("")
  const [notice,setNotice]=useState("")
  const [docSearch,setDocSearch]=useState("")
  const [docState,setDocState]=useState("all")
  useEffect(()=>{
    const reveal=(event:Event)=>{
      const {kind,subject}=(event as CustomEvent<{kind:string;subject:string}>).detail||{}
      if(!kind)return
      setDocSearch("")
      setDocState("all")
      window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{
        document.getElementById("monthly-req-"+encodeURIComponent(kind)+"-"+encodeURIComponent(subject||"contractor"))?.scrollIntoView({behavior:"smooth",block:"center"})
      }))
    }
    window.addEventListener("galant-v15-document-focus",reveal)
    return()=>window.removeEventListener("galant-v15-document-focus",reveal)
  },[])
  const independent=contractor.classification==="CI"
  const withWorkers=contractor.classification==="CT"
  const inactivePeriod=contractor.contract_status!=="active" && period>=todayMonth()
  const required=requirements // Las obligaciones provienen del evaluador documental.
  const displayRows=required.filter(req=>{
    const name=(req.name||nameOf(req.kind)).toLocaleLowerCase("es-CL")
    const matches=!docSearch.trim()||name.includes(docSearch.trim().toLocaleLowerCase("es-CL"))
    const state=req.state||"pending"
    const allowed=docState==="all"||
      (docState==="approved"&&state==="approved")||
      (docState==="critical"&&["observed","rejected","overdue","incomplete","missing"].includes(state))||
      (docState==="review"&&["pending","submitted"].includes(state))||
      (docState==="excluded"&&["not_applicable","exempt","no_movements","not_required","not_yet_required","inactive"].includes(state))
    return matches&&allowed
  })

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
      await reload();onReviewed?.();setNotice("Revisión guardada para todos los usuarios autorizados.")
    }catch(err){setError(errText(err))}
    finally{setBusy(false)}
  }
  const latest=(documentKind:string)=>rows.find(row=>row.kind===documentKind)
  const summary=summarizeRequirements(requirements)
  const total=summary.required
  const approved=summary.approved
  return <section className="monthly-panel" aria-labelledby="monthly-title">
    <div className="monthly-header">
      <div><span className="eyebrow">CONTROL DOCUMENTAL COMPARTIDO</span><h3 id="monthly-title">Documentación mensual</h3>
        <p>Registros de {contractor.name} en esta obra. Las entregas informadas y revisiones se registran manualmente por mes de competencia.</p></div>
      <div className="monthly-selector"><label htmlFor="monthly-period">Mes de competencia</label>
        <input id="monthly-period" type="month" min="2000-01" max="2099-12" value={period} onChange={e=>{setPeriod(e.target.value);onPeriodChange?.(e.target.value)}}/>
        <button type="button" className="secondary" disabled={loading||busy} onClick={()=>void reload().catch(err=>setError(errText(err)))} title="Actualizar documentos"><RefreshCcw size={16}/> Actualizar</button></div>
    </div>
    {inactivePeriod&&<p className="ops-inactive-banner" role="status">Contratista inactivo: no se generan nuevas obligaciones documentales para este período. La documentación histórica permanece disponible para consulta.</p>}
    <div className="monthly-summary"><strong>{inactivePeriod?"No exigible":total?approved+" de "+total:"Sin obligaciones aplicables"}</strong><span>requisitos exigibles aprobados en {period}; no aplica y no exigible no cuentan como incumplimiento</span></div>
    {!independent&&!withWorkers&&contractor.classification!=="CE"&&<p className="ops-help">Contratista sin clasificación documental completa: confirma su naturaleza y obligaciones antes de aprobar el período.</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p className="alert success" role="status"><CheckCircle2 size={16}/>{notice}</p>}
    <div className="monthly-v15-filters" role="search" aria-label="Filtrar documentación mensual">
      <label>Buscar documento<input type="search" value={docSearch} placeholder="F30, portería, liquidaciones…" onChange={event=>setDocSearch(event.target.value)}/></label>
      <label>Estado documental<select aria-label="Filtrar por estado documental" value={docState} onChange={event=>setDocState(event.target.value)}>
        <option value="all">Todos los estados</option><option value="critical">Incumplimientos</option><option value="review">En revisión</option>
        <option value="approved">Aprobados</option><option value="excluded">No exigibles o exentos</option>
      </select></label>
      <span aria-live="polite">{displayRows.length} de {required.length} requisitos</span>
    </div>
    {loading?<p><LoaderCircle size={16} className="spin"/> Cargando documentación mensual…</p>:<>
      <div className="table-wrap"><table className="ops-list-table monthly-table"><thead><tr><th>REQUISITO</th><th>ESTADO</th><th>OBSERVACIÓN / RESPALDO</th><th>ACCIÓN</th></tr></thead><tbody>
        {displayRows.map(req=>{const item=req.kind;const row=req.worker_level?undefined:latest(item);const state=req?.state||row?.review_status||"needs_classification";return <tr key={item+"|"+(req.subject||"contractor")} id={"monthly-req-"+encodeURIComponent(item)+"-"+encodeURIComponent(req.subject||"contractor")}>
          <td><strong>{req.name||nameOf(item)}</strong><small style={{display:"block"}}>{req?.applicable===null?"Confirmar exigibilidad":req?.applicable===false?"No aplicable":"Requisito aplicable"}</small></td>
          <td><span className={"status "+({ok:"success",warn:"review",bad:"error",muted:"neutral"} as const)[statusTone(state)]}>{statusLabel(state)}</span></td>
          <td><span className="monthly-v15-observation">{row?.notes||req.notes||"Sin observaciones registradas"}</span>{row?.document_id&&<a href={api.pdf(row.document_id)} target="_blank" rel="noreferrer">{row.original_name||"Abrir archivo existente"}</a>}{!row?.document_id&&req.source&&<small className="monthly-v15-source">Revisión manual, sin archivo asociado</small>}</td>
          <td>{!readOnly&&req.worker_level?<a href={"/admin/configuracion/contratistas/"+encodeURIComponent(contractor.id)+"?tab=documentos"}>Revisar por trabajador</a>:!readOnly&&req?.applicable===true?<details className="monthly-v15-review">
            <summary>Revisar</summary>
            <div className="monthly-v15-review-actions" role="group" aria-label={"Revisión de "+(req.name||nameOf(item))}>
              <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","approved")}>Aprobar</button>
              <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","observed")}>Observar</button>
              <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","pending")}>Pendiente</button>
              <button type="button" disabled={busy} onClick={()=>void manualReview(item,req.subject||"contractor","not_applicable")}>No aplica</button>
            </div>
          </details>:req?.applicable===null?"Configura la exigibilidad en Centro de control":"—"}</td>
        </tr>})}
      </tbody></table></div>
      {!required.length&&<p className="monthly-v15-empty" role="status">No hay requisitos configurados para este contratista y período. Consulta Configuración General antes de registrar aprobaciones.</p>}
      {!!required.length&&!displayRows.length&&<p className="monthly-v15-empty" role="status">No hay documentos que coincidan con estos filtros.</p>}
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
